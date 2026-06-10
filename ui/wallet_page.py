"""
AI Credits (wallet) page — surfaces the AI-credit balance that used to be
buried as one stat card inside License & Plan. Reached from its own menu tile
AND from the always-visible balance chip in the status bar.

Balance + usage come from ai.credit_manager.CreditManager (server is the source
of truth; refresh pulls the latest). Top-up opens the checkout site — the same
flow License & Plan uses.
"""
from __future__ import annotations

import webbrowser

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QSizePolicy,
    QDialog, QLineEdit, QApplication,
)

from ui.theme import THEME

CHECKOUT_URL = "https://apps.ai-consultants.in/checkout.html"


class WalletPage(QWidget):
    """Standalone AI-credits view: big balance, top-up, recent usage."""

    def __init__(self, license_mgr=None, parent=None):
        super().__init__(parent)
        self._lmgr = license_mgr
        outer = QVBoxLayout(self)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(16)

        title = QLabel("AI Wallet")
        title.setObjectName("page_title")
        outer.addWidget(title)
        sub = QLabel("Your AI credits power the document reader and the other "
                     "AI helpers that run on AccGenie's key.")
        sub.setObjectName("page_subtitle")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        # ── Balance card ──
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(24, 20, 24, 20)
        cl.setSpacing(8)

        cap = QLabel("AI CREDITS BALANCE")
        cap.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:11px; font-weight:bold;"
            " letter-spacing:1.2px;")
        cl.addWidget(cap)

        self._balance_lbl = QLabel("—")
        self._balance_lbl.setStyleSheet(
            f"color:{THEME['accent']}; font-size:34px; font-weight:800;")
        cl.addWidget(self._balance_lbl)

        btn_row = QHBoxLayout()
        topup = QPushButton("＋  Top up credits")
        topup.setObjectName("btn_primary")
        topup.setFixedHeight(36)
        topup.clicked.connect(self._open_topup)
        btn_row.addWidget(topup)

        refresh = QPushButton("⟳  Refresh")
        refresh.setFixedHeight(36)
        refresh.setStyleSheet(self._link_style())
        refresh.clicked.connect(self._refresh_balance)
        btn_row.addWidget(refresh)
        btn_row.addStretch()
        cl.addLayout(btn_row)
        outer.addWidget(card)

        # ── Usage log ──
        usage_lbl = QLabel("Recent AI usage")
        usage_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:13px; font-weight:bold;")
        outer.addWidget(usage_lbl)

        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["When", "Feature", "Cost"])
        self._table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        outer.addWidget(self._table, 1)

        self.refresh()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _cm(self):
        from ai.credit_manager import CreditManager
        return CreditManager()

    def refresh(self) -> None:
        """Called on every navigation to this page (MainWindow._select_page)."""
        try:
            self._balance_lbl.setText(self._cm().balance_display)
        except Exception:
            self._balance_lbl.setText("—")
        self._fill_usage()

    def _refresh_balance(self) -> None:
        try:
            self._cm().refresh_from_server()
        except Exception:
            pass
        self.refresh()

    def _fill_usage(self) -> None:
        try:
            rows = self._cm().get_usage_log() or []
        except Exception:
            rows = []
        rows = rows[-100:][::-1]   # most recent first, cap 100
        self._table.setRowCount(len(rows))
        for r, item in enumerate(rows):
            when = str(item.get("at", "") or item.get("when", "") or "")[:16]
            feat = str(item.get("feature", "") or item.get("kind", "") or "")
            cost = item.get("paise", item.get("cost", None))
            cost_s = f"₹ {cost/100:,.2f}" if isinstance(cost, (int, float)) else ""
            self._table.setItem(r, 0, QTableWidgetItem(when))
            self._table.setItem(r, 1, QTableWidgetItem(feat))
            ci = QTableWidgetItem(cost_s)
            ci.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(r, 2, ci)

    def _open_topup(self) -> None:
        TopUpDialog(self).exec()
        # The user may have paid in the browser — pull the latest balance.
        self._refresh_balance()

    def _go_license(self) -> None:
        win = self.window()
        if hasattr(win, "select_page_by_label"):
            win.select_page_by_label("License & Plan")

    @staticmethod
    def _link_style() -> str:
        return f"""
            QPushButton {{
                background: transparent; color: {THEME['accent']};
                border: 1px solid {THEME['accent']}; border-radius: 7px;
                padding: 4px 14px; font-size: 12px; font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['accent']}; color: white; }}
        """


class TopUpDialog(QDialog):
    """Pick an amount (with a rough document estimate) and pay via Razorpay —
    straight to Razorpay's own page, no marketing checkout. Uses the server's
    /api/v1/wallet/topup/create-order + the /wallet/pay page; the webhook
    credits the wallet on success."""

    PER_DOC_PAISE = 500          # ~Rs.5 per page (conservative)
    PRESETS = [100, 500, 1000]   # rupees

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Top up AI credits")
        self.setMinimumWidth(420)
        self._amount = 500

        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 20)
        v.setSpacing(12)

        t = QLabel("Top up your AI wallet")
        t.setStyleSheet("font-size:16px; font-weight:bold;")
        v.addWidget(t)
        hint = QLabel("AI document reading runs on these credits — about "
                      "Rs.5 per page. Pay securely via Razorpay.")
        hint.setStyleSheet(f"color:{THEME['text_dim']}; font-size:11px;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        row = QHBoxLayout()
        self._chips: dict[int, QPushButton] = {}
        for amt in self.PRESETS:
            b = QPushButton(f"Rs.{amt}")
            b.setCheckable(True)
            b.setFixedHeight(40)
            b.clicked.connect(lambda _=False, a=amt: self._pick(a))
            self._chips[amt] = b
            row.addWidget(b)
        v.addLayout(row)

        crow = QHBoxLayout()
        crow.addWidget(QLabel("Or custom  Rs."))
        self._custom = QLineEdit()
        self._custom.setPlaceholderText("e.g. 750")
        self._custom.setFixedWidth(120)
        self._custom.textEdited.connect(self._custom_changed)
        crow.addWidget(self._custom)
        crow.addStretch()
        v.addLayout(crow)

        self._est = QLabel("")
        self._est.setStyleSheet(
            f"color:{THEME['accent']}; font-weight:bold; font-size:13px;")
        v.addWidget(self._est)

        self._pay = QPushButton("Pay with Razorpay  →")
        self._pay.setObjectName("btn_primary")
        self._pay.setFixedHeight(40)
        self._pay.clicked.connect(self._pay_now)
        v.addWidget(self._pay)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet("font-size:11px;")
        v.addWidget(self._status)

        self._pick(500)

    def _pick(self, amt: int) -> None:
        self._amount = amt
        self._custom.clear()
        for a, b in self._chips.items():
            b.setChecked(a == amt)
        self._update_est()

    def _custom_changed(self, txt: str) -> None:
        for b in self._chips.values():
            b.setChecked(False)
        try:
            self._amount = max(0, int(txt or 0))
        except ValueError:
            self._amount = 0
        self._update_est()

    def _update_est(self) -> None:
        docs = (self._amount * 100) // self.PER_DOC_PAISE
        self._est.setText(f"≈ {docs} documents" if docs > 0 else "")
        self._pay.setEnabled(self._amount >= 1)

    def _pay_now(self) -> None:
        if self._amount < 1:
            return
        self._status.setText("Creating a secure order…")
        self._pay.setEnabled(False)
        QApplication.processEvents()
        try:
            import json
            import urllib.request
            from urllib.parse import urlencode
            from core.license_manager import SERVER_URL
            from ai.credit_manager import CreditManager

            key = CreditManager().license_key
            if not key:
                self._status.setText(
                    "No licence key found — open License & Plan first.")
                self._pay.setEnabled(True)
                return
            # SERVER_URL already ends in /api/v1 (e.g. https://host/api/v1).
            # The create-order endpoint lives under that; the /wallet/pay page
            # lives at the host root, so derive both bases from it.
            base = SERVER_URL.rstrip("/")
            host_root = base[:-len("/api/v1")] if base.endswith("/api/v1") else base
            payload = json.dumps(
                {"license_key": key, "amount_paise": self._amount * 100}).encode()
            req = urllib.request.Request(
                f"{base}/wallet/topup/create-order",
                data=payload, headers={"Content-Type": "application/json"},
                method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
            if not data.get("ok"):
                self._status.setText(
                    "Could not start payment: " + str(data.get("error", "")))
                self._pay.setEnabled(True)
                return
            pay_url = f"{host_root}/wallet/pay?" + urlencode({
                "order_id": data["order_id"],
                "key": data.get("razorpay_key_id", ""),
                "amount": data.get("amount_paise", self._amount * 100),
            })
            webbrowser.open(pay_url)
            self._status.setText(
                "Razorpay opened in your browser. After paying, close it and "
                "click Refresh — your new balance will appear.")
        except Exception as e:
            self._status.setText(f"Payment error: {e}")
            self._pay.setEnabled(True)
