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

from PySide6.QtCore import Qt, QEvent
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QLineEdit,
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
        # Parent to the MAIN WINDOW (not just the central widget) so the dim
        # overlay covers EVERYTHING — sidebar, content AND the status bar —
        # leaving no bright strip behind the launcher.
        parent = window
        super().__init__(parent)
        self._window = window
        self._query = ""              # current search text
        self._first_match = None      # (idx, label) of first result, for Enter
        self.setObjectName("nav_launcher")
        # A plain QWidget won't paint a stylesheet `background` unless this is
        # set — without it the dim scrim never actually rendered (the screen
        # behind stayed bright). This is what makes the overlay darken.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.hide()

        # Full-area dim scrim — strong, so the screen behind clearly recedes
        # and the launcher reads as a focused, near-fullscreen modal.
        self.setStyleSheet(f"#nav_launcher {{ background: rgba(5, 8, 16, 0.88); }}")

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
        hint = QLabel("type to search  ·  Esc to close")
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

        # Search row — type to filter the tiles to matching menu items.
        search_wrap = QFrame()
        search_wrap.setStyleSheet("background: transparent; border: none;")
        swl = QVBoxLayout(search_wrap)
        swl.setContentsMargins(24, 14, 24, 2)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search the menu — type a screen name…")
        self._search.setClearButtonEnabled(True)
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {THEME['bg_hover']};
                border: 1px solid {THEME['border']};
                border-radius: 10px; padding: 9px 12px;
                font-size: 13px; color: {THEME['text_primary']};
            }}
            QLineEdit:focus {{ border-color: {THEME['accent']}; }}
        """)
        self._search.textChanged.connect(self._on_search)
        self._search.installEventFilter(self)
        swl.addWidget(self._search)
        pv.addWidget(search_wrap)

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
        """(idx, label, icon) for every page except Home (shown as a pinned
        Dashboard tile, not grouped into the tree — see `_home_searchable`)."""
        items = []
        for idx, entry in enumerate(self._window._pages):
            label, icon = entry[0], entry[1]
            if (label or "").strip().lower() == "home":
                continue
            items.append((idx, label, icon))
        return items

    def _home_searchable(self) -> tuple[int, str, str] | None:
        """The Home page presented as a 'Dashboard' launcher entry, or None if
        the app has no Home page. The sidebar reaches Home via its logo, but the
        tile launcher has no logo — without this the dashboard is unreachable
        from the menu."""
        for idx, entry in enumerate(self._window._pages):
            if (entry[0] or "").strip().lower() == "home":
                return idx, "Dashboard", (entry[1] or "🏠")
        return None

    def _build_pinned(self) -> None:
        """A single always-on Dashboard tile at the very top of the launcher."""
        home = self._home_searchable()
        if home is None:
            return
        idx, label, icon = home
        cap = QLabel("🏠  DASHBOARD")
        cap.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; font-weight:700;"
            " letter-spacing:1.4px; padding:4px 0 6px; background:transparent;")
        self._body_layout.addWidget(cap)
        self._add_grid([self._make_tile(idx, label, icon)])

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

    def _make_action_tile(self, label: str, icon: str, on_click) -> QPushButton:
        """A tile that runs a callback (e.g. opens the Setup wizard) instead of
        jumping to a registered page."""
        btn = self._make_tile(-1, label, icon)
        btn.clicked.disconnect()
        btn.clicked.connect(lambda _=False: (self.close_launcher(), on_click()))
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

    def _searchables(self, items):
        """Flat list of (idx, label, icon) the search can match — every nav
        item, the Dashboard, plus the Quick Setup action (idx -1)."""
        out = list(items)
        home = self._home_searchable()
        if home is not None:
            out.insert(0, home)
        if hasattr(self._window, "open_setup_wizard"):
            out.append((-1, "Quick Setup", "⚙"))
        return out

    def _populate_results(self, items, q: str) -> None:
        """Flat, ungrouped grid of every menu item whose label contains `q`."""
        matches = [(i, l, ic) for (i, l, ic) in self._searchables(items)
                   if q in (l or "").lower()]
        self._first_match = (matches[0][0], matches[0][1]) if matches else None
        cap = QLabel(f"RESULTS · {len(matches)}")
        cap.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; font-weight:700;"
            " letter-spacing:1.4px; padding:4px 0 6px; background:transparent;")
        self._body_layout.addWidget(cap)
        if not matches:
            empty = QLabel("No menu items match your search.")
            empty.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:13px;"
                " padding:8px 2px; background:transparent;")
            self._body_layout.addWidget(empty)
            return
        tiles = []
        for (i, l, ic) in matches:
            if i == -1:     # the Quick Setup action
                tiles.append(self._make_action_tile(
                    l, ic, self._window.open_setup_wizard))
            else:
                tiles.append(self._make_tile(i, l, ic))
        self._add_grid(tiles)

    def _on_search(self, text: str) -> None:
        self._query = text or ""
        self._populate()

    def _activate_first(self) -> None:
        if self._first_match is not None:
            idx, label = self._first_match
            if idx == -1:
                self.close_launcher()
                self._window.open_setup_wizard()
            else:
                self._go(idx, label)

    def _populate(self) -> None:
        self._clear_body()
        items = self._nav_items()
        q = (self._query or "").strip().lower()
        if q:                              # search mode: flat results, no Recent
            self._populate_results(items, q)
            self._body_layout.addStretch()
            return
        self._first_match = None
        self._build_pinned()
        self._build_recent(items)
        tree = menu_tree.build_tree(items, label_of=lambda t: t[1])
        # Quick Setup lives as a tile under the "Settings" heading.
        wants_setup = hasattr(self._window, "open_setup_wizard")
        setup_added = False
        for section, groups in tree:
            self._section_header(section)
            for gi, (group, group_items) in enumerate(groups):
                self._group_header(group)
                tiles = [self._make_tile(i, l, ic) for (i, l, ic) in group_items]
                if wants_setup and not setup_added and section == "Settings" and gi == 0:
                    tiles.append(self._make_action_tile(
                        "Quick Setup", "⚙", self._window.open_setup_wizard))
                    setup_added = True
                self._add_grid(tiles)
        if wants_setup and not setup_added:        # no Settings section → give it one
            self._section_header("Settings")
            self._add_grid([self._make_action_tile(
                "Quick Setup", "⚙", self._window.open_setup_wizard)])
        self._body_layout.addStretch()

    # ── Show / hide ──────────────────────────────────────────────────────────

    def open_launcher(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        # Size the panel to ~92% × ~90% of the window — near-fullscreen, with
        # just a thin dimmed frame so it's clearly a modal over the app.
        if parent is not None:
            self._panel.setFixedSize(int(parent.width() * 0.92),
                                     int(parent.height() * 0.90))
        # Start every open with a clear search box, focused so the user can
        # just start typing to find a screen.
        self._search.blockSignals(True)
        self._search.clear()
        self._search.blockSignals(False)
        self._query = ""
        self._populate()
        self.show()
        self.raise_()
        self._search.setFocus()

    def close_launcher(self) -> None:
        self.hide()

    def toggle(self) -> None:
        self.close_launcher() if self.isVisible() else self.open_launcher()

    # ── Dismiss interactions ─────────────────────────────────────────────────

    def eventFilter(self, obj, ev) -> bool:
        # Keys typed inside the search box: Esc clears (then closes), Enter
        # jumps to the first match.
        if obj is self._search and ev.type() == QEvent.Type.KeyPress:
            k = ev.key()
            if k == Qt.Key.Key_Escape:
                if self._search.text():
                    self._search.clear()
                else:
                    self.close_launcher()
                return True
            if k in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._activate_first()
                return True
        return super().eventFilter(obj, ev)

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
