"""
Tile launcher — navigation Mode B (shared base UI).

A full-screen overlay that opens on a key press (or the ☰ button) and shows
every destination as category-grouped tiles. Click a tile → jump to that page
and close. Esc or a click outside the panel closes it. No typing anywhere.

Reads the 3-level hierarchy from ui/menu_tree.py, so it stays in lock-step
with the sidebar (Mode A). Works for BOTH AccountsHQ and RWA HQ because it
groups window._pages by label — the tree rules cover both apps' page labels.

The most-recently-visited pages appear in a "Recent" row at the top
(persisted in user_prefs under "nav_recent"), so the common screens are one
click away without scrolling.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy,
)

from ui.theme import THEME
from ui import menu_tree

_RECENT_KEY = "nav_recent"
_RECENT_MAX = 6
_COLS = 4   # tiles per row inside a group

# Section → accent colour for the little square dot.
_SECTION_COLOR = {
    "RWA · Society": "#5b8cff",
    "Accounting":    "#34d399",
    "Reports":       "#f59e0b",
    "Tools":         "#a78bfa",
    "Settings":      "#f472b6",
    "More":          "#94a3b8",
}


def _recent_labels() -> list[str]:
    try:
        from core.user_prefs import prefs
        val = prefs.get(_RECENT_KEY, [])
        return list(val) if isinstance(val, list) else []
    except Exception:
        return []


def record_recent(label: str) -> None:
    """Push `label` to the front of the recent list (delete dupes, cap size)."""
    try:
        from core.user_prefs import prefs
        cur = _recent_labels()
        cur = [x for x in cur if x != label]
        cur.insert(0, label)
        prefs.set(_RECENT_KEY, cur[:_RECENT_MAX])
    except Exception:
        pass


class NavLauncher(QWidget):
    """Overlay launcher. One instance per MainWindow, shown/hidden."""

    def __init__(self, window):
        # Parent to the central widget so the overlay covers sidebar + content.
        parent = window.centralWidget() or window
        super().__init__(parent)
        self._window = window
        self.setObjectName("nav_launcher")
        self.hide()

        # Full-area dim scrim.
        self.setStyleSheet(f"#nav_launcher {{ background: rgba(5, 8, 16, 0.62); }}")

        scrim = QVBoxLayout(self)
        scrim.setContentsMargins(0, 0, 0, 0)
        scrim.addStretch()

        center = QHBoxLayout()
        center.addStretch()

        # ── The panel ──
        self._panel = QFrame()
        self._panel.setObjectName("launcher_panel")
        self._panel.setStyleSheet(f"""
            #launcher_panel {{
                background: {THEME['bg_sidebar']};
                border: 1px solid {THEME['border']};
                border-radius: 16px;
            }}
        """)
        self._panel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        pv = QVBoxLayout(self._panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)

        # Header
        header = QFrame()
        header.setStyleSheet(f"border-bottom: 1px solid {THEME['border']};")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(24, 16, 18, 16)
        title = QLabel("Jump to…")
        title.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:17px; font-weight:bold;"
            " background: transparent; border: none;")
        hl.addWidget(title)
        hl.addStretch()
        hint = QLabel("click a tile  ·  Esc to close")
        hint.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:12px;"
            " background: transparent; border: none;")
        hl.addWidget(hint)
        close = QPushButton("✕")
        close.setFixedSize(30, 30)
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(f"""
            QPushButton {{ background: transparent; border: none;
                color:{THEME['text_secondary']}; font-size:16px; }}
            QPushButton:hover {{ color:{THEME['accent']}; }}
        """)
        close.clicked.connect(self.close_launcher)
        hl.addWidget(close)
        pv.addWidget(header)

        # Scrollable body
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._body = QWidget()
        self._body.setStyleSheet("background: transparent;")
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(24, 12, 24, 24)
        self._body_layout.setSpacing(2)
        scroll.setWidget(self._body)
        pv.addWidget(scroll, 1)

        center.addWidget(self._panel)
        center.addStretch()
        scrim.addLayout(center)
        scrim.addStretch()

    # ── Build / rebuild the tile content ─────────────────────────────────────

    def _clear_body(self) -> None:
        while self._body_layout.count():
            item = self._body_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def _nav_items(self) -> list[tuple[int, str, str]]:
        """(idx, label, icon) for every page except Home (logo-only)."""
        items = []
        for idx, entry in enumerate(self._window._pages):
            label, icon = entry[0], entry[1]
            if (label or "").strip().lower() == "home":
                continue
            items.append((idx, label, icon))
        return items

    def _go(self, idx: int, label: str) -> None:
        record_recent(label)
        self.close_launcher()
        self._window._select_page(idx)

    def _make_tile(self, idx: int, label: str, icon: str) -> QPushButton:
        btn = QPushButton()
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setMinimumHeight(58)
        btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['bg_hover']};
                border: 1px solid {THEME['border']};
                border-radius: 12px;
                text-align: left;
            }}
            QPushButton:hover {{ border-color: {THEME['accent']}; }}
        """)
        row = QHBoxLayout(btn)
        row.setContentsMargins(13, 8, 12, 8)
        row.setSpacing(11)
        ic = QLabel(icon)
        ic.setFixedWidth(26)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(f"font-size:21px; background:transparent; border:none;"
                         f" color:{THEME['text_primary']};")
        row.addWidget(ic)
        nm = QLabel(label)
        nm.setStyleSheet(f"font-size:13px; font-weight:600; background:transparent;"
                         f" border:none; color:{THEME['text_primary']};")
        nm.setWordWrap(True)
        row.addWidget(nm, 1)
        btn.clicked.connect(lambda _=False, i=idx, l=label: self._go(i, l))
        return btn

    def _add_grid(self, tiles: list[QPushButton]) -> None:
        host = QWidget()
        host.setStyleSheet("background: transparent;")
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 0, 8)
        grid.setHorizontalSpacing(11)
        grid.setVerticalSpacing(11)
        for c in range(_COLS):
            grid.setColumnStretch(c, 1)
        for i, t in enumerate(tiles):
            grid.addWidget(t, i // _COLS, i % _COLS)
        self._body_layout.addWidget(host)

    def _section_header(self, name: str) -> None:
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        h = QHBoxLayout(wrap)
        h.setContentsMargins(0, 16, 0, 6)
        h.setSpacing(9)
        dot = QLabel()
        dot.setFixedSize(11, 11)
        dot.setStyleSheet(
            f"background:{_SECTION_COLOR.get(name, '#94a3b8')}; border-radius:3px;")
        h.addWidget(dot)
        lbl = QLabel(name)
        lbl.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:14px; font-weight:800;"
            " letter-spacing:0.5px; background:transparent;")
        h.addWidget(lbl)
        h.addStretch()
        self._body_layout.addWidget(wrap)

    def _group_header(self, name: str) -> None:
        if not name:
            return
        lbl = QLabel(name.upper())
        lbl.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; font-weight:700;"
            " letter-spacing:1.4px; padding:6px 0 4px; background:transparent;")
        self._body_layout.addWidget(lbl)

    def _build_recent(self, items: list[tuple[int, str, str]]) -> None:
        by_label = {label: (idx, icon) for idx, label, icon in items}
        recent = [l for l in _recent_labels() if l in by_label]
        if not recent:
            return
        cap = QLabel("⭐  RECENT")
        cap.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; font-weight:700;"
            " letter-spacing:1.4px; padding:4px 0 6px; background:transparent;")
        self._body_layout.addWidget(cap)
        wrap = QWidget()
        wrap.setStyleSheet("background: transparent;")
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 4)
        row.setSpacing(9)
        for label in recent:
            idx, icon = by_label[label]
            chip = QPushButton(f"{icon}  {label}")
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFixedHeight(34)
            chip.setStyleSheet(f"""
                QPushButton {{
                    background: {THEME['bg_hover']};
                    border: 1px solid {THEME['border']};
                    border-radius: 17px; padding: 0 16px;
                    font-size: 12.5px; color: {THEME['text_primary']};
                }}
                QPushButton:hover {{ border-color: {THEME['accent']}; }}
            """)
            chip.clicked.connect(lambda _=False, i=idx, l=label: self._go(i, l))
            row.addWidget(chip)
        row.addStretch()
        self._body_layout.addWidget(wrap)

    def _populate(self) -> None:
        self._clear_body()
        items = self._nav_items()
        self._build_recent(items)
        tree = menu_tree.build_tree(items, label_of=lambda t: t[1])
        for section, groups in tree:
            self._section_header(section)
            for group, group_items in groups:
                self._group_header(group)
                tiles = [self._make_tile(i, l, ic) for (i, l, ic) in group_items]
                self._add_grid(tiles)
        self._body_layout.addStretch()

    # ── Show / hide ──────────────────────────────────────────────────────────

    def open_launcher(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        # Size the panel to ~82% × ~84% of the available area.
        if parent is not None:
            self._panel.setFixedSize(int(parent.width() * 0.82),
                                     int(parent.height() * 0.84))
        self._populate()
        self.show()
        self.raise_()
        self.setFocus()

    def close_launcher(self) -> None:
        self.hide()

    def toggle(self) -> None:
        self.close_launcher() if self.isVisible() else self.open_launcher()

    # ── Dismiss interactions ─────────────────────────────────────────────────

    def keyPressEvent(self, ev) -> None:
        if ev.key() == Qt.Key.Key_Escape:
            self.close_launcher()
            return
        super().keyPressEvent(ev)

    def mousePressEvent(self, ev) -> None:
        # Right-click or the mouse 'back' button closes from anywhere — a
        # one-action "back out" of the menu without reaching for the keyboard.
        if ev.button() in (Qt.MouseButton.RightButton, Qt.MouseButton.BackButton):
            self.close_launcher()
            return
        # A left-click outside the panel also closes; clicks inside fall
        # through to the tiles.
        if not self._panel.geometry().contains(ev.pos()):
            self.close_launcher()
            return
        super().mousePressEvent(ev)
