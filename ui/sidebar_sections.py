"""
Collapsible sidebar sections — shared base UI.

MainWindow.register_page() builds the sidebar linearly (a NavButton per page
plus optional section-header labels). With GST/TDS reports, reconciliation,
and the Document Inbox added, AHQ's sidebar now runs long. This module
post-processes that flat list into collapsible groups:

  ▾ TRANSACTIONS   ← expanded
        Post Voucher
        Day Book
  ▸ REPORTS
  ▸ TAX
  …

This was originally built in RWAGenie (rwagenie/app/sidebar.py); it's been
moved DOWN into the AHQ base so AHQ gets the grouped menu too, and RHQ can
share the same widget. RHQ keeps its own RWA-specific section map and skips
the base grouping (it overrides MainWindow._finalize_sidebar to a no-op and
groups with its own map after adding RWA pages).

The NavButton widgets are reused (re-parented), so navigation click wiring
through MainWindow._select_page() stays intact.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QSizePolicy

from ui.theme import THEME


class CollapsibleSection(QWidget):
    """A clickable section header that shows/hides a stack of NavButtons.
    Emits expanded_changed(is_expanded) so the host can enforce accordion
    behaviour (open one → collapse the rest)."""

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


# ── AHQ section map (case-insensitive substring; first match wins; anything
# unmatched lands in "Other" so a page is never dropped). ────────────────────
_LABEL_TO_SECTION: list[tuple[str, str]] = [
    ("Post Voucher",     "Transactions"),
    ("Day Book",         "Transactions"),
    ("Ledger Balances",  "Transactions"),
    ("Verbal",           "Transactions"),
    ("Reconcil",         "Reconciliation"),   # before the report/book matches
    ("Trial Balance",    "Reports"),
    ("Profit",           "Reports"),
    ("P & L",            "Reports"),
    ("P&L",              "Reports"),
    ("Balance Sheet",    "Reports"),
    ("Cash Book",        "Reports"),
    ("Bank Book",        "Reports"),
    ("Ledger Account",   "Reports"),
    ("Receipt",          "Reports"),
    ("Rcpt",             "Reports"),
    ("Aging",            "Reports"),
    ("Ageing",           "Reports"),
    ("GST",              "Tax"),
    ("TDS",              "Tax"),
    ("HSN",              "Tax"),
    ("Document Inbox",   "AI"),
    ("AI Doc",           "AI"),
    ("Backup",           "Data"),
    ("Migration",        "Data"),
    ("Period Lock",      "Data"),
    ("License",          "Account"),
    ("Feedback",         "Account"),
    ("Settings",         "Account"),
]

# Section order top→bottom; bool = expanded by default.
SECTION_ORDER: list[tuple[str, bool]] = [
    ("Transactions",   True),
    ("Reports",        False),
    ("Tax",            False),
    ("Reconciliation", False),
    ("AI",             False),
    ("Data",           False),
    ("Account",        False),
    ("Other",          False),
]


def section_for_label(label: str) -> str:
    lower = (label or "").lower()
    for needle, section in _LABEL_TO_SECTION:
        if needle.lower() in lower:
            return section
    return "Other"


def regroup_into_sections(window) -> None:
    """Rebuild window's flat sidebar (_nav_container of NavButtons + section
    QLabels) into collapsible sections. Operates on window._pages (the
    authoritative page list) and window._nav_container. Safe to call once
    after all pages are registered."""
    nav = getattr(window, "_nav_container", None)
    pages = getattr(window, "_pages", None)
    if nav is None or pages is None:
        return

    # 1. Bucket each page's NavButton by section.
    buckets: dict[str, list] = {name: [] for name, _ in SECTION_ORDER}
    for entry in pages:
        # MainWindow stores (label, icon, widget, button) tuples.
        label, btn = entry[0], entry[-1]
        sec = section_for_label(label)
        buckets.setdefault(sec, []).append(btn)

    # 2. Detach everything currently in the nav (buttons + old header labels).
    while nav.count() > 0:
        item = nav.takeAt(0)
        w = item.widget()
        if w is not None:
            w.setParent(None)

    # 3. Rebuild as one CollapsibleSection per non-empty bucket.
    sections: list[CollapsibleSection] = []
    for sec_name, expanded in SECTION_ORDER:
        btns = buckets.get(sec_name, [])
        if not btns:
            continue
        section = CollapsibleSection(sec_name, expanded=expanded)
        for btn in btns:
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
