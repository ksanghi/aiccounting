"""
Bento-style reusable widgets.

Drop these into any page to get instant bento aesthetic:

    from ui.bento_widgets import KPITile, StatusPill, ActionCard, BentoFooter

    layout.addWidget(KPITile("Overdue", "₹68,300", "5 invoices",
                              status="bad"))
    layout.addWidget(StatusPill("Overdue", status="bad"))

All widgets pick up their colours from the live theme dict, so a
theme-mode switch (`ui.theme.set_theme_mode("dark")`) repaints them
without further changes — Qt re-applies the stylesheet.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore    import Qt, Signal
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget,
)

from ui.theme import THEME


# ── KPI tile ───────────────────────────────────────────────────────────

class KPITile(QFrame):
    """Big number summary card.

      ┌────────────────┐
      │ LABEL          │
      │ ₹2.42L         │
      │ ↑ 12% vs Apr   │
      └────────────────┘

    `status` picks a coloured background variant:
      ""     — neutral (default card)
      "good" — green tint, value text green
      "warn" — amber tint, value text amber
      "bad"  — red tint, value text red
    """

    clicked = Signal()

    def __init__(self, label: str, value: str = "",
                 delta: str = "", status: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        status = (status or "").lower()
        suffix = {"good": "_good", "warn": "_warn", "bad": "_bad"}.get(status, "")
        value_suffix = {"good": "_good", "warn": "_warn", "bad": "_bad"}.get(status, "")
        self.setObjectName(f"bento_tile{suffix}")
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Preferred)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)

        self._lbl = QLabel(label.upper())
        self._lbl.setObjectName("bento_label")
        lay.addWidget(self._lbl)

        self._val = QLabel(value)
        self._val.setObjectName(f"bento_value{value_suffix}")
        lay.addWidget(self._val)

        self._delta = QLabel(delta)
        self._delta.setObjectName("bento_delta")
        self._delta.setVisible(bool(delta))
        lay.addWidget(self._delta)

    def set_value(self, value: str) -> None:
        self._val.setText(value)

    def set_delta(self, delta: str) -> None:
        self._delta.setText(delta)
        self._delta.setVisible(bool(delta))

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ── Status pill ────────────────────────────────────────────────────────

class StatusPill(QLabel):
    """Compact, coloured status label.

    >>> StatusPill("Paid", status="good")
    >>> StatusPill("Overdue", status="bad")
    >>> StatusPill("Due 3d", status="warn")
    >>> StatusPill("Draft", status="info")
    """

    def __init__(self, text: str, status: str = "",
                 parent: Optional[QWidget] = None):
        super().__init__(text, parent)
        self.set_status(status)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(20)
        self.setMaximumHeight(22)

    def set_status(self, status: str) -> None:
        s = (status or "info").lower()
        obj = {
            "good":     "status_pill_good",
            "warn":     "status_pill_warn",
            "bad":      "status_pill_bad",
            "info":     "status_pill_info",
        }.get(s, "status_pill_info")
        self.setObjectName(obj)


# ── Action card ────────────────────────────────────────────────────────

class ActionCard(QFrame):
    """Tap-to-act card with an icon, title and subtitle.

      ┌──────────────────────────────┐
      │ [📤]  Send broadcast         │
      │       SMS / WhatsApp to all  │
      └──────────────────────────────┘
    """

    clicked = Signal()

    def __init__(self, title: str, subtitle: str = "",
                 icon: str = "•",
                 parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("action_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Preferred)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        ic = QLabel(icon)
        ic.setFixedSize(36, 36)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setStyleSheet(
            f"background-color: {THEME['accent_soft']}; "
            f"color: {THEME['accent']}; "
            f"border-radius: 10px; font-size: 16px;"
        )
        lay.addWidget(ic)

        inner = QVBoxLayout()
        inner.setContentsMargins(0, 0, 0, 0)
        inner.setSpacing(0)
        t = QLabel(title)
        t.setObjectName("action_card_title")
        inner.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("action_card_subtitle")
            inner.addWidget(s)
        lay.addLayout(inner, 1)

    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(ev)


# ── Bento footer (e.g. voucher form summary + save) ────────────────────

class BentoFooter(QFrame):
    """Footer with up to N small status tiles + a save-button area.

    Use:

        footer = BentoFooter()
        footer.add_tile("Lines", "5")
        footer.add_tile("Total receipts", "₹16,950")
        footer.add_tile("Balance check", "✓ Balanced", status="good")
        footer.add_button(QPushButton("Save voucher", primary=True))
    """

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("bento_footer")
        self.setStyleSheet(
            f"#bento_footer {{ background-color: {THEME['bg_card_2']}; "
            f"border-top: 1px solid {THEME['border']}; }}"
        )
        self._lay = QHBoxLayout(self)
        self._lay.setContentsMargins(18, 14, 18, 14)
        self._lay.setSpacing(12)
        self._tiles_added = 0

    def add_tile(self, label: str, value: str, status: str = "") -> KPITile:
        tile = KPITile(label, value, "", status=status)
        # Smaller footer tile — override the bento_value font-size locally.
        tile.setStyleSheet(
            f"#bento_value {{ font-size: 16px; }} "
            f"#bento_value_good {{ font-size: 16px; }} "
            f"#bento_value_warn {{ font-size: 16px; }} "
            f"#bento_value_bad  {{ font-size: 16px; }}"
        )
        tile.setSizePolicy(QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Fixed)
        self._lay.addWidget(tile)
        self._tiles_added += 1
        return tile

    def add_spacer(self) -> None:
        self._lay.addStretch(1)

    def add_button(self, btn: QWidget) -> None:
        self._lay.addWidget(btn)


# ── Helper: row of KPI tiles ───────────────────────────────────────────

def kpi_row(parent: Optional[QWidget] = None) -> QHBoxLayout:
    """Convenience: create a horizontal layout for a row of KPITiles.
    Use:

        row = kpi_row()
        row.addWidget(KPITile(...))
        row.addWidget(KPITile(...))
        outer.addLayout(row)
    """
    h = QHBoxLayout()
    h.setSpacing(14)
    h.setContentsMargins(0, 0, 0, 0)
    return h
