"""Erkennt die Adresse eines laufenden Dev-Servers (Vite, Next, Nuxt, Angular, php -S, artisan serve …) in der Programmausgabe."""
import json
import re
from pathlib import Path

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


def detect_command(root: Path) -> str | None:
    """Start-Befehl des Projekts, wenn es keinen eingetragenen gibt: Laravel (artisan), Node-Projekte mit dev- bzw. start-Skript (Vite, Next, Nuxt, Angular)."""
    root = Path(root)
    if (root / "artisan").is_file() and (root / "composer.json").is_file():
        return "php artisan serve"
    try:
        scripts = json.loads((root / "package.json").read_text(encoding="utf-8")).get("scripts", {})
    except (OSError, ValueError):
        return None
    install = "[ -d node_modules ] || npm install; "
    if "dev" in scripts:
        return install + "npm run dev"
    if "start" in scripts and ("ng " in scripts["start"] or (root / "angular.json").exists()):
        return install + "npm start"
    return None
