"""Shared small widgets for the Store HQ screens — keyboard-first, no big buttons.
Mirrors the chip-button look used by ui/widgets.py (the F2/F3 chips)."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton
from ui.theme import THEME


def chip_btn(label: str, tooltip: str = "", slot=None) -> QPushButton:
    """A compact chip button (e.g. 'F2', '↻'). The keyboard shortcut is the real
    entry point; the chip is just a visible hint, never a big primary button."""
    b = QPushButton(label)
    b.setFixedHeight(30)
    b.setToolTip(tooltip)
    b.setStyleSheet(f"""
        QPushButton {{
            background: {THEME['bg_hover']};
            border: 1px solid {THEME['border']};
            border-radius: 7px;
            color: {THEME['text_secondary']};
            font-size: 11px;
            font-weight: bold;
            padding: 2px 10px;
        }}
        QPushButton:hover {{
            background: {THEME['accent_dim']};
            color: {THEME['accent']};
            border-color: {THEME['accent']};
        }}
    """)
    if slot is not None:
        b.clicked.connect(slot)
    return b
