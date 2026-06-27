"""Store HQ tile launcher — a full-screen overlay (Ctrl+Q / Menu key) showing
every store screen as a big tile. Mirrors the main app's NavLauncher look, but
a single flat grid (the store has few screens — no menu-tree grouping needed)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QFrame, QSizePolicy,
)

from ui.theme import THEME

_COLS = 3


class StoreLauncher(QWidget):
    def __init__(self, window):
        parent = window.centralWidget() or window
        super().__init__(parent)
        self._window = window
        self.setObjectName("store_launcher")
        self.hide()
        self.setStyleSheet("#store_launcher { background: rgba(5, 8, 16, 0.62); }")

        scrim = QVBoxLayout(self)
        scrim.setContentsMargins(0, 0, 0, 0)
        scrim.addStretch()
        center = QHBoxLayout(); center.addStretch()

        self._panel = QFrame()
        self._panel.setObjectName("store_launcher_panel")
        self._panel.setStyleSheet(f"""
            #store_launcher_panel {{
                background: {THEME.get('bg_sidebar', THEME.get('bg_panel', '#10182a'))};
                border: 1px solid {THEME['border']};
                border-radius: 16px;
            }}""")
        self._panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        pv = QVBoxLayout(self._panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        header = QFrame()
        header.setStyleSheet(f"border-bottom: 1px solid {THEME['border']};")
        hl = QHBoxLayout(header); hl.setContentsMargins(24, 16, 18, 16)
        title = QLabel("Store HQ — Jump to…")
        title.setStyleSheet(f"color:{THEME['text_primary']}; font-size:17px; font-weight:bold;"
                            " background:transparent; border:none;")
        hl.addWidget(title); hl.addStretch()
        hint = QLabel("click a tile  ·  Esc to close")
        hint.setStyleSheet(f"color:{THEME.get('text_dim', THEME['text_secondary'])}; font-size:12px;"
                           " background:transparent; border:none;")
        hl.addWidget(hint)
        pv.addWidget(header)

        self._grid_host = QWidget(); self._grid_host.setStyleSheet("background:transparent;")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(24, 20, 24, 24)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(14)
        pv.addWidget(self._grid_host, 1)

        center.addWidget(self._panel); center.addStretch()
        scrim.addLayout(center); scrim.addStretch()

    def _tile(self, idx, label, icon, enabled=True):
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor if enabled else Qt.CursorShape.ArrowCursor)
        btn.setMinimumHeight(96)
        btn.setEnabled(enabled)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        border = THEME['accent'] if enabled else THEME['border']
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['bg_hover']};
                border: 1px solid {THEME['border']};
                border-radius: 14px;
            }}
            QPushButton:hover {{ border-color: {border}; }}
            QPushButton:disabled {{ color: {THEME['text_secondary']}; }}
        """)
        col = QVBoxLayout(btn); col.setContentsMargins(14, 12, 14, 12); col.setSpacing(4)
        ic = QLabel(icon); ic.setStyleSheet("font-size:30px; background:transparent; border:none;")
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        col.addWidget(ic)
        nm = QLabel(label if enabled else f"{label}")
        nm.setAlignment(Qt.AlignmentFlag.AlignCenter)
        clr = THEME['text_primary'] if enabled else THEME['text_secondary']
        nm.setStyleSheet(f"font-size:13px; font-weight:600; color:{clr}; background:transparent; border:none;")
        col.addWidget(nm)
        if enabled:
            btn.clicked.connect(lambda _=False, i=idx: (self.close_launcher(), self._window._select(i)))
        return btn

    def _populate(self):
        while self._grid.count():
            w = self._grid.takeAt(0).widget()
            if w:
                w.setParent(None)
        tiles = []
        for i, (label, icon, _page) in enumerate(self._window._pages):
            tiles.append(self._tile(i, label, icon, enabled=True))
        # roadmap tiles (not yet built) — shows what's coming, so it doesn't feel thin
        for label, icon in self._window.COMING_SOON:
            tiles.append(self._tile(-1, f"{label}  (soon)", icon, enabled=False))
        for n, t in enumerate(tiles):
            self._grid.addWidget(t, n // _COLS, n % _COLS)

    def open_launcher(self):
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
            self._panel.setFixedSize(int(parent.width() * 0.7), int(parent.height() * 0.72))
        self._populate()
        self.show(); self.raise_(); self.setFocus()

    def close_launcher(self):
        self.hide()

    def toggle(self):
        self.close_launcher() if self.isVisible() else self.open_launcher()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key.Key_Escape:
            self.close_launcher(); return
        super().keyPressEvent(ev)

    def mousePressEvent(self, ev):
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.BackButton):
            self.close_launcher(); return
        if not self._panel.geometry().contains(ev.pos()):
            self.close_launcher(); return
        super().mousePressEvent(ev)
