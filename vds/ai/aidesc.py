"""Anbindung an AI-Desc: dessen MCP-Server gibt Claude im Chat das Archiv früherer Chats, den Systemstatus und die lokalen Modelle.

AI-Desc ist ein eigenes Programm mit eigenem Python. Die IDE startet es nur als Prozess und importiert nichts daraus."""
import json
import os
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment

from .. import options

TOOLS = "mcp__aidesc__*"
PREFIX = "mcp__aidesc__"


def folder() -> Path:
    return Path(options.get("ai/aidesc_path")).expanduser()


def installed() -> bool:
    return (folder() / "aidesc" / "__main__.py").is_file()


def python() -> str:
    """Das System-Python: Dort liegen psutil und PyQt6 für AI-Desc. Ein aktiviertes venv der IDE hätte sie nicht."""
    return "/usr/bin/python3" if os.access("/usr/bin/python3", os.X_OK) else "python3"


def mcp_config() -> str | None:
    """Der Wert für `claude --mcp-config`, oder None, wenn die Anbindung aus ist oder AI-Desc fehlt."""
    if not options.get("ai/aidesc_mcp") or not installed():
        return None
    return json.dumps({"mcpServers": {"aidesc": {"type": "stdio", "command": python(), "args": ["-m", "aidesc", "mcp"], "env": {"PYTHONPATH": str(folder())}}}})


def open_window(parent=None) -> bool:
    """Das AI-Desc-Fenster als eigenen Prozess starten; es läuft auch nach dem Schließen der IDE weiter."""
    if not installed():
        return False
    process = QProcess(parent)
    process.setProgram(python())
    process.setArguments(["-m", "aidesc"])
    process.setWorkingDirectory(str(folder()))
    env = QProcessEnvironment.systemEnvironment()
    env.insert("PYTHONPATH", str(folder()))
    process.setProcessEnvironment(env)
    return process.startDetached()[0]
