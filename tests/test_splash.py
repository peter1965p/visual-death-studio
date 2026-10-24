"""Startbild: Zeichnen, Fortschritt aus dem Hauptfenster, Option."""
from PySide6.QtGui import QColor

from vds import options
from vds.app import MainWindow
from vds.splash import H, W, SplashScreen


def test_splash_paints_title_skull_and_clamped_progress(qapp):
    s = SplashScreen()
    s.step(150, "Test")
    assert s.value == 100.0
    s.step(-5, "Test"); assert s.value == 0.0
    s.step(40, "Lade …")
    img = s.grab().toImage()
    assert (img.width(), img.height()) == (W, H)
    # Totenkopf (Cyan-/Violett-Leuchten links), Fortschrittsbalken (Cyan am Anfang), Hintergrund dunkel
    assert any(QColor(img.pixel(x, 150)).blue() > 200 for x in range(60, 240))
    assert QColor(img.pixel(60, H - 72)).green() > 150 and QColor(img.pixel(W - 60, H - 72)).lightness() < 60
    assert QColor(img.pixel(20, 20)).lightness() < 40


def test_main_window_reports_monotonic_startup_progress(qapp, tmp_path):
    steps = []
    w = MainWindow(progress=lambda p, t: steps.append((p, t)))
    try:
        pct = [p for p, _ in steps]
        assert pct == sorted(pct) and pct[0] <= 5 and pct[-1] >= 90 and len(steps) >= 8
        assert all(t for _, t in steps) and any("Menüs" in t for _, t in steps)
    finally:
        w.docs.close_all(); w.close()


def test_splash_option_defaults_on_and_can_be_switched_off(qapp):
    options.reset()
    assert options.get("ui/splash") is True
    options.set("ui/splash", False); assert options.get("ui/splash") is False
    options.reset()
