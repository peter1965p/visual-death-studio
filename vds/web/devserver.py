"""Erkennt die Adresse eines laufenden Dev-Servers (Vite, Next, Nuxt, Angular, php -S, artisan serve …) in der Programmausgabe."""
import re

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|[\w.-]+\.local)(?::\d{2,5})?(?:/[^\s\]\)\"'>]*)?", re.I)
SKIP_BEFORE = ("network", "press h", "docs", "see ")


def find_url(text: str) -> str | None:
    """Erste lokale Adresse im Text (ohne „Network:“-Zeilen); 0.0.0.0 wird zu localhost."""
    for line in ANSI.sub("", text).splitlines():
        low = line.lower()
        m = URL.search(line)
        if not m or any(k in low[: m.start()] for k in SKIP_BEFORE):
            continue
        url = m.group(0).rstrip(".,;")
        return url.replace("0.0.0.0", "localhost").replace("[::]", "localhost").replace("[::1]", "localhost")
    return None
