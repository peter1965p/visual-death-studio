"""Erkennt die Adresse eines laufenden Dev-Servers (Vite, Next, Nuxt, Angular, php -S, artisan serve …) in der Programmausgabe."""
import json
import re
from pathlib import Path

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
URL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1?\]|[\w.-]+\.local)(?::\d{2,5})?(?:/[^\s\]\)\"'>]*)?", re.I)
SKIP_BEFORE = ("network", "press h", "docs", "see ")
# Anwendungsserver ohne http://-Adresse in der Ausgabe (RoadRunner, FrankenPHP/Caddy, Swoole): "address": "[::]:8080", "serving on :8080", "listening on 0.0.0.0:9501"
ADDR_JSON = re.compile(r'"address"\s*:\s*"(?:[\w.\[\]:*-]*):(\d{2,5})"')
ADDR_TEXT = re.compile(r"(?:listening|serving|running|started|server)[^\n]{0,70}?(?:\bon\b|\bat\b|address)[\s:=\[\"]*(?:https?://)?(?:\[::\]|0\.0\.0\.0|localhost|127\.0\.0\.1|\*)?:(\d{2,5})\b", re.I)
# Spring Boot: "Tomcat started on port 8080 (http) with context path '/'" (auch Netty/Jetty/Undertow)
SPRING_PORT = re.compile(r"\bstarted on ports?\(?s?\)?[: ]+(\d{2,5})\b", re.I)


def find_url(text: str) -> str | None:
    """Erste lokale Adresse im Text (ohne „Network:“-Zeilen); 0.0.0.0 wird zu localhost."""
    for line in ANSI.sub("", text).splitlines():
        low = line.lower()
        m = URL.search(line)
        if not m or any(k in low[: m.start()] for k in SKIP_BEFORE):
            continue
        url = m.group(0).rstrip(".,;")
        return url.replace("0.0.0.0", "localhost").replace("[::]", "localhost").replace("[::1]", "localhost")
    for line in ANSI.sub("", text).splitlines():                    # zweiter Durchgang: nur Port ohne Schema
        low = line.lower()
        m = ADDR_JSON.search(line) or ADDR_TEXT.search(line) or SPRING_PORT.search(line)
        if m and not any(k in low for k in ("network", "grpc", "metrics", "rpc", "pprof", "health")):
            return f"http://localhost:{m.group(1)}"
    return None


def _spring_command(root: Path) -> str | None:
    """Spring Boot mit Maven (mvnw bzw. mvn) oder Gradle (gradlew bzw. gradle)."""
    def has(name: str, needle: str) -> bool:
        try:
            return needle in (root / name).read_text(encoding="utf-8")
        except OSError:
            return False
    if has("pom.xml", "spring-boot"):
        return "./mvnw spring-boot:run" if (root / "mvnw").is_file() else "mvn spring-boot:run"
    for gradle in ("build.gradle", "build.gradle.kts"):
        if has(gradle, "org.springframework.boot"):
            return "./gradlew bootRun" if (root / "gradlew").is_file() else "gradle bootRun"
    return None


def detect_command(root: Path) -> str | None:
    """Start-Befehl des Projekts, wenn es keinen eingetragenen gibt: Laravel (artisan), Node-Projekte mit dev- bzw. start-Skript (Vite, Next, Nuxt, Angular)."""
    root = Path(root)
    if (root / "artisan").is_file() and (root / "composer.json").is_file():
        try:
            octane = "laravel/octane" in (root / "composer.json").read_text(encoding="utf-8")
        except OSError:
            octane = False
        return "php artisan octane:start" if octane else "php artisan serve"      # Octane: RoadRunner, FrankenPHP oder Swoole je nach config/octane.php
    spring = _spring_command(root)
    if spring:
        return spring
    if (root / ".rr.yaml").is_file():
        return "./rr serve" if (root / "rr").is_file() else "rr serve"
    if (root / "Caddyfile").is_file():
        return "frankenphp run"
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
