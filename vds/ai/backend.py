"""Wählt den Claude-Anbieter: lokale Claude-Code-CLI oder eigener API-Schlüssel (Extras → Optionen → Claude)."""
from .. import options
from . import api, claude_cli, keystore


def provider() -> str:
    return options.get("claude/provider")


def available() -> bool:
    return bool(keystore.load()) if provider() == "api" else claude_cli.available()


def unavailable_message() -> str:
    if provider() == "api":
        return "**Kein API-Schlüssel hinterlegt.** Trage ihn unter Extras → Optionen → Claude ein (oder setze ANTHROPIC_API_KEY)."
    return "**Claude-CLI nicht gefunden.** Installiere Claude Code und melde dich an – oder nutze unter Extras → Optionen → Claude einen eigenen API-Schlüssel."


def label() -> str:
    return f"Claude-API ({api.config('chat').model})" if provider() == "api" else "Claude Code (lokale Anmeldung)"


def make_agent(parent=None):
    from .agent import ApiAgent
    return ApiAgent(parent) if provider() == "api" else claude_cli.ClaudeProcess(parent)
