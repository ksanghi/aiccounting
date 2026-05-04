"""
License page UI — key entry, plan status, usage meter, upgrade nudge.
"""
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit,
    QFrame, QProgressBar, QMessageBox,
    QGridLayout,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal

from ui.theme import THEME
from core.license_manager import (
    LicenseManager, PLAN_PRICES, PLAN_LIMITS, PLAN_FEATURES,
)

UPGRADE_URL = "https://aiccounting.in/upgrade"


class ValidateThread(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, mgr: LicenseManager, key: str):
        super().__init__()
        self.mgr = mgr
        self.key = key

    def run(self):
        ok, msg = self.mgr.validate_with_server(self.key)
        self.finished.emit(ok, msg)


class LicensePage(QWidget):

    plan_changed = pyqtSignal(str)

    def __init__(self, license_mgr: LicenseManager, parent=None):
        super().__init__(parent)
        self._mgr    = license_mgr
        self._thread = None
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)

        title = QLabel("License & Plan")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel("Manage your subscription and view usage")
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # ── Current plan card ──
        plan_card = QFrame()
        plan_card.setObjectName("card")
        pc = QVBoxLayout(plan_card)
        pc.setContentsMargins(20, 16, 20, 16)
        pc.setSpacing(12)

        top_row = QHBoxLayout()
        self._plan_badge = QLabel("FREE")
        self._plan_badge.setFixedHeight(28)
        top_row.addWidget(self._plan_badge)
        top_row.addStretch()
        self._expiry_lbl = QLabel("")
        self._expiry_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        top_row.addWidget(self._expiry_lbl)
        pc.addLayout(top_row)

        # Stats grid
        stats = QGridLayout()
        stats.setSpacing(10)

        def _stat(label: str):
            w = QWidget()
            w.setStyleSheet(
                f"background:{THEME['bg_input']}; border-radius:8px;"
            )
            inner = QVBoxLayout(w)
            inner.setContentsMargins(12, 8, 12, 8)
            inner.setSpacing(2)
            lbl = QLabel(label)
            lbl.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:10px;"
                f" font-weight:bold; letter-spacing:0.5px;"
            )
            val = QLabel("—")
            val.setStyleSheet(
                f"font-size:16px; font-weight:500; color:{THEME['text_primary']};"
            )
            inner.addWidget(lbl)
            inner.addWidget(val)
            return w, val

        w1, self._txn_used_lbl  = _stat("TRANSACTIONS USED")
        w2, self._txn_limit_lbl = _stat("PLAN LIMIT")
        w3, self._overage_lbl   = _stat("OVERAGE COST")
        w4, self._users_lbl     = _stat("USERS ALLOWED")
        for col, w in enumerate([w1, w2, w3, w4]):
            stats.addWidget(w, 0, col)
        pc.addLayout(stats)

        usage_lbl = QLabel("Transaction usage")
        usage_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        pc.addWidget(usage_lbl)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setFixedHeight(8)
        self._progress.setTextVisible(False)
        pc.addWidget(self._progress)

        self._usage_detail = QLabel("")
        self._usage_detail.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px;"
        )
        pc.addWidget(self._usage_detail)
        layout.addWidget(plan_card)

        # ── Upgrade nudge ──
        self._nudge_frame = QFrame()
        self._nudge_frame.setObjectName("card")
        self._nudge_frame.setVisible(False)
        nf = QHBoxLayout(self._nudge_frame)
        nf.setContentsMargins(16, 12, 16, 12)
        self._nudge_lbl = QLabel("")
        self._nudge_lbl.setWordWrap(True)
        self._nudge_lbl.setStyleSheet(
            f"color:{THEME['warning']}; font-size:12px;"
        )
        nudge_btn = QPushButton("Upgrade now")
        nudge_btn.setObjectName("btn_primary")
        nudge_btn.setFixedHeight(32)
        nudge_btn.setFixedWidth(130)
        nudge_btn.clicked.connect(self._upgrade)
        nf.addWidget(self._nudge_lbl, 1)
        nf.addWidget(nudge_btn)
        layout.addWidget(self._nudge_frame)

        # ── License key entry ──
        key_frame = QFrame()
        key_frame.setObjectName("card")
        kf = QVBoxLayout(key_frame)
        kf.setContentsMargins(20, 16, 20, 16)
        kf.setSpacing(10)
        kf.addWidget(QLabel("License key"))

        key_row = QHBoxLayout()
        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText("AICC-XXXX-XXXX-XXXX")
        self._key_edit.setFixedHeight(34)
        current_key = self._mgr.license_key
        if current_key and current_key != "FREE-DEMO":
            self._key_edit.setText(current_key)
        self._key_edit.returnPressed.connect(self._activate)

        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setObjectName("btn_primary")
        self._activate_btn.setFixedHeight(34)
        self._activate_btn.setFixedWidth(100)
        self._activate_btn.clicked.connect(self._activate)
        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(self._activate_btn)
        kf.addLayout(key_row)

        self._key_status = QLabel("")
        self._key_status.setStyleSheet("font-size:11px;")
        kf.addWidget(self._key_status)
        layout.addWidget(key_frame)

        # ── Plan comparison ──
        plans_frame = QFrame()
        plans_frame.setObjectName("card")
        pf = QVBoxLayout(plans_frame)
        pf.setContentsMargins(20, 16, 20, 16)
        pf.setSpacing(10)
        pf.addWidget(QLabel("Available plans"))

        plan_grid = QGridLayout()
        plan_grid.setSpacing(8)
        plan_defs = [
            ("FREE",     "Free",     "Rs.0/yr",       "5,000 txn",   "Basic features"),
            ("STANDARD", "Standard", "Rs.1,999/yr",   "20,000 txn",  "Reports + backup"),
            ("PRO",      "Pro",      "Rs.4,999/yr",   "50,000 txn",  "GST + TDS + AI"),
            ("PREMIUM",  "Premium",  "Rs.9,999/yr",   "Unlimited",   "All features"),
        ]
        for col, (key, name, price, limit, desc) in enumerate(plan_defs):
            is_current = (key == self._mgr.plan)
            w = QWidget()
            w.setStyleSheet(f"""
                background:{THEME['accent_dim'] if is_current else THEME['bg_input']};
                border-radius:8px;
                border:{'1.5px solid ' + THEME['accent']
                        if is_current
                        else '0.5px solid ' + THEME['border']};
                padding:10px;
            """)
            inner = QVBoxLayout(w)
            inner.setSpacing(3)
            inner.setContentsMargins(8, 8, 8, 8)

            n_lbl = QLabel(name)
            n_lbl.setStyleSheet(
                f"font-size:12px; font-weight:bold;"
                f"color:{THEME['accent'] if is_current else THEME['text_primary']};"
            )
            p_lbl = QLabel(price)
            p_lbl.setStyleSheet(
                f"font-size:13px; font-weight:500; color:{THEME['text_primary']};"
            )
            l_lbl = QLabel(limit)
            l_lbl.setStyleSheet(
                f"font-size:10px; color:{THEME['success']};"
            )
            d_lbl = QLabel(desc)
            d_lbl.setStyleSheet(
                f"font-size:10px; color:{THEME['text_secondary']};"
            )
            inner.addWidget(n_lbl)
            inner.addWidget(p_lbl)
            inner.addWidget(l_lbl)
            inner.addWidget(d_lbl)

            if is_current:
                cur = QLabel("Current plan")
                cur.setStyleSheet(
                    f"font-size:10px; color:{THEME['accent']}; font-weight:bold;"
                )
                inner.addWidget(cur)
            else:
                up_btn = QPushButton("Upgrade")
                up_btn.setFixedHeight(26)
                up_btn.setStyleSheet("font-size:10px; padding:2px;")
                up_btn.clicked.connect(self._upgrade)
                inner.addWidget(up_btn)

            plan_grid.addWidget(w, 0, col)
        pf.addLayout(plan_grid)

        buy_lbl = QLabel(
            "Purchase at aiccounting.in/pricing  "
            "— Razorpay · UPI · Cards · NetBanking"
        )
        buy_lbl.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px;"
        )
        pf.addWidget(buy_lbl)
        layout.addWidget(plans_frame)
        layout.addStretch()

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh(self):
        s    = self._mgr.status_summary()
        plan = s["plan"]

        badge_colours = {
            "FREE":     (THEME["text_secondary"], THEME["bg_hover"]),
            "STANDARD": (THEME["accent"],         THEME["accent_dim"]),
            "PRO":      (THEME["success"],         "#0A2A0A"),
            "PREMIUM":  (THEME["warning"],         "#2A1A00"),
        }
        fc, bc = badge_colours.get(plan, (THEME["accent"], THEME["accent_dim"]))
        self._plan_badge.setText(plan)
        self._plan_badge.setStyleSheet(f"""
            background:{bc}; color:{fc};
            border:1px solid {fc}; border-radius:5px;
            padding:3px 12px; font-size:13px; font-weight:bold;
        """)

        days = s["days_to_expiry"]
        if s["is_expired"]:
            self._expiry_lbl.setText("EXPIRED — renew now")
            self._expiry_lbl.setStyleSheet(
                f"color:{THEME['danger']}; font-size:11px; font-weight:bold;"
            )
        elif days <= 30:
            self._expiry_lbl.setText(f"Expires in {days} days")
            self._expiry_lbl.setStyleSheet(
                f"color:{THEME['warning']}; font-size:11px;"
            )
        else:
            self._expiry_lbl.setText(f"Valid until {s['expires_at']}")
            self._expiry_lbl.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:11px;"
            )

        self._txn_used_lbl.setText(f"{s['txn_used']:,}")
        self._txn_limit_lbl.setText(
            "Unlimited" if plan == "PREMIUM" else f"{s['txn_limit']:,}"
        )

        if s["overage_count"] > 0:
            self._overage_lbl.setText(f"Rs.{s['overage_cost']:.2f}")
            self._overage_lbl.setStyleSheet(
                f"font-size:16px; font-weight:500; color:{THEME['warning']};"
            )
        else:
            self._overage_lbl.setText("Rs.0.00")
            self._overage_lbl.setStyleSheet(
                f"font-size:16px; font-weight:500; color:{THEME['success']};"
            )

        ul = self._mgr.user_limit
        self._users_lbl.setText("Unlimited" if ul >= 999 else str(ul))

        pct = int(s["txn_pct"])
        self._progress.setValue(pct)
        colour = (THEME["danger"] if pct >= 100
                  else THEME["warning"] if pct >= 80
                  else THEME["success"])
        self._progress.setStyleSheet(f"""
            QProgressBar {{
                background:{THEME['bg_input']}; border-radius:4px; border:none;
            }}
            QProgressBar::chunk {{
                background:{colour}; border-radius:4px;
            }}
        """)

        used      = s["txn_used"]
        limit     = s["txn_limit"]
        remaining = max(0, limit - used)
        if plan == "PREMIUM":
            detail = f"{used:,} transactions used this year"
        elif used > limit:
            overage = used - limit
            rate    = 0.20 if plan == "PREMIUM" else 0.30
            detail  = (
                f"{used:,} used of {limit:,} — "
                f"{overage:,} over limit "
                f"(Rs.{overage * rate:.2f} overage)"
            )
        else:
            detail = f"{used:,} used of {limit:,} — {remaining:,} remaining"
        self._usage_detail.setText(detail)

        nudge = self._mgr.upgrade_savings()
        if nudge:
            self._nudge_frame.setVisible(True)
            self._nudge_lbl.setText(
                f"You have {nudge['overage_txn']:,} overage transactions costing "
                f"Rs.{nudge['overage_cost']:.2f}. "
                f"Upgrading to {nudge['next_plan']} would save "
                f"Rs.{nudge['would_save']:.2f}."
            )
        else:
            self._nudge_frame.setVisible(False)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _activate(self):
        key = self._key_edit.text().strip().upper()
        if not key:
            self._set_key_status("Please enter a license key.", error=True)
            return

        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Checking…")
        self._set_key_status("Contacting license server…", error=False)

        self._thread = ValidateThread(self._mgr, key)
        self._thread.finished.connect(self._on_validate)
        self._thread.start()

    def _on_validate(self, ok: bool, msg: str):
        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Activate")

        if ok:
            self._set_key_status(f"✓  {msg}", error=False, success=True)
            self.refresh()
            self.plan_changed.emit(self._mgr.plan)
            QMessageBox.information(
                self, "Activated",
                f"License activated!\n"
                f"Plan: {self._mgr.plan}\n"
                f"Expires: {self._mgr.expires_at}",
            )
        else:
            self._set_key_status(f"✗  {msg}", error=True)

    def _upgrade(self):
        webbrowser.open(UPGRADE_URL)

    def _set_key_status(self, msg: str, error: bool = False, success: bool = False):
        colour = (THEME["danger"] if error
                  else THEME["success"] if success
                  else THEME["text_secondary"])
        weight = "bold" if success else "normal"
        self._key_status.setText(msg)
        self._key_status.setStyleSheet(
            f"color:{colour}; font-size:11px; font-weight:{weight};"
        )
