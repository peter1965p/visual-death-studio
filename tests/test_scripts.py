"""install.sh / uninstall.sh: Syntax und Entfernen im Sandbox-HOME (die Installation selbst braucht Netzwerk und wird hier nicht ausgeführt)."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sh(script, home, *args):
    env = {k: v for k, v in os.environ.items() if k not in ("PREFIX", "XDG_DATA_HOME", "XDG_CONFIG_HOME")}
    env["HOME"] = str(home)
    return subprocess.run(["bash", str(ROOT / script), *args], capture_output=True, text=True, env=env, timeout=30)


def test_scripts_are_valid_bash_and_executable():
    for s in ("install.sh", "uninstall.sh"):
        assert os.access(ROOT / s, os.X_OK)
        assert subprocess.run(["bash", "-n", str(ROOT / s)]).returncode == 0
        assert "Aufruf" in subprocess.run(["bash", str(ROOT / s), "--help"], capture_output=True, text=True).stdout


def test_install_rejects_unknown_option():
    r = subprocess.run(["bash", str(ROOT / "install.sh"), "--quatsch"], capture_output=True, text=True)
    assert r.returncode == 2 and "Unbekannte Option" in r.stderr


def fake_install(home, venv, marker):
    for p in (home / ".local/bin/visual-death-studio", home / ".local/share/applications/visual-death-studio.desktop",
              home / ".local/share/icons/hicolor/scalable/apps/visual-death-studio.svg", home / ".config/VisualDeathStudio/x.conf",
              home / ".local/share/visual-death-studio/tools/bin/dlv", home / "Projekte/mein/main.py", venv / "bin/python"):
        p.parent.mkdir(parents=True, exist_ok=True); p.write_text("x")
    if marker:
        (venv / ".vds-install").write_text("x")


def test_uninstall_removes_only_what_install_created(tmp_path):
    home, venv = tmp_path / "home", tmp_path / "venv"
    fake_install(home, venv, marker=True)
    assert "Testlauf" in sh("uninstall.sh", home, "--dry-run", "--venv", str(venv)).stdout
    assert (home / ".local/bin/visual-death-studio").exists()                       # Testlauf löscht nichts
    r = sh("uninstall.sh", home, "-y", "--venv", str(venv))
    assert r.returncode == 0, r.stderr
    assert not (home / ".local/bin/visual-death-studio").exists() and not (home / ".local/share/applications/visual-death-studio.desktop").exists()
    assert not venv.exists()
    assert (home / ".config/VisualDeathStudio/x.conf").exists() and (home / "Projekte/mein/main.py").exists()   # Einstellungen, Projekte bleiben
    sh("uninstall.sh", home, "-y", "--purge", "--venv", str(venv))
    assert not (home / ".config/VisualDeathStudio").exists() and not (home / ".local/share/visual-death-studio").exists()
    assert (home / "Projekte/mein/main.py").exists()
    assert "Nichts zu entfernen" in sh("uninstall.sh", home, "-y", "--venv", str(venv)).stdout


def test_uninstall_keeps_foreign_venv(tmp_path):
    home, venv = tmp_path / "home", tmp_path / "meinvenv"
    fake_install(home, venv, marker=False)                                           # ohne Marker: nicht von install.sh
    r = sh("uninstall.sh", home, "-y", "--venv", str(venv))
    assert (venv / "bin/python").exists() and "bleibt erhalten" in r.stdout
