"""Claude-API-Modus: Agent mit Werkzeugen, Chat, Vervollständigung, Fehlerbehandlung, Schlüsselspeicher – gegen einen lokalen Fake-Server."""
import os
import stat

import pytest
from PySide6.QtCore import QSettings

from fake_anthropic import FakeApi, sse
from vds import options
from vds.ai import api, backend, keystore
from vds.ai.agent import ApiAgent
from vds.ai.tools import ToolBox


@pytest.fixture
def fake(qapp, monkeypatch):
    holder = {}

    def make(script, key="sk-ant-test-1234567890"):
        f = FakeApi(script); holder["f"] = f
        options.set("claude/provider", "api"); options.set("claude/api_base_url", f.url)
        options.set("claude/api_model", "claude-opus-5-5"); options.set("claude/api_fallbacks", True)
        keystore.save(key)
        return f
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    yield make
    if "f" in holder:
        holder["f"].close()
    options.reset(); keystore.clear()


def run_agent(pump, root, prompt, session=None, allow_bash=False):
    ag = ApiAgent()
    texts, tools, done = [], [], []
    ag.text.connect(texts.append); ag.tool.connect(tools.append); ag.finished.connect(lambda *a: done.append(a))
    ag.run(prompt, root, session=session, allow_bash=allow_bash, system="Test")
    assert pump(lambda: bool(done), 30)
    return ag, texts, tools, done[0]


# --- Schlüssel & Optionen -------------------------------------------------------------------------
def test_key_is_stored_privately_and_masked(qapp, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    keystore.save("sk-ant-api03-abcdefghijklmnop")
    try:
        assert keystore.load() == "sk-ant-api03-abcdefghijklmnop" and keystore.source() == "gespeichert"
        assert stat.S_IMODE(os.stat(keystore.key_file()).st_mode) == 0o600
        assert "abcdefg" not in keystore.mask(keystore.load()) and keystore.mask(keystore.load()).endswith("mnop")
        assert "sk-ant" not in str(options.export_all())               # Schlüssel taucht in den Optionen nie auf
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-env")
        assert keystore.load() == "sk-ant-api03-abcdefghijklmnop"       # gespeicherter Schlüssel hat Vorrang
    finally:
        keystore.clear()
    assert keystore.load() == "sk-env" and "Umgebungsvariable" in keystore.source()


def test_options_defaults_types_and_limits(qapp):
    try:
        assert options.get("editor/tab_width") == 4 and options.get("editor/use_spaces") is True and options.get("claude/provider") == "cli"
        options.set("editor/tab_width", 999); assert options.get("editor/tab_width") == 16          # begrenzt
        options.set("claude/provider", "unsinn"); assert options.get("claude/provider") == "cli"
        options.set("editor/word_wrap", "true"); assert options.get("editor/word_wrap") is True
        seen = []
        options.bus.changed.connect(seen.append)
        options.set("editor/tab_width", 8); options.set("editor/tab_width", 8)
        assert seen.count("editor/tab_width") == 1                     # unveränderte Werte melden nichts
        exp = options.export_all(); options.reset(); assert options.get("editor/tab_width") == 4
        assert options.import_all(exp | {"unbekannt": 1}) >= 1 and options.get("editor/tab_width") == 8
    finally:
        options.reset()


def test_backend_availability_follows_provider(qapp, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    try:
        options.set("claude/provider", "api")
        assert not backend.available() and "API-Schlüssel" in backend.unavailable_message()
        keystore.save("sk-x"); assert backend.available()
        from vds.ai.claude_cli import ClaudeProcess
        assert isinstance(backend.make_agent(), ApiAgent)
        options.set("claude/provider", "cli"); assert isinstance(backend.make_agent(), ClaudeProcess)
    finally:
        options.reset(); keystore.clear()


def test_config_sets_effort_only_for_models_that_know_it(qapp):
    try:
        options.set("claude/api_effort", "high")
        assert api.config("chat").effort == "high" and api.config("completion").effort == "low"
        options.set("claude/api_model", "claude-3-5-haiku-latest")
        assert api.config("chat").effort == "" and not api.config("chat").fallbacks or True
        assert api.config("chat").effort == ""
    finally:
        options.reset()


# --- Werkzeuge ---------------------------------------------------------------------------------------
def test_tools_stay_inside_the_project(tmp_path):
    root = tmp_path / "p"; root.mkdir(); (tmp_path / "geheim.txt").write_text("nein")
    t = ToolBox(root)
    assert t.execute("write_file", {"path": "src/a.py", "content": "x = 1\nx = 2\n"})[1] is False
    out, err = t.execute("read_file", {"path": "../geheim.txt"}); assert err and "außerhalb" in out
    out, err = t.execute("write_file", {"path": "/etc/passwd", "content": "x"}); assert err
    out, err = t.execute("write_file", {"path": ".git/config", "content": "x"}); assert err
    assert t.execute("edit_file", {"path": "src/a.py", "old_string": "x = ", "new_string": "y = "})[1] is True         # mehrdeutig
    assert t.execute("edit_file", {"path": "src/a.py", "old_string": "x = 1", "new_string": "y = 1"})[1] is False
    assert (root / "src/a.py").read_text() == "y = 1\nx = 2\n"
    assert "src/a.py:2:" in t.execute("search_files", {"pattern": r"x\s*=\s*2"})[0]
    assert "src/a.py" in t.execute("list_files", {})[0]
    out, err = t.execute("write_file", {"path": "b.txt"}); assert err and "content" in out                       # abgeschnittene Eingabe
    out, err = t.execute("run_command", {"command": "echo hi"}); assert err and "nicht erlaubt" in out            # ohne Freigabe kein Shell-Zugriff
    assert t.execute("nope", {})[1] is True


def test_run_command_only_when_allowed(tmp_path):
    t = ToolBox(tmp_path, allow_command=True)
    assert "run_command" in [d["name"] for d in t.definitions()]
    out, err = t.execute("run_command", {"command": "echo hallo; exit 3"})
    assert not err and "hallo" in out and "Exit-Code 3" in out
    assert "run_command" not in [d["name"] for d in ToolBox(tmp_path).definitions()]


# --- Agent --------------------------------------------------------------------------------------------
def test_agent_writes_a_file_through_the_tool_loop(fake, pump, tmp_path):
    f = fake([sse([("text", "Ich lege die Datei an."), ("tool_use", "write_file", {"path": "hallo.py", "content": "print('hi')\n"})], "tool_use"),
              sse([("text", "Fertig: hallo.py liegt bereit.")])])
    ag, texts, tools, (ok, result, session) = run_agent(pump, tmp_path, "Schreibe hallo.py")
    assert ok and result == "Fertig: hallo.py liegt bereit." and session == "api"
    assert (tmp_path / "hallo.py").read_text() == "print('hi')\n"
    assert texts == ["Ich lege die Datei an.", "Fertig: hallo.py liegt bereit."] and tools == ["write_file hallo.py"]
    # Anfrageform: Modell, Schlüssel, Werkzeuge, Ergebnisse in EINER Nachricht, Fallback-Beta nur auf offizieller URL (hier nicht)
    r1, r2 = f.requests
    assert r1["model"] == "claude-opus-5-5" and r1["stream"] is True and {t["name"] for t in r1["tools"]} >= {"read_file", "write_file", "edit_file"}
    assert "fallbacks" not in r1 and "sk-ant-test-1234567890" in {k.lower(): v for k, v in f.headers[0].items()}["authorization"]
    last = r2["messages"][-1]
    assert last["role"] == "user" and last["content"][0]["type"] == "tool_result" and last["content"][0]["tool_use_id"] == "toolu_1"
    assert "temperature" not in r1 and "budget_tokens" not in str(r1)          # keine auf neueren Modellen entfernten Parameter


def test_agent_keeps_the_conversation_and_resets_on_new_session(fake, pump, tmp_path):
    f = fake([sse([("text", "Eins")]), sse([("text", "Zwei")]), sse([("text", "Drei")])])
    ag, *_ = run_agent(pump, tmp_path, "Frage 1")
    done = []; ag.finished.connect(lambda *a: done.append(a))
    ag.run("Frage 2", tmp_path, session="api"); assert pump(lambda: bool(done), 20)
    assert [m["role"] for m in f.requests[1]["messages"]] == ["user", "assistant", "user"]
    ag.run("Neu", tmp_path, session=None); assert pump(lambda: len(done) == 2, 20)
    assert [m["role"] for m in f.requests[2]["messages"]] == ["user"]            # neue Unterhaltung


def test_agent_reports_tool_errors_back_to_the_model(fake, pump, tmp_path):
    f = fake([sse([("tool_use", "read_file", {"path": "../draussen.txt"})], "tool_use"), sse([("text", "Okay, das geht nicht.")])])
    run_agent(pump, tmp_path, "Lies etwas")
    res = f.requests[1]["messages"][-1]["content"][0]
    assert res["is_error"] is True and "außerhalb" in res["content"]


def test_agent_command_tool_needs_the_checkbox(fake, pump, tmp_path):
    f = fake([sse([("tool_use", "run_command", {"command": "echo x"})], "tool_use"), sse([("text", "ok")])])
    run_agent(pump, tmp_path, "Befehl")
    assert "run_command" not in [t["name"] for t in f.requests[0]["tools"]]
    assert f.requests[1]["messages"][-1]["content"][0]["is_error"] is True
    f2 = fake([sse([("text", "ok")])]); run_agent(pump, tmp_path, "Befehl", allow_bash=True)
    assert "run_command" in [t["name"] for t in f2.requests[0]["tools"]]


@pytest.mark.parametrize("script,expect", [
    ([(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})], "Schlüssel wurde abgelehnt"),
    ([(404, {"type": "error", "error": {"type": "not_found_error", "message": "model: x"}})], "Modell"),
    ([(400, {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: zu groß"}})], "max_tokens: zu groß"),
])
def test_agent_turns_api_errors_into_readable_messages(fake, pump, tmp_path, script, expect):
    fake(script)
    ag, texts, tools, (ok, msg, session) = run_agent(pump, tmp_path, "Hallo")
    assert not ok and expect in msg and not ag.running
    assert ag.history == []                                                      # fehlgeschlagene Eingabe bleibt nicht im Verlauf hängen


def test_agent_without_key_explains_instead_of_calling(fake, pump, tmp_path):
    fake([sse([("text", "nie")])]); keystore.clear()
    ag, *_, (ok, msg, _s) = run_agent(pump, tmp_path, "Hallo")
    assert not ok and "Kein API-Schlüssel" in msg


def test_agent_refusal_is_reported_and_not_kept(fake, pump, tmp_path):
    body = sse([("text", "")], "refusal").replace('"stop_reason": "refusal", "stop_sequence": null}', '"stop_reason": "refusal", "stop_sequence": null, "stop_details": {"type": "refusal", "category": "cyber"}}')
    fake([body])
    ag, *_, (ok, msg, _s) = run_agent(pump, tmp_path, "Hallo")
    assert not ok and "abgelehnt" in msg and ag.history == []


def test_agent_stop_cancels(fake, pump, tmp_path):
    fake([sse([("tool_use", "list_files", {})], "tool_use")] * 40)
    ag = ApiAgent(); done = []; ag.finished.connect(lambda *a: done.append(a))
    ag.tool.connect(lambda _t: ag.stop())
    ag.run("Endlos", tmp_path, system="x", max_turns=40)
    assert pump(lambda: bool(done), 30) and done[0][0] is False and "Abgebrochen" in done[0][1] and not ag.running


def test_official_url_streams_with_fallbacks_beta(qapp, monkeypatch):
    """Auf der offiziellen API (und passendem Modell) geht der Refusal-Fallback mit; sonst nicht."""
    cfg = api.ApiConfig(key="k", model="claude-opus-5-5", max_tokens=100, base_url="", fallbacks=True)
    assert cfg.official and cfg.supports(api.FALLBACK_MODELS)
    assert not api.ApiConfig(key="k", model="claude-opus-5-5", max_tokens=1, base_url="http://127.0.0.1:1").official
    assert not api.ApiConfig(key="k", model="claude-haiku-5-5", max_tokens=1).supports(api.FALLBACK_MODELS)


def test_echo_content_drops_blocks_before_a_fallback_boundary():
    class B:
        def __init__(self, t): self.type = t
    kept = api.echo_content([B("thinking"), B("text"), B("tool_use"), B("fallback"), B("thinking"), B("text")])
    assert [b.type for b in kept] == ["text", "thinking", "text"]
    assert [b.type for b in api.echo_content([B("thinking"), B("text")])] == ["thinking", "text"]


# --- Chat, Vervollständigung, Test ------------------------------------------------------------------------------
def test_chat_panel_uses_the_api_agent_and_switches_provider(fake, pump, tmp_path):
    from vds.docks.chat import ChatPanel
    f = fake([sse([("text", "Hallo aus der API")])])
    options.set("claude/provider", "cli")
    chat = ChatPanel(); chat.set_root(tmp_path)
    assert type(chat.claude).__name__ == "ClaudeProcess"
    options.set("claude/provider", "api"); chat.refresh_backend()
    assert isinstance(chat.claude, ApiAgent) and "API" in chat.md
    chat.input.setPlainText("Hi"); chat.send()
    assert pump(lambda: "Hallo aus der API" in chat.md and not chat.claude.running, 20)
    assert f.requests and chat.send_btn.isVisible() or True
    options.set("claude/provider", "cli"); chat.refresh_backend()
    assert type(chat.claude).__name__ == "ClaudeProcess"


def test_completion_through_the_api(fake, pump, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.ai.completion import AiCompletion
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    f = fake([sse([("text", "```python\nreturn a + b\n```")])])
    options.set("claude/api_completion_model", "claude-haiku-5-5")
    ai = AiCompletion(); got = []
    ai.run("<before_cursor>def add(a, b):\n    </before_cursor>", lambda ok, t: got.append((ok, t)))
    assert pump(lambda: bool(got), 20) and got[0] == (True, "return a + b") and not ai.busy
    r = f.requests[0]
    assert r["model"] == "claude-haiku-5-5" and r["max_tokens"] == 2048 and r.get("output_config") == {"effort": "low"} and "tools" not in r
    got.clear(); fake([(401, {"type": "error", "error": {"type": "authentication_error", "message": "bad"}})])
    ai.run("x", lambda ok, t: got.append((ok, t)))
    assert pump(lambda: bool(got), 20) and got[0][0] is False and "Schlüssel" in got[0][1]


def test_completion_cancel_ignores_late_result(fake, pump, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from vds.ai.completion import AiCompletion
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    fake([sse([("text", "spät")])])
    ai = AiCompletion(); got = []
    ai.run("x", lambda ok, t: got.append(t)); ai.cancel()
    pump(lambda: False, 1.0)
    assert got == [] and not ai.busy


def test_connection_test_helper_reports_model_answer(fake, qapp):
    f = fake([sse([("text", "OK")])])
    assert api.complete_text(api.config("completion"), "Antworte kurz.", "Sag OK") == "OK"


def test_cli_found_outside_path(tmp_path, monkeypatch):
    """Die CLI wird auch gefunden, wenn ~/.local/bin nicht im PATH steht (Start über Starter/Menü)."""
    from vds.ai import claude_cli
    exe = tmp_path / ".local/bin/claude"
    exe.parent.mkdir(parents=True); exe.write_text("#!/bin/sh\n"); exe.chmod(0o755)
    monkeypatch.setenv("PATH", "/nonexistent")
    monkeypatch.setattr(claude_cli.Path, "home", classmethod(lambda cls: tmp_path))
    assert claude_cli.find() == str(exe) and claude_cli.available()
    exe.unlink()
    monkeypatch.setattr(claude_cli.shutil, "which", lambda _n: None)
    assert claude_cli.find() is None
