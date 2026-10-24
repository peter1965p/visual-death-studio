"""Claude-Agent über die API: dieselbe Schnittstelle wie `ClaudeProcess` (text/tool/finished), aber mit eigenem Schlüssel und eigenen Dateiwerkzeugen.
Die Schleife läuft in einem Thread; Signale kommen sicher im GUI-Thread an."""
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from . import api
from .tools import ToolBox


class ApiAgent(QObject):
    text = Signal(str)                 # fertiger Textblock des Assistenten
    tool = Signal(str)                 # z. B. "write_file main.py"
    finished = Signal(bool, str, str)  # ok, Ergebnistext bzw. Fehlermeldung, Sitzungs-ID

    SESSION = "api"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.history: list = []
        self._thread: threading.Thread | None = None
        self._cancel = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None

    def run(self, prompt: str, cwd: Path, session: str | None = None, allow_bash: bool = False, system: str | None = None, max_turns: int = 30):
        if self.running:
            return
        if session != self.SESSION:
            self.history = []                                  # neue Unterhaltung
        self._cancel = threading.Event()
        cfg = api.config("chat")
        self._thread = threading.Thread(target=self._loop, args=(cfg, Path(cwd), allow_bash, system or "", max_turns, prompt), daemon=True)
        self._thread.start()

    def stop(self):
        self._cancel.set()

    # --- Schleife (Thread) ---------------------------------------------------------------------
    def _loop(self, cfg, cwd, allow_bash, system, max_turns, prompt):
        result = (False, "Unbekannter Fehler.", self.SESSION)
        try:
            result = self._agent(cfg, cwd, allow_bash, system, max_turns, prompt)
        except api.Cancelled:
            self.history = self._trim(self.history)
            result = (False, "Abgebrochen.", self.SESSION)
        except Exception as e:                                 # API-, Netzwerk- und Programmfehler gehören in den Chat, nicht in den Absturz
            self.history = self._trim(self.history)
            result = (False, api.describe_error(e), self.SESSION)
        finally:
            self._thread = None
        self.finished.emit(*result)

    @staticmethod
    def _trim(history: list) -> list:
        """Nach Abbruch/Fehler zurück zur letzten abgeschlossenen Runde (keine offene Nutzereingabe, kein tool_use ohne Ergebnis)."""
        while history:
            last = history[-1]
            blocks = last["content"] if isinstance(last["content"], list) else []
            if last["role"] == "assistant" and not any(getattr(b, "type", "") == "tool_use" for b in blocks):
                break
            history.pop()
        return history

    def _agent(self, cfg, cwd, allow_bash, system, max_turns, prompt) -> tuple:
        if not cfg.key:
            return False, "Kein API-Schlüssel hinterlegt (Extras → Optionen → Claude).", self.SESSION
        client = api.make_client(cfg)
        box = ToolBox(cwd, allow_bash)
        tools = box.definitions(eager=cfg.official)
        messages = self.history
        messages.append({"role": "user", "content": prompt})
        last_text = ""
        for _turn in range(max_turns):
            msg = api.stream_message(client, cfg, api.request_kwargs(cfg, system, messages, tools), self._cancel, on_text=self._emit_text)
            if msg.stop_reason == "refusal":
                messages.pop()                                 # abgelehnte Eingabe nicht im Verlauf behalten
                return False, api.refusal_text(msg), self.SESSION
            texts = [b.text for b in msg.content if b.type == "text" and b.text.strip()]
            last_text = texts[-1] if texts else last_text
            messages.append({"role": "assistant", "content": api.echo_content(msg.content)})
            uses = [b for b in msg.content if b.type == "tool_use"]
            if msg.stop_reason == "pause_turn":
                continue
            if not uses:
                if msg.stop_reason == "max_tokens":
                    return False, "Die Antwort wurde wegen des Token-Limits abgeschnitten (Optionen → Claude → Max. Ausgabe erhöhen).", self.SESSION
                return True, last_text, self.SESSION
            if msg.stop_reason == "max_tokens":
                messages.pop()
                return False, "Die Antwort wurde mitten in einem Werkzeugaufruf abgeschnitten (Optionen → Claude → Max. Ausgabe erhöhen).", self.SESSION
            results = []
            for u in uses:
                if self._cancel.is_set():
                    raise api.Cancelled()
                self.tool.emit(box.label(u.name, u.input if isinstance(u.input, dict) else {}))
                out, is_err = box.execute(u.name, u.input, self._cancel)
                results.append({"type": "tool_result", "tool_use_id": u.id, "content": out, **({"is_error": True} if is_err else {})})
            messages.append({"role": "user", "content": results})          # alle Ergebnisse in EINER Nachricht
        return False, f"Abbruch nach {max_turns} Schritten.", self.SESSION

    def _emit_text(self, t: str):
        self.text.emit(t)
