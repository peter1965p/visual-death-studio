"""Paket-Manager (wie der NuGet-Paket-Manager in Visual Studio): Durchsuchen · Installiert · Updates für NuGet, pip, npm, cargo."""
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, QRunnable, QThreadPool, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
                               QPlainTextEdit, QPushButton, QSplitter, QTabBar, QVBoxLayout, QWidget)

from ..packages.sources import SOURCES, Pkg, is_pre, vkey


class _Signals(QObject):
    done = Signal(object, object)       # Ergebnis, Fehler


class _Job(QRunnable):
    def __init__(self, fn):
        super().__init__()
        self.fn, self.signals = fn, _Signals()

    def run(self):
        try:
            res, err = self.fn(), None
        except Exception as e:  # Netzwerk-/Parsefehler werden dem Nutzer angezeigt
            res, err = None, e
        try:
            self.signals.done.emit(res, err)
        except RuntimeError:   # Panel wurde inzwischen geschlossen
            pass


class PackagePanel(QWidget):
    filesChanged = Signal()   # Projektdateien (csproj, package.json, requirements.txt …) wurden verändert

    def __init__(self, parent=None):
        super().__init__(parent)
        self.root = Path(".")
        self.pkgs: list[Pkg] = []
        self._jobs, self.proc, self._gen = set(), None, 0
        self.src = SOURCES[0]
        # Kopfzeile
        self.eco = QComboBox(); self.eco.addItems([s.name for s in SOURCES])
        self.target = QComboBox(); self.target.setMinimumWidth(200)
        self.search = QLineEdit(placeholderText="Suchen …  (Enter)")
        self.pre = QCheckBox("Vorabversionen")
        self.tabs = QTabBar(); [self.tabs.addTab(t) for t in ("Durchsuchen", "Installiert", "Updates")]
        top = QHBoxLayout(); top.setContentsMargins(6, 4, 6, 0)
        for w in (QLabel("Quelle:"), self.eco, QLabel("Projekt:"), self.target):
            top.addWidget(w)
        top.addSpacing(10); top.addWidget(self.search, 1); top.addWidget(self.pre)
        # Liste + Details
        self.list = QListWidget(); self.list.setUniformItemSizes(False)
        self.title, self.meta, self.desc = QLabel(), QLabel(), QLabel()
        self.title.setStyleSheet("font-size:15px;font-weight:600"); self.meta.setObjectName("sub")
        self.desc.setWordWrap(True); self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.link = QLabel(); self.link.setStyleSheet("color:#5ee7ff"); self.link.setCursor(Qt.PointingHandCursor)
        self.version = QComboBox()
        self.b_install, self.b_remove = QPushButton("Installieren"), QPushButton("Deinstallieren")
        self.b_install.setObjectName("primary")
        detail = QWidget(); dl = QVBoxLayout(detail); dl.setContentsMargins(10, 8, 10, 8)
        vrow = QHBoxLayout(); vrow.addWidget(QLabel("Version:")); vrow.addWidget(self.version, 1)
        brow = QHBoxLayout(); brow.addWidget(self.b_install); brow.addWidget(self.b_remove); brow.addStretch()
        for w in (self.title, self.meta, self.desc): dl.addWidget(w)
        dl.addWidget(self.link); dl.addStretch(); dl.addLayout(vrow); dl.addLayout(brow)
        split = QSplitter(); split.addWidget(self.list); split.addWidget(detail); split.setSizes([520, 380])
        self.log = QPlainTextEdit(readOnly=True); self.log.setMaximumHeight(90)
        self.status = QLabel(); self.status.setObjectName("sub")
        lay = QVBoxLayout(self); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(4)
        lay.addLayout(top); lay.addWidget(self.tabs); lay.addWidget(split, 1); lay.addWidget(self.status); lay.addWidget(self.log)
        # Verdrahtung
        self.eco.currentIndexChanged.connect(self._eco_changed)
        self.target.currentIndexChanged.connect(lambda _i: self._reload())
        self.tabs.currentChanged.connect(lambda _i: self._reload())
        self.pre.toggled.connect(lambda _b: self._reload())
        self.search.returnPressed.connect(self._reload)
        self.list.currentItemChanged.connect(lambda cur, _p: self._show(cur.data(Qt.UserRole) if cur else None))
        self.b_install.clicked.connect(self._install); self.b_remove.clicked.connect(self._remove)
        self.link.mousePressEvent = lambda e: self.link.text() and QDesktopServices.openUrl(QUrl(self.link.toolTip()))
        self._show(None)

    # --- Projekt/Quelle ----------------------------------------------------------------------------
    def set_root(self, root: Path):
        self.root = Path(root)
        found = next((i for i, s in enumerate(SOURCES) if s.targets(self.root)), 0)
        self.eco.blockSignals(True); self.eco.setCurrentIndex(found); self.eco.blockSignals(False)
        self._eco_changed(found)

    def _eco_changed(self, i):
        self.src = SOURCES[i]
        self.target.blockSignals(True)
        self.target.clear()
        for t in self.src.targets(self.root):
            self.target.addItem(t.label, t)
        self.target.blockSignals(False)
        self.search.setPlaceholderText("Exakten Paketnamen eingeben …  (Enter)" if not self.src.supports_search else "Suchen …  (Enter)")
        self._reload()

    def _cur_target(self):
        return self.target.currentData()

    # --- Laden ---------------------------------------------------------------------------------------
    def _async(self, fn, cb):
        job = _Job(fn)
        self._jobs.add(job)
        gen = self._gen

        def done(res, err, job=job):
            self._jobs.discard(job)
            if gen == self._gen:
                cb(res, err)
        job.signals.done.connect(done)
        QThreadPool.globalInstance().start(job)

    def _reload(self):
        self._gen += 1
        tab = self.tabs.currentIndex()
        t = self._cur_target()
        installed = {p.id.lower(): p for p in (self.src.installed(t) if t else [])}
        self.installed = installed
        if tab == 0:
            q = self.search.text().strip()
            if not q:
                self._fill([], "Gib einen Suchbegriff ein." if self.src.supports_search else "Gib den exakten Paketnamen ein (PyPI hat keine Volltextsuche).")
                return
            self.status.setText("Suche …")
            self._async(lambda: self.src.search(q, self.pre.isChecked()), lambda r, e: self._searched(r, e))
        elif tab == 1:
            self._fill(list(installed.values()), "" if installed else "Keine Pakete installiert." if t else f"Kein {self.src.name}-Projekt im Ordner.")
        else:
            self._check_updates(list(installed.values()))

    def _searched(self, res, err):
        if err:
            return self._fill([], f"Suche fehlgeschlagen: {err}")
        self._fill(res, "" if res else "Keine Treffer.")

    def _check_updates(self, items):
        if not items:
            return self._fill([], "Keine Pakete installiert.")
        self.status.setText(f"Prüfe {len(items)} Paket(e) auf Updates …")
        items = items[:60]
        pre, src, out, left = self.pre.isChecked(), self.src, [], [len(items)]
        for p in items:
            def work(p=p):
                return p, src.latest(p.id, pre)

            def got(res, err):
                left[0] -= 1
                if res and res[1]:
                    pkg, latest = res
                    if pkg.installed and vkey(latest) > vkey(pkg.installed):
                        pkg.latest = latest
                        out.append(pkg)
                if left[0] <= 0:
                    self._fill(sorted(out, key=lambda x: x.id.lower()), "" if out else "Alle Pakete sind aktuell.")
            self._async(work, got)

    def _fill(self, pkgs, msg=""):
        self.pkgs = pkgs
        self.list.clear()
        for p in pkgs:
            inst = self.installed.get(p.id.lower()) if hasattr(self, "installed") else None
            ver = f"{p.installed} → {p.latest}" if p.latest else p.version
            it = QListWidgetItem(f"{p.id}   {ver}" + (f"   ✓ installiert {inst.installed}" if inst and not p.latest and self.tabs.currentIndex() == 0 else "")
                                 + (f"\n{p.description[:110]}" if p.description else ""))
            it.setData(Qt.UserRole, p)
            if inst:
                it.setForeground(QColor("#3dffa1"))
            self.list.addItem(it)
        self.status.setText(msg or f"{len(pkgs)} Paket(e)")
        if pkgs:
            self.list.setCurrentRow(0)
        else:
            self._show(None)

    # --- Details ------------------------------------------------------------------------------------------
    def _show(self, p: Pkg | None):
        self.sel = p
        self.version.clear()
        for b in (self.b_install, self.b_remove):
            b.setEnabled(False)
        if not p:
            self.title.setText(""); self.meta.setText(""); self.desc.setText("Wähle ein Paket aus der Liste."); self.link.setText("")
            return
        self.title.setText(p.id)
        bits = [x for x in (p.authors, f"{p.downloads:,} Downloads".replace(",", ".") if p.downloads else "") if x]
        self.meta.setText("  ·  ".join(bits))
        self.desc.setText(p.description or "(keine Beschreibung)")
        self.link.setText("Projektseite öffnen ↗" if p.url else ""); self.link.setToolTip(p.url)
        if p.versions:
            self._fill_versions(p, p.versions)
        else:
            self.version.addItem("lade Versionen …")
            self._async(lambda: self.src.versions(p.id), lambda r, e, p=p: self._got_versions(p, r or []))
        self._buttons()

    def _got_versions(self, p, vs):
        p.versions = vs
        if self.sel is p:
            self._fill_versions(p, vs)

    def _fill_versions(self, p, vs):
        self.version.clear()
        shown = [v for v in vs if self.pre.isChecked() or not is_pre(v)] or vs
        self.version.addItems(shown[:150])
        inst = self.installed.get(p.id.lower()) if hasattr(self, "installed") else None
        want = (p.latest or p.version) if p.latest or not inst else inst.installed
        i = self.version.findText(want)
        self.version.setCurrentIndex(max(0, i))
        self._buttons()

    def _buttons(self):
        p = self.sel
        t = self._cur_target()
        busy = self.proc is not None
        inst = self.installed.get(p.id.lower()) if p and hasattr(self, "installed") else None
        self.b_install.setText("Aktualisieren" if inst else "Installieren")
        self.b_install.setEnabled(bool(p and t and not busy and self.version.count()))
        self.b_remove.setEnabled(bool(inst and t and not busy))

    # --- Aktionen --------------------------------------------------------------------------------------------
    def _install(self):
        p, t = self.sel, self._cur_target()
        if not p or not t:
            return
        ver = self.version.currentText() if self.version.count() and "lade" not in self.version.currentText() else ""
        try:
            steps = [self.src.install_cmd(t, p.id, ver)]
        except RuntimeError as e:
            if self.src.ecosystem != "pypi" or QMessageBox.question(self, "Virtuelle Umgebung", f"{e}\n\nJetzt eine .venv im Projekt anlegen?") != QMessageBox.Yes:
                return
            # Der Installationsbefehl braucht die .venv und wird deshalb erst nach deren Anlegen berechnet
            steps = [([shutil.which("python3") or "python3", "-m", "venv", ".venv"], t.path), lambda: self.src.install_cmd(t, p.id, ver)]
        self._chain(steps, lambda ok, t=t, p=p, ver=ver: self._finish("install", t, p.id, ver, ok))

    def _remove(self):
        p, t = self.sel, self._cur_target()
        if not p or not t:
            return
        if QMessageBox.question(self, "Deinstallieren", f"'{p.id}' aus dem Projekt entfernen?") != QMessageBox.Yes:
            return
        try:
            step = self.src.remove_cmd(t, p.id)
        except RuntimeError as e:
            return QMessageBox.warning(self, "Paket-Manager", str(e))
        self._chain([step], lambda ok, t=t, p=p: self._finish("remove", t, p.id, "", ok))

    def install_module(self, pip_name: str, on_done):
        """Installiert ein PyPI-Paket in die .venv des Projekts (legt sie bei Bedarf an) – z. B. nach einem ModuleNotFoundError."""
        from ..packages.sources import BY_ECO, Target
        pypi = BY_ECO["pypi"]
        self.eco.setCurrentIndex(SOURCES.index(pypi))
        t = self._cur_target() or Target(self.root, ".  (Python)")
        steps = []
        if not pypi.python(t):
            steps.append(([shutil.which("python3") or "python3", "-m", "venv", ".venv"], t.path))
        steps.append(lambda: pypi.install_cmd(t, pip_name, ""))
        self.search.setText(pip_name)
        self._chain(steps, lambda ok: (self._finish("install", t, pip_name, "", ok), on_done(ok)))

    def _chain(self, steps, on_done):
        if self.proc:
            return
        if not steps:
            return
        cmd, cwd = steps[0]() if callable(steps[0]) else steps[0]
        if not shutil.which(cmd[0]) and not Path(cmd[0]).exists():
            self.log.appendPlainText(f"'{cmd[0]}' ist nicht installiert.")
            return on_done(False)
        self.log.appendPlainText("> " + " ".join(cmd))
        self.status.setText("Läuft …")
        p = QProcess(self); p.setWorkingDirectory(str(cwd)); p.setProcessChannelMode(QProcess.MergedChannels)
        p.readyReadStandardOutput.connect(lambda: self.log.appendPlainText(bytes(p.readAllStandardOutput()).decode("utf-8", "replace").rstrip()))
        p.finished.connect(lambda code, _s: self._step_done(code, steps[1:], on_done))
        p.errorOccurred.connect(lambda e: e == QProcess.FailedToStart and self._step_done(127, [], on_done))
        self.proc = p
        self._buttons()
        p.start(cmd[0], cmd[1:])

    def _step_done(self, code, rest, on_done):
        self.proc = None
        if code == 0 and rest:
            return self._chain(rest, on_done)
        on_done(code == 0)

    def _finish(self, op, t, pkg_id, ver, ok):
        if ok:
            try:
                self.src.after(t, op, pkg_id, ver)
            except OSError as e:
                self.log.appendPlainText(f"Hinweis: {e}")
            self.status.setText(f"{pkg_id}: {'installiert' if op == 'install' else 'entfernt'}.")
            self.filesChanged.emit()
        else:
            self.status.setText("Fehlgeschlagen – siehe Protokoll.")
        self._reload_installed_only()
        self._buttons()

    def _reload_installed_only(self):
        t = self._cur_target()
        self.installed = {p.id.lower(): p for p in (self.src.installed(t) if t else [])}
        if self.tabs.currentIndex() == 1:
            self._fill(list(self.installed.values()), "" if self.installed else "Keine Pakete installiert.")
        else:
            for i in range(self.list.count()):
                p = self.list.item(i).data(Qt.UserRole)
                self.list.item(i).setForeground(QColor("#3dffa1") if p.id.lower() in self.installed else QColor("#dbe6ff"))
