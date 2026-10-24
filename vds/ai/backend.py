"""Wählt den Claude-Anbieter: lokale Claude-Code-CLI oder eigener API-Schlüssel (Extras → Optionen → Claude)."""
from .. import options
from . import api, claude_cli, keystore


def setting() -> str:
    return options.get("claude/provider")


def provider() -> str:
    """Wirksamer Anbieter: bei „auto“ Claude Code, wenn installiert, sonst die API, wenn ein Schlüssel hinterlegt ist."""
    s = setting()
    if s != "auto":
        return s
    return "cli" if claude_cli.available() or not keystore.load() else "api"


def available() -> bool:
    return bool(keystore.load()) if provider() == "api" else claude_cli.available()


def unavailable_message() -> str:
    if provider() == "api":
        return "**Kein API-Schlüssel hinterlegt.** Trage ihn unter Extras → Optionen → Claude ein (oder setze ANTHROPIC_API_KEY)."
    if setting() == "auto":
        return "**Weder Claude Code noch ein API-Schlüssel gefunden.** Installiere Claude Code und melde dich an – oder trage unter Extras → Optionen → Claude einen API-Schlüssel ein."
    return "**Claude Code nicht gefunden.** Installiere Claude Code und melde dich an – oder nutze unter Extras → Optionen → Claude einen eigenen API-Schlüssel."


def label() -> str:
    return f"Claude-API ({api.config('chat').model})" if provider() == "api" else "Claude Code (lokale Anmeldung)"


def make_agent(parent=None):
    from .agent import ApiAgent
    return ApiAgent(parent) if provider() == "api" else claude_cli.ClaudeProcess(parent)
