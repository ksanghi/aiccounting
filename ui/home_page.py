"""
Home / Dashboard — the accounting landing surface when Accounts HQ opens.

Top-to-bottom:
  1. Header        — company name + product + today's date.
  2. Bento KPI strip — Cash & Bank / Receivables / Payables / Net this month.
                       Tiles are clickable → jump to the relevant page.
  3. Recent activity — the last 8 (non-cancelled) vouchers.
  4. Quick actions — Post Voucher / Day Book / Reports / Document Inbox.

Every query is wrapped in try/except so a fresh company or a missing table
renders a zero/empty card instead of crashing the dashboard. Navigation goes
through main_window.select_page_by_label(...).

This is the AHQ base Home; RWA HQ keeps its own society-specific HomePage.
"""
from __future__ import annotations

from datetime import date

from PySide6.QtCore    import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame,
    QScrollArea, QSizePolicy,
)

from core import branding
from ui.theme import THEME

try:
    from ui.bento_widgets import KPITile, ActionCard
except Exception:                       # pragma: no cover - defensive
    KPITile = ActionCard = None


def _fmt_money(amount: float) -> str:
    sign = "-" if amount < 0 else ""
    n = abs(int(round(amount)))
    if n >= 10_000_000:
        return f"{sign}₹ {n / 10_000_000:.2f} Cr"
    if n >= 100_000:
        return f"{sign}₹ {n / 100_000:.2f} L"
    return f"{sign}₹ {n:,}"


class HomePage(QWidget):
    """Accounting dashboard. Constructed as HomePage(db, company_id, tree)."""

    def __init__(self, db, company_id, tree, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.tree = tree
        self._build()

    # ── navigation ──────────────────────────────────────────────────────
    def _go(self, label: str) -> None:
        mw = self.window()
        if hasattr(mw, "select_page_by_label"):
            try:
                mw.select_page_by_label(label)
            except Exception:
                pass

    # ── layout scaffold (built once) ────────────────────────────────────
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        host = QWidget()
        root = QVBoxLayout(host)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)

        self._title = QLabel()
        self._title.setObjectName("page_title")
        self._title.setStyleSheet(
            f"font-size:22px; font-weight:800; color:{THEME['text_primary']};")
        self._sub = QLabel()
        self._sub.setStyleSheet(
            f"font-size:12px; color:{THEME['text_secondary']};")
        root.addWidget(self._title)
        root.addWidget(self._sub)

        self._kpi_grid = QGridLayout()
        self._kpi_grid.setSpacing(14)
        root.addLayout(self._kpi_grid)

        rec_lbl = QLabel("RECENT ACTIVITY")
        rec_lbl.setObjectName("nav_section")
        rec_lbl.setStyleSheet(
            f"font-size:10px; font-weight:bold; letter-spacing:1px; "
            f"color:{THEME['text_secondary']}; margin-top:8px;")
        root.addWidget(rec_lbl)
        self._recent_box = QVBoxLayout()
        self._recent_box.setSpacing(0)
        rec_host = QWidget()
        rec_host.setLayout(self._recent_box)
        root.addWidget(rec_host)

        qa_lbl = QLabel("QUICK ACTIONS")
        qa_lbl.setObjectName("nav_section")
        qa_lbl.setStyleSheet(
            f"font-size:10px; font-weight:bold; letter-spacing:1px; "
            f"color:{THEME['text_secondary']}; margin-top:8px;")
        root.addWidget(qa_lbl)
        self._qa_grid = QGridLayout()
        self._qa_grid.setSpacing(14)
        root.addLayout(self._qa_grid)

        root.addStretch()
        scroll.setWidget(host)
        outer.addWidget(scroll)

        self.refresh()

    # ── data ────────────────────────────────────────────────────────────
    def _company_name(self) -> str:
        try:
            row = self.db.execute(
                "SELECT name FROM companies WHERE id=?", (self.company_id,)
            ).fetchone()
            return row["name"] if row else "Company"
        except Exception:
            return "Company"

    def _cash_bank(self) -> float:
        try:
            ids = [r["id"] for r in self.tree.get_bank_cash_ledgers()]
            bals = self.tree.get_all_ledger_balances()
            total = 0.0
            for i in ids:
                b = bals.get(i)
                if b:
                    total += b["balance"] if b["type"] == "Dr" else -b["balance"]
            return total
        except Exception:
            return 0.0

    def _group_total(self, group_name: str, side: str) -> float:
        try:
            rows = self.db.execute(
                """SELECT l.id FROM ledgers l
                   JOIN account_groups g ON l.group_id = g.id
                   WHERE l.company_id = ? AND g.name = ?""",
                (self.company_id, group_name),
            ).fetchall()
            ids = [r["id"] for r in rows]
            bals = self.tree.get_all_ledger_balances()
            total = 0.0
            for i in ids:
                b = bals.get(i)
                if b:
                    total += b["balance"] if b["type"] == side else -b["balance"]
            return total
        except Exception:
            return 0.0

    def _net_this_month(self) -> float:
        try:
            ms = date.today().replace(day=1).isoformat()
            today = date.today().isoformat()
            row = self.db.execute(
                """SELECT
                     COALESCE(SUM(CASE WHEN g.nature='INCOME'
                       THEN vl.cr_amount - vl.dr_amount ELSE 0 END), 0) AS inc,
                     COALESCE(SUM(CASE WHEN g.nature='EXPENSE'
                       THEN vl.dr_amount - vl.cr_amount ELSE 0 END), 0) AS exp
                   FROM voucher_lines vl
                   JOIN vouchers v       ON vl.voucher_id = v.id
                   JOIN ledgers  l       ON vl.ledger_id  = l.id
                   JOIN account_groups g ON l.group_id    = g.id
                   WHERE v.company_id = ? AND v.is_cancelled = 0
                     AND v.voucher_date >= ? AND v.voucher_date <= ?""",
                (self.company_id, ms, today),
            ).fetchone()
            return round((row["inc"] or 0.0) - (row["exp"] or 0.0), 2)
        except Exception:
            return 0.0

    def _recent_vouchers(self) -> list[dict]:
        try:
            rows = self.db.execute(
                """SELECT voucher_date, voucher_type, voucher_number,
                          narration, total_amount
                   FROM vouchers
                   WHERE company_id = ? AND is_cancelled = 0
                   ORDER BY voucher_date DESC, id DESC
                   LIMIT 8""",
                (self.company_id,),
            ).fetchall()
            return [dict(r) for r in rows]
        except Exception:
            return []

    # ── render ──────────────────────────────────────────────────────────
    @staticmethod
    def _clear(layout) -> None:
        while layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)

    def refresh(self) -> None:
        self._title.setText(self._company_name())
        self._sub.setText(
            f"{branding.PRODUCT_NAME}  ·  {date.today().strftime('%A, %d %B %Y')}")

        # KPI tiles -------------------------------------------------------
        self._clear(self._kpi_grid)
        cash = self._cash_bank()
        recv = self._group_total("Sundry Debtors", "Dr")
        pay  = self._group_total("Sundry Creditors", "Cr")
        net  = self._net_this_month()
        kpis = [
            ("Cash & Bank",    cash, "good" if cash >= 0 else "bad",  "Ledger Balances"),
            ("Receivables",    recv, "warn" if recv > 0 else "good",  "Receivables Aging"),
            ("Payables",       pay,  "warn" if pay  > 0 else "good",  ""),
            ("Net this month", net,  "good" if net  >= 0 else "bad",  "Reports"),
        ]
        for col, (label, amount, status, target) in enumerate(kpis):
            if KPITile is not None:
                tile = KPITile(label, _fmt_money(amount), status=status)
                if target:
                    try:
                        tile.clicked.connect(lambda t=target: self._go(t))
                        tile.setCursor(Qt.CursorShape.PointingHandCursor)
                    except Exception:
                        pass
            else:
                tile = QLabel(f"{label}\n{_fmt_money(amount)}")
            self._kpi_grid.addWidget(tile, 0, col)

        # Recent activity -------------------------------------------------
        self._clear(self._recent_box)
        recent = self._recent_vouchers()
        if not recent:
            empty = QLabel("No vouchers yet — post your first entry to get started.")
            empty.setStyleSheet(f"color:{THEME['text_secondary']}; padding:10px 2px;")
            self._recent_box.addWidget(empty)
        else:
            for v in recent:
                self._recent_box.addWidget(self._activity_row(v))

        # Quick actions ---------------------------------------------------
        self._clear(self._qa_grid)
        actions = [
            ("Post Voucher",   "Record a new entry",          "✏", "Post Voucher"),
            ("Day Book",       "Browse all vouchers",         "📋", "Day Book"),
            ("Reports",        "Trial balance, P&L and more", "📊", "Reports"),
            ("Document Inbox", "AI-read incoming documents",  "📥", "Document Inbox"),
        ]
        for i, (title, sub, icon, target) in enumerate(actions):
            if ActionCard is not None:
                card = ActionCard(title, sub, icon=icon)
                try:
                    card.clicked.connect(lambda t=target: self._go(t))
                except Exception:
                    pass
            else:
                card = QLabel(f"{icon}  {title}")
                card.setCursor(Qt.CursorShape.PointingHandCursor)
            self._qa_grid.addWidget(card, i // 2, i % 2)

    def _activity_row(self, v: dict) -> QWidget:
        row = QFrame()
        row.setStyleSheet(
            f"QFrame {{ border-bottom:1px solid {THEME['border']}; }}")
        lay = QHBoxLayout(row)
        lay.setContentsMargins(2, 8, 2, 8)
        lay.setSpacing(10)

        when = QLabel(v.get("voucher_date") or "")
        when.setFixedWidth(92)
        when.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px;")

        ref = QLabel(f"{v.get('voucher_type','')}  {v.get('voucher_number','')}")
        ref.setFixedWidth(150)
        ref.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px; font-weight:600;")

        narr = QLabel((v.get("narration") or "").strip())
        narr.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px;")
        narr.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        amt = QLabel(_fmt_money(v.get("total_amount") or 0))
        amt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amt.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px; font-weight:600;")

        lay.addWidget(when)
        lay.addWidget(ref)
        lay.addWidget(narr, 1)
        lay.addWidget(amt)
        return row
