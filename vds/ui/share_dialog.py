"""Live-Share-Dialog: Sitzung hosten (Code an Gäste weitergeben) oder einer Sitzung beitreten."""
from pathlib import Path

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from ..share import session as S


class ShareDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("Live Share")
        self.setMinimumWidth(520)
        tabs = QTabWidget()
        # --- Host
        h = QWidget(); hl = QVBoxLayout(h)
        self.read_only = QCheckBox("Gäste dürfen nur lesen")
        self.addr = QComboBox(); self.addr.addItems(S.local_addresses())
        self.code = QLineEdit(); self.code.setReadOnly(True)
        self.peers = QListWidget(); self.peers.setMaximumHeight(90)
        self.b_host = QPushButton("Sitzung starten"); self.b_host.clicked.connect(self.toggle_host)
        self.b_copy = QPushButton("Code kopieren"); self.b_copy.clicked.connect(lambda: self.code.selectAll() or self.code.copy())
        row = QHBoxLayout(); row.addWidget(self.code, 1); row.addWidget(self.b_copy)
        self.hint = QLabel("Die Verbindung ist unverschlüsselt: nur im lokalen Netz oder über ein VPN verwenden und den Code nur an Personen geben, denen du vertraust.")
        self.hint.setWordWrap(True); self.hint.setObjectName("sub")
        for w in (QLabel("Adresse, unter der Gäste dich erreichen:"), self.addr, self.read_only, self.b_host, row, QLabel("Verbundene Gäste:"), self.peers, self.hint):
            hl.addLayout(w) if isinstance(w, QHBoxLayout) else hl.addWidget(w)
        # --- Gast
        g = QWidget(); gl = QVBoxLayout(g)
        self.join_code = QLineEdit(); self.join_code.setPlaceholderText("Code vom Host, z. B. 192.168.1.5:41234/AbCdEf …")
        self.name = QLineEdit("Gast")
        self.folder = QLineEdit(str(Path.home() / "LiveShare"))
        b = QPushButton("…"); b.setFixedWidth(32); b.clicked.connect(self._browse)
        fr = QHBoxLayout(); fr.addWidget(self.folder, 1); fr.addWidget(b)
        self.b_join = QPushButton("Beitreten"); self.b_join.clicked.connect(self.join)
        self.state = QLabel(""); self.state.setWordWrap(True)
        for w in (QLabel("Code:"), self.join_code, QLabel("Dein Name:"), self.name, QLabel("Lokaler Ordner für die Kopie des Projekts:"), fr, self.b_join, self.state):
            gl.addLayout(w) if isinstance(w, QHBoxLayout) else gl.addWidget(w)
        tabs.addTab(h, "Hosten"); tabs.addTab(g, "Beitreten")
        QVBoxLayout(self).addWidget(tabs)
        self.win.share.peersChanged.connect(self._peers)
        self.win.share.status.connect(self.state.setText)

    def _browse(self):
        p = QFileDialog.getExistingDirectory(self, "Ordner", self.folder.text())
        if p:
            self.folder.setText(p)

    def _peers(self, names):
        self.peers.clear(); self.peers.addItems(names)

    def toggle_host(self):
        if self.win.share.active:
            self.win.share.stop()
            self.b_host.setText("Sitzung starten"); self.code.clear(); self.peers.clear()
            return
        try:
            self.win.share_host(self.read_only.isChecked())
        except OSError as e:
            self.hint.setText(f"Sitzung konnte nicht starten: {e}")
            return
        self.code.setText(self.win.share.join_code(self.addr.currentText()))
        self.b_host.setText("Sitzung beenden")

    def join(self):
        try:
            self.win.share_join(self.join_code.text(), self.name.text().strip() or "Gast", Path(self.folder.text()))
            self.state.setText("Verbinde …")
        except ValueError as e:
            self.state.setText(str(e))
