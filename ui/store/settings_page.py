"""Store HQ — Settings: store/company profile, sales-tax rate (drives sales),
and the keyboard reference. Tax rate writes companies.sales_tax_rate (no new
storage — the engine already reads it)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFormLayout, QFrame,
    QDoubleSpinBox, QMessageBox,
)

from ui.theme import THEME
from ui.widgets import make_label
from core import branding
try:
    from core.country import active_profile
except Exception:
    active_profile = None


class SettingsPage(QWidget):
    TITLE = "Settings"

    def __init__(self, store_engine, store_sales, parent=None):
        super().__init__(parent)
        self.se = store_engine
        self.ss = store_sales
        self._build()
        self.refresh()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)
        title = QLabel(self.TITLE); title.setObjectName("page_title"); root.addWidget(title)

        # ── store profile ─────────────────────────────────────────────────────
        prof = QFrame(); prof.setStyleSheet(
            f"QFrame{{background:{THEME['bg_hover']};border:1px solid {THEME['border']};border-radius:12px;}}")
        pf = QFormLayout(prof); pf.setContentsMargins(18, 14, 18, 14)
        self._co = QLabel("—"); self._country = QLabel("—"); self._cur = QLabel("—")
        for w in (self._co, self._country, self._cur):
            w.setStyleSheet("background:transparent; border:none;")
        pf.addRow(make_label("Company / store"), self._co)
        pf.addRow(make_label("Country profile"), self._country)
        pf.addRow(make_label("Currency"), self._cur)
        root.addWidget(prof)

        # ── tax ────────────────────────────────────────────────────────────────
        tax = QFrame(); tax.setStyleSheet(
            f"QFrame{{background:{THEME['bg_hover']};border:1px solid {THEME['border']};border-radius:12px;}}")
        tf = QFormLayout(tax); tf.setContentsMargins(18, 14, 18, 14)
        self._rate = QDoubleSpinBox(); self._rate.setRange(0, 100); self._rate.setDecimals(3)
        self._rate.setSuffix("  %")
        tf.addRow(make_label("Sales tax rate"), self._rate)
        save = QPushButton("Save tax rate"); save.setObjectName("btn_primary")
        save.clicked.connect(self._save_rate)
        srow = QHBoxLayout(); srow.addStretch(); srow.addWidget(save)
        tf.addRow(srow)
        root.addWidget(tax)

        # ── keyboard reference ──────────────────────────────────────────────────
        kb = QLabel(
            "<b>Keyboard</b><br>"
            "F2 — create &nbsp;·&nbsp; F3 — edit &nbsp;·&nbsp; Ctrl+Q — menu (tiles)<br>"
            "Counter: F2 invoice · F4 close day · Enter add to cart<br>"
            "Purchasing: F2 new PO · F3 receive · F6 suppliers · F9 direct GRN<br>"
            "Returns: F2 sale return · F9 purchase return · Ctrl+1…N jump to screen")
        kb.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px; padding:6px 2px;")
        root.addWidget(kb)
        root.addStretch()

    def refresh(self):
        row = self.se.tree.db.execute(
            "SELECT name, sales_tax_rate FROM companies WHERE id=?",
            (self.se.tree.company_id,)).fetchone()
        self._co.setText((row["name"] if row else "—") or "—")
        try:
            self._rate.setValue(float((row["sales_tax_rate"] if row else 0) or 0))
        except Exception:
            self._rate.setValue(0.0)
        prof_name = "—"; cur = "—"
        if active_profile:
            try:
                p = active_profile()
                prof_name = getattr(p, "name", getattr(p, "code", "—"))
                cur = getattr(p, "currency_symbol", "—")
            except Exception:
                pass
        self._country.setText(str(prof_name))
        self._cur.setText(str(cur))

    def _save_rate(self):
        try:
            self.se.tree.db.execute(
                "UPDATE companies SET sales_tax_rate=? WHERE id=?",
                (self._rate.value(), self.se.tree.company_id))
            self.se.tree.db.commit()
            # the sales engine caches no rate unless overridden; clear any override
            self.ss._rate = None
            QMessageBox.information(self, "Settings", "Sales tax rate saved.")
        except Exception as e:
            QMessageBox.critical(self, "Settings", str(e))
