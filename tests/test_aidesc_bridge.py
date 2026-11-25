"""Die Anbindung an AI-Desc: Der Chat bekommt den MCP-Server, der Projekt-Assistent nicht, und ohne AI-Desc läuft alles wie vorher."""
import json

import pytest

from vds import options
from vds.ai import aidesc, claude_cli


class FakeProcess:
    """Merkt sich die Argumente, statt Claude zu starten."""
    last = None

    class _Sig:
        def connect(self, *_a):
            pass

    readyReadStandardOutput = readyReadStandardError = errorOccurred = finished = _Sig()

    def __init__(self, *_a):
        pass

    def setWorkingDirectory(self, *_a):
        pass

    def setProcessChannelMode(self, *_a):
        pass

    def start(self, _program, args):
        FakeProcess.last = args

    def closeWriteChannel(self):
        pass


@pytest.fixture
def installed(qapp, tmp_path, monkeypatch):
    (tmp_path / "aidesc").mkdir()
    (tmp_path / "aidesc" / "__main__.py").write_text("")
    options.reset(["ai/aidesc_mcp", "ai/aidesc_path"])
    options.set("ai/aidesc_path", str(tmp_path))
    monkeypatch.setattr(claude_cli, "QProcess", FakeProcess)
    monkeypatch.setattr(claude_cli.QProcess, "SeparateChannels", 0, raising=False)
    yield tmp_path
    options.reset(["ai/aidesc_mcp", "ai/aidesc_path"])


def run(tmp_path, use_aidesc):
    process = claude_cli.ClaudeProcess()
    process.use_aidesc = use_aidesc
    process.run("Hallo", tmp_path)
    return FakeProcess.last


def test_the_chat_gets_the_server_and_may_use_its_tools(installed):
    args = run(installed, True)
    server = json.loads(args[args.index("--mcp-config") + 1])["mcpServers"]["aidesc"]
    assert server["args"] == ["-m", "aidesc", "mcp"]
    assert server["env"]["PYTHONPATH"] == str(installed)
    allowed = args[args.index("--allowedTools") + 1].split(",")
    assert aidesc.TOOLS in allowed and "Bash" not in allowed


def test_the_project_wizard_stays_as_it_was(installed):
    args = run(installed, False)
    assert "--mcp-config" not in args
    assert aidesc.TOOLS not in args[args.index("--allowedTools") + 1]


def test_switched_off_or_missing_means_no_server(installed, tmp_path):
    options.set("ai/aidesc_mcp", False)
    assert "--mcp-config" not in run(installed, True)
    options.set("ai/aidesc_mcp", True)
    options.set("ai/aidesc_path", str(tmp_path / "gibt-es-nicht"))
    assert "--mcp-config" not in run(installed, True)


def test_the_chat_shows_a_readable_tool_name(tmp_path):
    assert claude_cli.describe_tool("mcp__aidesc__archiv_suchen", {"text": "Zebra"}, tmp_path) == "AI-Desc: archiv_suchen Zebra"
    assert claude_cli.describe_tool("Write", {"file_path": str(tmp_path / "a.py")}, tmp_path) == "Write a.py"
