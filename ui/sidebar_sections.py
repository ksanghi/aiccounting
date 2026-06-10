"""
Collapsible sidebar sections — navigation Mode A (shared base UI).

MainWindow.register_page() builds the sidebar linearly (a NavButton per page
plus optional section-header labels). This module post-processes that flat
list into a THREE-level collapsible tree, driven by ui/menu_tree.py:

  ▾ ACCOUNTING            ← section (collapsible)
        ENTRY             ← group sub-header (the middle level)
          Post Voucher    ← page
          Auto Post
        RECONCILIATION
          Bank Reconciliation
  ▸ REPORTS
  ▸ TOOLS
  …

The section/group assignment lives entirely in ui/menu_tree.py so the sidebar
(this file) and the tile launcher (ui/nav_launcher.py) can never drift.

The NavButton widgets are reused (re-parented), so the click wiring through
MainWindow._select_page() stays intact. RHQ keeps its own sidebar map
(rwagenie/app/sidebar.py) and overrides _finalize_sidebar.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QSizePolicy

from ui.theme import THEME
from ui import menu_tree


class CollapsibleSection(QWidget):
    """A clickable section header that shows/hides a stack of NavButtons
    (optionally split by group sub-headers). Emits expanded_changed so the
    host can enforce accordion behaviour (open one → collapse the rest)."""

    expanded_changed = Signal(bool)

    def __init__(self, title: str, expanded: bool = False, parent=None):
        super().__init__(parent)
        self._title = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.setSpacing(0)

        self._header = QPushButton()
        self._header.setFixedHeight(28)
        self._header.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._header.clicked.connect(self.toggle)
        outer.addWidget(self._header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(0)
        outer.addWidget(self._body)

        self._apply_state()

    def add_button(self, button: QWidget) -> None:
        button.setParent(self._body)
        self._body_layout.addWidget(button)

    def add_subheader(self, text: str) -> None:
        """A small group label inside the section body (the middle level)."""
        if not text:
            return
        lbl = QLabel(text.upper())
        lbl.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:9px; font-weight:bold;"
            " letter-spacing:1px; padding:6px 14px 2px;")
        self._body_layout.addWidget(lbl)

    def is_empty(self) -> bool:
        return self._body_layout.count() == 0

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, value: bool, emit: bool = True) -> None:
        value = bool(value)
        if value == self._expanded:
            return
        self._expanded = value
        self._apply_state()
        if emit:
            self.expanded_changed.emit(value)

    def toggle(self) -> None:
        self.set_expanded(not self._expanded)

    def _apply_state(self) -> None:
        self._body.setVisible(self._expanded)
        arrow = "▾" if self._expanded else "▸"
        self._header.setText(f"  {arrow}   {self._title.upper()}")
        self._header.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {THEME['text_secondary']};
                font-size: 10px; font-weight: bold; letter-spacing: 1px;
                text-align: left; padding: 6px 14px;
            }}
            QPushButton:hover {{ color: {THEME['accent']}; }}
        """)


# Back-compat shim — some code may still import this. Delegates to menu_tree.
def section_for_label(label: str) -> str:
    return menu_tree.resolve(label)[0]


def regroup_into_sections(window) -> None:
    """Mode A sidebar. Now a compact header rail + hover flyout (see
    ui/nav_flyout.py) rather than an inline accordion — the section contents
    fly out over the content area, open on hover/click, show one at a time,
    and auto-collapse when a page is picked."""
    from ui.nav_flyout import build_flyout_rail
    build_flyout_rail(window)
    return


def _regroup_accordion_legacy(window) -> None:
    """Previous inline-accordion grouping — kept for reference, unused."""
    nav = getattr(window, "_nav_container", None)
    pages = getattr(window, "_pages", None)
    if nav is None or pages is None:
        return

    # 1. Drop the Home nav button (reached via the logo, not the menu); keep
    #    the rest as (label, button) items for the tree builder.
    items = []
    for entry in pages:
        label, btn = entry[0], entry[-1]
        if (label or "").strip().lower() == "home":
            btn.setParent(None)
            continue
        items.append((label, btn))

    # 2. Detach everything currently in the nav (buttons + old header labels).
    while nav.count() > 0:
        item = nav.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)

    # 3. Build the tree and rebuild as collapsible sections with group
    #    sub-headers.
    tree = menu_tree.build_tree(items, label_of=lambda it: it[0])
    sections: list[CollapsibleSection] = []
    for sec_name, groups in tree:
        expanded = sec_name in menu_tree.DEFAULT_EXPANDED
        section = CollapsibleSection(sec_name, expanded=expanded)
        multi = sum(1 for g, _ in groups if g) > 0
        for group_name, group_items in groups:
            if multi:
                section.add_subheader(group_name)
            for _label, btn in group_items:
                section.add_button(btn)
        nav.addWidget(section)
        sections.append(section)

    # 4. Accordion: opening one section collapses the others.
    def _accordion(is_open: bool, opener: CollapsibleSection) -> None:
        if not is_open:
            return
        for s in sections:
            if s is not opener and s.is_expanded():
                s.set_expanded(False, emit=False)
    for s in sections:
        s.expanded_changed.connect(
            lambda is_open, opener=s: _accordion(is_open, opener))
