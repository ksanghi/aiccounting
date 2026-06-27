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
    try:
        from core.i18n import currency_symbol, display_locale
        sym = currency_symbol()
        indian = display_locale() == "IN"
    except Exception:
        sym, indian = "₹", True
    sign = "-" if amount < 0 else ""
    n = abs(int(round(amount)))
    if indian:
        # Indian lakh/crore abbreviation
        if n >= 10_000_000:
            return f"{sign}{sym} {n / 10_000_000:.2f} Cr"
        if n >= 100_000:
            return f"{sign}{sym} {n / 100_000:.2f} L"
        return f"{sign}{sym} {n:,}"
    # Western K/M/B abbreviation
    if n >= 1_000_000_000:
        return f"{sign}{sym} {n / 1_000_000_000:.2f} B"
    if n >= 1_000_000:
        return f"{sign}{sym} {n / 1_000_000:.2f} M"
    if n >= 1_000:
        return f"{sign}{sym} {n / 1_000:.2f} K"
    return f"{sign}{sym} {n:,}"


class HomePage(QWidget):
    """Accounting dashboard. Constructed as HomePage(db, company_id, tree)."""

    def __init__(self, db, company_id, tree, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.tree = tree
        self._build()

    # ── navigation ──────────────────────────────────────────────────────
    def _go(self, target) -> None:
        """Navigate to a page by label. `target` may be a single label or a
        list of fallbacks — the first one that's actually registered wins.
        (Report pages register individually — "P & L", "Receivables Aging" —
        when licensed, or as one "Reports" hub when not, so a single hard-coded
        target would be dead on some tiers.)"""
        mw = self.window()
        if not hasattr(mw, "select_page_by_label"):
            return
        targets = [target] if isinstance(target, str) else list(target)
        for label in targets:
            try:
                if mw.select_page_by_label(label):
                    return
            except Exception:
                pass

    def _section_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setObjectName("nav_section")
        lbl.setStyleSheet(
            f"font-size:10px; font-weight:bold; letter-spacing:1px; "
            f"color:{THEME['text_secondary']}; margin-top:8px;")
        return lbl

    # ── layout scaffold (built once) ────────────────────────────────────
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        # Never scroll sideways — force the content to the viewport width so a
        # long narration (or any wide child) can't push the dashboard off-screen.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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

        # Income & Expense (left) and Needs attention (right), side by side so
        # the screen fills out. Each half is a label stacked over its content.
        two_col = QHBoxLayout()
        two_col.setSpacing(20)

        # ── Left: Income & Expense — calendar-month comparison (this month ·
        # same month last year · last month). Ledger figures + ▲/▼, no chart.
        left = QVBoxLayout()
        left.setSpacing(8)
        left.addWidget(self._section_label("INCOME & EXPENSE"))
        self._cmp_grid = QGridLayout()
        self._cmp_grid.setHorizontalSpacing(26)
        self._cmp_grid.setVerticalSpacing(9)
        cmp_host = QFrame()
        cmp_host.setObjectName("bento_tile")
        cmp_host.setLayout(self._cmp_grid)
        cmp_host.setContentsMargins(16, 12, 16, 12)
        left.addWidget(cmp_host)
        left.addStretch()

        # ── Right: Needs attention — risk flags derived from the ledgers; each
        # row only appears when triggered, else a single "all clear" line.
        right = QVBoxLayout()
        right.setSpacing(8)
        right.addWidget(self._section_label("NEEDS ATTENTION"))
        self._risk_box = QVBoxLayout()
        self._risk_box.setSpacing(6)
        risk_host = QWidget()
        risk_host.setLayout(self._risk_box)
        right.addWidget(risk_host)
        right.addStretch()

        two_col.addLayout(left, 1)
        two_col.addLayout(right, 1)
        root.addLayout(two_col)

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

    # ── period comparison (calendar months, MTD-aligned) ────────────────
    def _month_ranges(self):
        """Three (start, end) ISO pairs aligned to the same day-of-month so the
        comparison is like-for-like: this month-to-date · same month last year
        to the same day · last month to the same day."""
        import calendar
        today = date.today()
        d = today.day

        def md(year, month):
            last = calendar.monthrange(year, month)[1]
            return (date(year, month, 1).isoformat(),
                    date(year, month, min(d, last)).isoformat())

        cur = (today.replace(day=1).isoformat(), today.isoformat())
        lm_year, lm_month = (today.year - 1, 12) if today.month == 1 \
            else (today.year, today.month - 1)
        return cur, md(lm_year, lm_month), md(today.year - 1, today.month)

    def _income_expense(self, start_iso: str, end_iso: str):
        """(income, expense) over a date range — same nature rules as the
        Net-this-month KPI, just split and parameterised."""
        try:
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
                (self.company_id, start_iso, end_iso),
            ).fetchone()
            return float(row["inc"] or 0.0), float(row["exp"] or 0.0)
        except Exception:
            return 0.0, 0.0

    # ── risk flags ──────────────────────────────────────────────────────
    def _overdrawn_accounts(self) -> list[tuple[str, float]]:
        """Cash/bank ledgers whose net balance has gone negative."""
        out = []
        try:
            rows = self.tree.get_bank_cash_ledgers()
            bals = self.tree.get_all_ledger_balances()
            for r in rows:
                b = bals.get(r["id"])
                if not b:
                    continue
                net = b["balance"] if b["type"] == "Dr" else -b["balance"]
                if net < -0.01:
                    name = r["name"] if "name" in r.keys() else "Account"
                    out.append((name, net))
        except Exception:
            pass
        return out

    def _risk_flags(self) -> list[tuple[str, str, list]]:
        """(severity, text, deep-dive target list) for every triggered risk.
        severity ∈ good/warn/bad; target list is passed to `_go` (first
        registered label wins)."""
        flags: list[tuple[str, str, list]] = []
        today = date.today().isoformat()

        # 1. Spending > income, current month → P&L.
        cur, _lm, _ly = self._month_ranges()
        inc, exp = self._income_expense(cur[0], cur[1])
        if exp > inc + 0.01:
            flags.append(("bad",
                f"Spending is ahead of income this month by {_fmt_money(exp - inc)}",
                ["P & L", "Reports", "Trial Balance"]))

        # 2. Overdrawn cash / bank → the cash/bank balances.
        for name, net in self._overdrawn_accounts():
            flags.append(("bad", f"{name} is overdrawn ({_fmt_money(net)})",
                ["Ledger Balances", "Bank Book", "Cash Book"]))

        # 3 & 4. Receivables / payables overdue past 90 days (FIFO aging — works
        # on balance-based books, no bill-wise tracking required).
        try:
            from core.reports_engine import ReportsEngine
            re = ReportsEngine(self.db, self.company_id)
            rec = re.receivables_aging(today)
            r90 = rec.get("totals", {}).get("b90p", 0.0)
            if r90 > 0.01:
                top = rec["rows"][0]["ledger"] if rec.get("rows") else ""
                tail = f" — {top} the largest" if top else ""
                flags.append(("warn",
                    f"{_fmt_money(r90)} receivable overdue beyond 90 days{tail}",
                    ["Receivables Aging", "Reports"]))
            pay = re.payables_aging(today)
            p90 = pay.get("totals", {}).get("b90p", 0.0)
            if p90 > 0.01:
                top = pay["rows"][0]["ledger"] if pay.get("rows") else ""
                tail = f" — {top} the largest" if top else ""
                flags.append(("warn",
                    f"{_fmt_money(p90)} payable overdue beyond 90 days{tail}",
                    ["Payables Aging", "Reports"]))
        except Exception:
            pass

        return flags

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
            ("Cash & Bank",    cash, "good" if cash >= 0 else "bad",
             ["Ledger Balances"]),
            ("Receivables",    recv, "warn" if recv > 0 else "good",
             ["Receivables Aging", "Reports"]),
            ("Payables",       pay,  "warn" if pay  > 0 else "good",
             ["Payables Aging", "Reports"]),
            ("Net this month", net,  "good" if net  >= 0 else "bad",
             ["P & L", "Reports", "Trial Balance"]),
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
            # Equal stretch on each column so the 4 tiles spread the full width.
            self._kpi_grid.setColumnStretch(col, 1)

        # Income & Expense comparison -------------------------------------
        self._render_comparison()

        # Needs attention (risk flags) ------------------------------------
        self._render_risks()

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
            ("Reports",        "Trial balance, P&L and more", "📊",
             ["P & L", "Reports", "Trial Balance"]),
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
            # All four in a single row, spread evenly across the full width.
            self._qa_grid.addWidget(card, 0, i)
            self._qa_grid.setColumnStretch(i, 1)

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
        # Ignored (not Expanding) so a long narration takes only the leftover
        # space and clips, instead of forcing the whole dashboard wider.
        narr.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

        amt = QLabel(_fmt_money(v.get("total_amount") or 0))
        amt.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        amt.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px; font-weight:600;")

        lay.addWidget(when)
        lay.addWidget(ref)
        lay.addWidget(narr, 1)
        lay.addWidget(amt)
        return row

    # ── Income & Expense comparison render ──────────────────────────────
    def _render_comparison(self) -> None:
        self._clear(self._cmp_grid)
        cur, lm, ly = self._month_ranges()
        inc_c, exp_c = self._income_expense(*cur)
        inc_l, exp_l = self._income_expense(*lm)
        inc_y, exp_y = self._income_expense(*ly)
        net_c, net_l, net_y = inc_c - exp_c, inc_l - exp_l, inc_y - exp_y

        def hdr(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px; "
                            "font-weight:700; letter-spacing:0.5px;")
            l.setAlignment(Qt.AlignmentFlag.AlignRight)
            return l

        def row_label(text: str) -> QLabel:
            l = QLabel(text)
            l.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px; "
                            "font-weight:600;")
            return l

        def delta_html(now: float, base: float, higher_is_good: bool) -> str:
            if abs(base) < 0.01:
                return ""
            pct = (now - base) / abs(base) * 100.0
            up = pct >= 0
            good = up if higher_is_good else (not up)
            col = THEME["good"] if good else THEME["bad"]
            arrow = "▲" if up else "▼"
            return (f" <span style='color:{col}; font-size:11px'>"
                    f"{arrow}{abs(pct):.0f}%</span>")

        def cell(value: float, now: float | None = None,
                 higher_is_good: bool = True, bold: bool = True) -> QLabel:
            weight = "700" if bold else "500"
            html = f"<span style='font-weight:{weight}'>{_fmt_money(value)}</span>"
            if now is not None:
                html += delta_html(now, value, higher_is_good)
            l = QLabel(html)
            l.setTextFormat(Qt.TextFormat.RichText)
            l.setStyleSheet(f"color:{THEME['text_primary']}; font-size:13px;")
            l.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            return l

        self._cmp_grid.addWidget(hdr(""),                    0, 0)
        self._cmp_grid.addWidget(hdr("THIS MONTH"),          0, 1)
        self._cmp_grid.addWidget(hdr("SAME MONTH LAST YEAR"), 0, 2)
        self._cmp_grid.addWidget(hdr("LAST MONTH"),          0, 3)

        # (name, current, last-year, last-month, higher_is_good)
        rows = [
            ("Income",   inc_c, inc_y, inc_l, True),
            ("Expenses", exp_c, exp_y, exp_l, False),
            ("Net",      net_c, net_y, net_l, True),
        ]
        for ri, (name, c, y, l, hig) in enumerate(rows, start=1):
            self._cmp_grid.addWidget(row_label(name), ri, 0)
            self._cmp_grid.addWidget(cell(c),                 ri, 1)
            self._cmp_grid.addWidget(cell(y, c, hig),         ri, 2)
            self._cmp_grid.addWidget(cell(l, c, hig),         ri, 3)
        self._cmp_grid.setColumnStretch(0, 0)
        for cstretch in (1, 2, 3):
            self._cmp_grid.setColumnStretch(cstretch, 1)

    # ── Risk flags render ───────────────────────────────────────────────
    def _render_risks(self) -> None:
        self._clear(self._risk_box)
        flags = self._risk_flags()
        if not flags:
            self._risk_box.addWidget(self._risk_row(
                "good", "Nothing needs attention — the books look healthy."))
            return
        for severity, text, target in flags:
            self._risk_box.addWidget(self._risk_row(severity, text, target))

    def _risk_row(self, severity: str, text: str, target=None) -> QWidget:
        sev = severity if severity in ("good", "warn", "bad") else "warn"
        icon = "✓" if sev == "good" else "⚠"
        col = THEME[sev]
        w = QFrame()
        w.setObjectName("risk_row")
        # When the row links to a report, give it a hover cue + chevron.
        hover = (f"#risk_row:hover {{ border:1px solid {col}; "
                 f"border-left:3px solid {col}; }}") if target else ""
        w.setStyleSheet(
            f"#risk_row {{ background:{THEME['bg_hover']}; "
            f"border:1px solid {THEME['border']}; border-left:3px solid {col}; "
            f"border-radius:8px; }} {hover}")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)
        ic = QLabel(icon)
        ic.setFixedWidth(18)
        ic.setStyleSheet(f"color:{col}; font-size:14px; font-weight:700; "
                         "background:transparent; border:none;")
        lay.addWidget(ic)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12.5px; "
                          "background:transparent; border:none;")
        lay.addWidget(lbl, 1)
        if target:
            chev = QLabel("›")
            chev.setStyleSheet(f"color:{THEME['text_dim']}; font-size:16px; "
                               "font-weight:700; background:transparent; border:none;")
            lay.addWidget(chev)
            w.setCursor(Qt.CursorShape.PointingHandCursor)
            # Left-click anywhere on the row jumps to the relevant report.
            w.mousePressEvent = lambda ev, t=target: (
                self._go(t) if ev.button() == Qt.MouseButton.LeftButton else None)
        return w
