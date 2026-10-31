"""Web-Vorschau: eingebetteter Browser (QtWebEngine) mit Adressleiste, Geräte-Größen, Zoom und Elementauswahl/-bearbeitung."""
import json
import weakref

from PySide6.QtCore import QCoreApplication, QEvent, QSettings, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QToolButton, QVBoxLayout, QWidget)

from .page import PreviewPage

_PROFILES: list = []
_PANELS: "weakref.WeakSet" = weakref.WeakSet()


def dispose_profiles():
    """Profile erst nach allen Seiten freigeben (beim Beenden der Anwendung aufrufen)."""
    from shiboken6 import delete, isValid
    for panel in list(_PANELS):                       # noch lebende Vorschau-Fenster zuerst abbauen (Seite vor Profil)
        if isValid(panel):
            panel.shutdown()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    while _PROFILES:
        p = _PROFILES.pop()
        if isValid(p):
            delete(p)


# Name -> (Breite, Höhe, mobiler User-Agent)
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"
DEVICES = {"Frei (füllt das Fenster)": (0, 0, None), "Laptop 1280×800": (1280, 800, None), "Tablet 768×1024": (768, 1024, None),
           "Handy 390×844": (390, 844, MOBILE_UA), "Handy klein 360×640": (360, 640, MOBILE_UA)}


class PreviewPanel(QWidget):
    picked = Signal(dict)
    changed = Signal(dict)
    textChanged = Signal(dict)
    consoleMessage = Signal(str, str, int, str)
    pageLoaded = Signal(bool, str)
    ready = Signal(dict)
    saveRequested = Signal()
    undoRequested = Signal()
    insertDropped = Signal(dict)         # Baustein auf die Seite gezogen: {block, where, info}
    outlineChanged = Signal(list)
    discardRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # eigenes Profil (User-Agent der Geräte-Vorschau ändert nichts anderswo); gehört der Anwendung, damit es erst nach der Seite zerstört wird
        self.profile = QWebEngineProfile(QCoreApplication.instance())
        _PROFILES.append(self.profile)
        _PANELS.add(self)
        self.page = PreviewPage(self.profile, self)
        self.view = QWebEngineView()
        self.view.setPage(self.page)
        self.mode = "off"
        self._selected_path = ""
        self.landscape = False
        # Leiste
        self.back = self._tool("◀", "Zurück", self.view.back); self.fwd = self._tool("▶", "Vor", self.view.forward)
        self.reload_btn = self._tool("⟳", "Neu laden (Strg+R)", self.reload)
        self.url = QLineEdit(); self.url.setPlaceholderText("http://localhost:5173 – oder Dev-Server starten (F5)")
        self.url.returnPressed.connect(lambda: self.set_url(self.url.text()))
        self.device = QComboBox(); self.device.addItems(list(DEVICES))
        self.device.currentIndexChanged.connect(self._apply_device)
        self.rotate = self._tool("⟲", "Drehen", self._rotate)
        self.zoom = QComboBox(); self.zoom.addItems(["50 %", "75 %", "100 %", "125 %", "150 %"]); self.zoom.setCurrentText("100 %")
        self.zoom.currentIndexChanged.connect(self._apply_device)
        self.btn_pick = self._tool("⌖ Auswählen", "Elemente anklicken (Esc beendet)", lambda: self.set_mode("off" if self.mode == "pick" else "pick"), checkable=True)
        self.btn_edit = self._tool("✥ Bearbeiten", "Elemente verschieben, skalieren, Text per Doppelklick ändern", lambda: self.set_mode("off" if self.mode == "edit" else "edit"), checkable=True)
        bar = QHBoxLayout(); bar.setContentsMargins(4, 4, 4, 4); bar.setSpacing(4)
        for w in (self.back, self.fwd, self.reload_btn):
            bar.addWidget(w)
        bar.addWidget(self.url, 1)
        for w in (self.device, self.rotate, self.zoom, self.btn_pick, self.btn_edit):
            bar.addWidget(w)
        self.status = QLabel(); self.status.setObjectName("sub")
        self.scroll = QScrollArea(); self.scroll.setWidget(self.view); self.scroll.setWidgetResizable(True); self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.btn_save = QPushButton("💾 In Quellcode speichern"); self.btn_save.setToolTip("Alle Änderungen aus „Bearbeiten“ in die Projektdateien schreiben (Vorschau der Änderung vorher)")
        self.btn_save.clicked.connect(lambda: self.saveRequested.emit())
        self.btn_discard = QPushButton("Verwerfen"); self.btn_discard.setToolTip("Änderungen in der Vorschau zurücknehmen")
        self.btn_discard.clicked.connect(lambda: self.discardRequested.emit())
        self.btn_undo = QPushButton("↶ Rückgängig"); self.btn_undo.setToolTip("Letzte Änderung am Quellcode zurücknehmen")
        self.btn_undo.clicked.connect(lambda: self.undoRequested.emit()); self.btn_undo.setVisible(False)
        foot = QHBoxLayout(); foot.setContentsMargins(4, 2, 4, 2); foot.setSpacing(4)
        foot.addWidget(self.status, 1); foot.addWidget(self.btn_undo); foot.addWidget(self.btn_discard); foot.addWidget(self.btn_save)
        self.set_pending(0)
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(0)
        lay.addLayout(bar); lay.addWidget(self.scroll, 1); lay.addLayout(foot)
        # Signale
        self.page.toolMessage.connect(self._tool_message)
        self.page.consoleMessage.connect(self.consoleMessage)
        self.view.loadFinished.connect(self._loaded)
        self.view.urlChanged.connect(self._url_changed)
        self._reload_timer = QTimer(self, singleShot=True, interval=250)
        self._reload_timer.timeout.connect(self.reload)

    def set_pending(self, n: int):
        """Anzahl der noch nicht in den Quellcode übernommenen Änderungen; die Knöpfe erscheinen nur, wenn es welche gibt."""
        self.btn_save.setVisible(n > 0); self.btn_discard.setVisible(n > 0)
        self.btn_save.setText(f"💾 In Quellcode speichern ({n})" if n else "💾 In Quellcode speichern")

    def set_undo(self, available: bool):
        self.btn_undo.setVisible(available)

    def refresh_outline(self):
        """Seitenstruktur (Baum der Elemente) aus der Seite holen."""
        def done(raw):
            try:
                self.outlineChanged.emit(json.loads(raw) if raw else [])
            except ValueError:
                pass
        self.eval("JSON.stringify(window.__vds ? window.__vds.outline() : [])", done)           # Arrays reicht QtWebEngine nicht zuverlässig durch

    @staticmethod
    def _tool(text, tip, slot, checkable=False):
        b = QToolButton(); b.setText(text); b.setToolTip(tip); b.setCheckable(checkable); b.clicked.connect(lambda _=False: slot())
        return b

    # --- Seite ---------------------------------------------------------------------------------------
    def set_url(self, url: str):
        url = url.strip()
        if not url:
            return
        if "://" not in url:
            url = "http://" + url
        self.view.load(QUrl(url))

    def current_url(self) -> str:
        return self.view.url().toString()

    def reload(self):
        """Neu laden ohne Browser-Cache (Dev-Werkzeug: geänderte CSS-Dateien müssen sofort wirken)."""
        self.page.triggerAction(QWebEnginePage.ReloadAndBypassCache)

    def schedule_reload(self, force=False, mode="immer"):
        """Nach dem Speichern: kurz warten und neu laden. mode: nie | immer | ohne-hmr (Seiten mit Vite/Next/Nuxt aktualisieren sich selbst)."""
        if mode == "nie" or self.view.url().isEmpty() or not self.view.url().isValid():
            return
        if force or mode == "immer":
            return self._reload_timer.start()
        self.eval("!!document.querySelector('script[src*=\"@vite/client\"], script[src*=\"/_next/\"], script[src*=\"/_nuxt/\"], script[src*=\"webpack-hmr\"]')",
                  lambda hmr: None if hmr else self._reload_timer.start())

    def _url_changed(self, u):
        self.url.setText(u.toString())

    def _loaded(self, ok: bool):
        self.status.setText(f"{'Geladen' if ok else 'Konnte nicht geladen werden'}: {self.view.url().toString()}")
        self.pageLoaded.emit(ok, self.view.url().toString())
        if ok:
            self.refresh_outline()
            self.set_mode(self.mode, force=True)
            if self._selected_path:
                self.eval(f"window.__vds && window.__vds.restore({json.dumps(self._selected_path)})")

    def eval(self, js: str, cb=None):
        if cb:
            self.page.runJavaScript(js, cb)
        else:
            self.page.runJavaScript(js)

    # --- Modus --------------------------------------------------------------------------------------------
    def set_mode(self, mode: str, force=False):
        if mode == self.mode and not force:
            return
        self.mode = mode
        self.btn_pick.setChecked(mode == "pick"); self.btn_edit.setChecked(mode == "edit")
        self.eval(f"window.__vds && window.__vds.setMode({json.dumps(mode)})")
        self.status.setText({"pick": "Auswählen: Element anklicken", "edit": "Bearbeiten: ziehen = verschieben, Pfeiltasten = fein, Griffe = Größe, Doppelklick = Text", "off": ""}[mode])

    def _tool_message(self, kind: str, data: dict):
        if kind == "pick":
            self._selected_path = data.get("path", "")
            self.picked.emit(data)
        elif kind == "changed":
            self.changed.emit(data)
        elif kind == "text":
            self.textChanged.emit(data)
        elif kind == "ready":
            self.ready.emit(data)
        elif kind == "insert":
            self.insertDropped.emit(data)
        elif kind == "hover":
            self.status.setText(data.get("tag", ""))

    # --- Gerät/Zoom -----------------------------------------------------------------------------------------------
    def _rotate(self):
        self.landscape = not self.landscape
        self._apply_device()

    def _apply_device(self, *_):
        w, h, ua = DEVICES[self.device.currentText()]
        if self.landscape:
            w, h = h, w
        self.profile.setHttpUserAgent(ua or QWebEngineProfile.defaultProfile().httpUserAgent())
        self.view.setZoomFactor(int(self.zoom.currentText().split()[0]) / 100)
        self.scroll.setWidgetResizable(w == 0)
        self.view.setFixedSize(QSize(w, h)) if w else (self.view.setMinimumSize(0, 0), self.view.setMaximumSize(16777215, 16777215))
        self.rotate.setEnabled(w > 0)
        if self.view.url().isValid() and not self.view.url().isEmpty():
            self.view.reload()                                  # neuer User-Agent gilt erst nach dem Neuladen

    def shutdown(self):
        """Seite und Ansicht vor dem Profil abbauen (QtWebEngine stürzt sonst beim Beenden ab, wenn das Profil zuerst stirbt)."""
        if getattr(self, "_down", False):
            return
        self._down = True
        self._reload_timer.stop()
        self.view.stop()
        self.view.setParent(None)
        self.page.deleteLater(); self.view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape and self.mode != "off":
            return self.set_mode("off")
        super().keyPressEvent(e)
