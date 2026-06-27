"""
Flyout navigation rail — Mode A (shared base UI), hover/click flyout style.

The sidebar shows only SECTION headers. Hovering OR clicking a header pops a
floating panel out OVER the content area listing that section's pages (grouped
by sub-group). The flyout:
  • opens on hover OR click,
  • shows only ONE section at a time,
  • auto-closes when you pick a page (auto-collapse on selection),
  • auto-closes shortly after the mouse leaves it (so it doesn't linger).

This replaces the old inline accordion: the rail stays compact (just headers),
and the page list gets real room by bleeding over the data area. Driven by
ui/menu_tree.py so it stays in lock-step with the tile launcher (Mode B), and
it re-parents the existing NavButton widgets, so click wiring through
MainWindow._select_page() is untouched.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QFrame, QStackedWidget,
    QSizePolicy,
)

from ui.theme import THEME
from ui import menu_tree


class _RailHeader(QPushButton):
    """Section header in the rail. Emits on hover-in / hover-out so the host
    can drive the flyout."""
    hovered = Signal()
    left = Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(34)

    def enterEvent(self, e):
        self.hovered.emit()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.left.emit()
        super().leaveEvent(e)


class SectionFlyout(QWidget):
    """Floating panel (child of the central widget) that overlays the content
    area and shows one section's pages. Shown via show_for()."""

    def __init__(self, window):
        parent = window.centralWidget() or window
        super().__init__(parent)
        self._window = window
        self.setObjectName("section_flyout")
        self.hide()

        # Small delay before auto-hiding, so moving the mouse from the header
        # across to the flyout doesn't flicker it shut.
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(220)
        self._hide_timer.timeout.connect(self.hide)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame()
        self._card.setObjectName("flyout_card")
        outer.addWidget(self._card)
        cv = QVBoxLayout(self._card)
        cv.setContentsMargins(8, 8, 8, 10)
        cv.setSpacing(2)
        self._title = QLabel()
        cv.addWidget(self._title)
        self._stack = QStackedWidget()
        cv.addWidget(self._stack)
        self._panels: dict[str, int] = {}
        self.apply_theme()

    def add_panel(self, section: str, widget: QWidget) -> None:
        self._panels[section] = self._stack.addWidget(widget)

    def show_for(self, section: str, header: QWidget) -> None:
        if section not in self._panels:
            return
        self._hide_timer.stop()
        self._stack.setCurrentIndex(self._panels[section])
        # Size the stack to THIS section's panel, so a short menu isn't
        # stretched to the tallest section's height (what spread the items).
        cur = self._stack.currentWidget()
        if cur is not None:
            self._stack.setFixedHeight(cur.sizeHint().height())
        self._title.setText(section.upper())
        self.adjustSize()
        cw = self.parentWidget()
        if cw is None:
            return
        sb = getattr(self._window, "_sidebar", None)
        x = sb.width() if sb is not None else 200
        try:
            top = header.mapTo(cw, header.rect().topLeft()).y()
        except Exception:
            top = 60
        h = self.sizeHint().height()
        y = max(2, min(top, cw.height() - h - 6))
        self.move(x, y)
        self.show()
        self.raise_()

    def schedule_hide(self) -> None:
        self._hide_timer.start()

    def enterEvent(self, e):
        self._hide_timer.stop()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._hide_timer.start()
        super().leaveEvent(e)

    def apply_theme(self) -> None:
        self._card.setStyleSheet(f"""
            #flyout_card {{
                background: {THEME['bg_sidebar']};
                border: 1px solid {THEME['border']};
                border-radius: 12px;
            }}
        """)
        self._title.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; font-weight:bold;"
            " letter-spacing:1.2px; padding:4px 8px 6px; background:transparent;")


def _header_qss() -> str:
    return f"""
        QPushButton {{
            background: transparent; border: none;
            color: {THEME['text_secondary']};
            font-size: 11px; font-weight: bold; letter-spacing: 0.8px;
            text-align: left; padding: 6px 14px;
        }}
        QPushButton:hover {{
            background: {THEME['bg_hover']};
            color: {THEME['accent']};
        }}
    """


def build_flyout_rail(window) -> None:
    """Rebuild window's flat sidebar into the compact header rail + a hover
    flyout. Safe to call once after all pages are registered."""
    nav = getattr(window, "_nav_container", None)
    pages = getattr(window, "_pages", None)
    if nav is None or pages is None:
        return

    # 1. Collect (label, button) for every page except Home (logo-only).
    items = []
    for entry in pages:
        label, btn = entry[0], entry[-1]
        if (label or "").strip().lower() == "home":
            btn.setParent(None)
            continue
        items.append((label, btn))

    # 2. Clear whatever is in the rail now.
    while nav.count() > 0:
        it = nav.takeAt(0)
        w = it.widget()
        if w is not None:
            w.setParent(None)

    # 3. One flyout for the whole rail; one stacked panel per section.
    flyout = SectionFlyout(window)
    window._nav_flyout = flyout

    tree = menu_tree.build_tree(items, label_of=lambda it: it[0])
    for section, groups in tree:
        header = _RailHeader("  " + section.upper())
        header.setStyleSheet(_header_qss())

        panel = QWidget()
        panel.setMinimumWidth(232)
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        multi = any(g for g, _ in groups)
        for gname, gitems in groups:
            if multi and gname:
                sub = QLabel(gname.upper())
                sub.setStyleSheet(
                    f"color:{THEME['text_dim']}; font-size:9px; font-weight:bold;"
                    " letter-spacing:1px; padding:6px 12px 2px; background:transparent;")
                pv.addWidget(sub)
            for _label, btn in gitems:
                btn.setParent(panel)
                pv.addWidget(btn)
                # Auto-collapse on selection: picking a page hides the flyout.
                btn.clicked.connect(lambda *_: flyout.hide())
        pv.addStretch(1)   # top-align: absorb any extra height at the bottom
        flyout.add_panel(section, panel)

        header.hovered.connect(lambda s=section, h=header: flyout.show_for(s, h))
        header.clicked.connect(
            lambda _=False, s=section, h=header: flyout.show_for(s, h))
        header.left.connect(flyout.schedule_hide)
        nav.addWidget(header)

    nav.addStretch()
