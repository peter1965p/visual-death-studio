"""Anbindung an die Claude-API über das offizielle Python-SDK (`anthropic`): eigener API-Schlüssel statt Claude-Code-Anmeldung."""
import threading
from dataclasses import dataclass

import anthropic

from .. import options
from . import keystore

OFFICIAL_HOST = "api.anthropic.com"
MODEL_PRESETS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1"]
# Modelle, die `output_config.effort` kennen (andere lehnen den Parameter ab)
EFFORT_MODELS = ("claude-opus-5", "claude-sonnet-5", "claude-haiku-5", "claude-fable", "claude-mythos", "claude-opus-4-8", "claude-opus-4-7",
                 "claude-opus-4-6", "claude-sonnet-4-6")
# Modelle mit Refusal-Fallback (beta, nur auf der offiziellen API)
FALLBACK_MODELS = ("claude-fable", "claude-opus-5", "claude-sonnet-5-5")
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class Cancelled(Exception):
    pass


@dataclass
class ApiConfig:
    key: str
    model: str
    max_tokens: int
    base_url: str = ""
    effort: str = ""
    fallbacks: bool = False

    @property
    def official(self) -> bool:
        return not self.base_url or OFFICIAL_HOST in self.base_url

    def supports(self, prefixes) -> bool:
        return self.model.startswith(prefixes)


def config(kind: str = "chat") -> ApiConfig:
    """Aktuelle Einstellungen: kind = chat (Agent, Assistent) oder completion (kurze Codevorschläge)."""
    chat = kind == "chat"
    cfg = ApiConfig(key=keystore.load(), model=options.get("claude/api_model" if chat else "claude/api_completion_model").strip(),
                    max_tokens=options.get("claude/api_max_tokens") if chat else 2048, base_url=options.get("claude/api_base_url").strip(),
                    effort=options.get("claude/api_effort") if chat else "low", fallbacks=bool(options.get("claude/api_fallbacks")) and chat)
    if not cfg.supports(EFFORT_MODELS):
        cfg.effort = ""
    return cfg


def make_client(cfg: ApiConfig, timeout: float = 600.0) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=cfg.key, base_url=cfg.base_url or None, timeout=timeout, max_retries=2)


def request_kwargs(cfg: ApiConfig, system: str, messages: list, tools: list | None = None) -> dict:
    kw = dict(model=cfg.model, max_tokens=cfg.max_tokens, system=system, messages=messages)
    if tools:
        kw["tools"] = tools
    if cfg.effort:
        kw["output_config"] = {"effort": cfg.effort}
    return kw


def describe_error(e: Exception) -> str:
    if isinstance(e, anthropic.AuthenticationError):
        return "Der API-Schlüssel wurde abgelehnt (ungültig oder widerrufen). Prüfe ihn unter Extras → Optionen → Claude."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "Der API-Schlüssel hat keine Berechtigung für diese Anfrage."
    if isinstance(e, anthropic.NotFoundError):
        return "Modell oder Adresse nicht gefunden – prüfe den Modellnamen unter Extras → Optionen → Claude."
    if isinstance(e, anthropic.RateLimitError):
        wait = e.response.headers.get("retry-after", "")
        return "Rate-Limit erreicht" + (f" – bitte in {wait} s erneut versuchen." if wait else " – bitte später erneut versuchen.")
    if isinstance(e, anthropic.APITimeoutError):
        return "Zeitüberschreitung bei der Verbindung zur Claude-API."
    if isinstance(e, anthropic.APIConnectionError):
        return "Keine Verbindung zur Claude-API – Netzwerk oder Adresse prüfen."
    if isinstance(e, anthropic.APIStatusError):
        return f"API-Fehler {e.status_code}: {e.message}"
    return str(e) or e.__class__.__name__


def refusal_text(msg) -> str:
    cat = getattr(getattr(msg, "stop_details", None), "category", None)
    return "Claude hat die Anfrage abgelehnt" + (f" (Kategorie: {cat})" if cat else "") + "."


def stream_message(client, cfg: ApiConfig, kw: dict, cancel: threading.Event, on_text=None):
    """Eine Anfrage per Streaming (kein HTTP-Timeout bei langen Antworten); gibt die fertige Nachricht zurück.
    Bei Modellen mit Refusal-Fallback wird `fallbacks: "default"` mitgeschickt (nur offizielle API, abschaltbar)."""
    use_fb = cfg.fallbacks and cfg.official and cfg.supports(FALLBACK_MODELS)
    mgr = client.beta.messages.stream(**kw, betas=[FALLBACK_BETA], fallbacks="default") if use_fb else client.messages.stream(**kw)
    with mgr as stream:
        for event in stream:
            if cancel.is_set():
                raise Cancelled()
            if on_text and event.type == "content_block_stop" and getattr(event.content_block, "type", "") == "text":
                if event.content_block.text.strip():
                    on_text(event.content_block.text)
        return stream.get_final_message()


def echo_content(content: list) -> list:
    """Antwortblöcke für den Gesprächsverlauf: nach einem Fallback mitten in der Antwort gehören nur Text- und spätere Blöcke zurück
    (thinking, tool_use und der `fallback`-Marker vor der Grenze werden weggelassen)."""
    last = max((i for i, b in enumerate(content) if b.type == "fallback"), default=-1)
    out = []
    for i, b in enumerate(content):
        if b.type == "fallback":
            continue
        if i < last and b.type != "text":
            continue
        out.append(b)
    return out


def complete_text(cfg: ApiConfig, system: str, prompt: str, timeout: float = 60.0) -> str:
    """Kurzer Aufruf ohne Werkzeuge (Codevervollständigung, Verbindungstest). Gibt den Text zurück oder wirft."""
    client = make_client(cfg, timeout)
    msg = client.messages.create(**request_kwargs(cfg, system, [{"role": "user", "content": prompt}]))
    if msg.stop_reason == "refusal":
        raise RuntimeError(refusal_text(msg))
    return "".join(b.text for b in msg.content if b.type == "text")
