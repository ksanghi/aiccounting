"""
License page — clean rewrite with proper spacing
"""
import webbrowser
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QLineEdit,
    QFrame, QScrollArea, QMessageBox
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont

from ui.theme import THEME
from ui.widgets import make_separator
from core.license_manager import (
    LicenseManager, PLAN_PRICES, PLAN_LIMITS,
    PLAN_FEATURES
)

UPGRADE_URL = "https://accgenie.in/pricing"


class ValidateThread(QThread):
    finished = Signal(bool, str)

    def __init__(self, mgr, key):
        super().__init__()
        self.mgr = mgr
        self.key = key

    def run(self):
        ok, msg = self.mgr.validate_with_server(self.key)
        self.finished.emit(ok, msg)


def section_label(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"""
        font-size: 13px;
        font-weight: bold;
        color: {THEME['text_primary']};
        padding: 4px 0px 6px 0px;
    """)
    return lbl


def divider() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.Shape.HLine)
    f.setStyleSheet(
        f"color: {THEME['border']};"
        f"background: {THEME['border']};"
        f"border: none; max-height: 1px;"
    )
    return f


class LicensePage(QWidget):

    plan_changed = Signal(str)

    def __init__(self, license_mgr: LicenseManager, parent=None):
        super().__init__(parent)
        self._mgr = license_mgr
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 0, 24, 24)
        outer.setSpacing(0)

        title = QLabel("License & Plan")
        title.setObjectName("page_title")
        outer.addWidget(title)

        sub = QLabel("Manage your subscription and view usage")
        sub.setObjectName("page_subtitle")
        outer.addWidget(sub)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(16)

        # ── SECTION 1: Current plan status ──────────────────────────────────
        layout.addWidget(section_label("Current plan"))

        status_card = QFrame()
        status_card.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
                padding: 0px;
            }}
        """)
        sc = QVBoxLayout(status_card)
        sc.setContentsMargins(20, 16, 20, 16)
        sc.setSpacing(14)

        # Plan badge + expiry row
        top = QHBoxLayout()
        top.setSpacing(12)

        self._plan_badge = QLabel("FREE")
        self._plan_badge.setFixedHeight(32)
        self._plan_badge.setStyleSheet(f"""
            background: {THEME['accent_dim']};
            color: {THEME['accent']};
            border: 1px solid {THEME['accent']};
            border-radius: 6px;
            padding: 4px 16px;
            font-size: 14px;
            font-weight: bold;
        """)

        self._expiry_lbl = QLabel("")
        self._expiry_lbl.setStyleSheet(
            f"color: {THEME['text_secondary']}; font-size: 12px;"
        )

        top.addWidget(self._plan_badge)
        top.addStretch()
        top.addWidget(self._expiry_lbl)
        sc.addLayout(top)

        sc.addWidget(divider())

        # Stats row — 4 cards
        stats_row = QHBoxLayout()
        stats_row.setSpacing(10)

        def make_stat(label: str) -> QLabel:
            card = QFrame()
            card.setStyleSheet(f"""
                QFrame {{
                    background: {THEME['bg_input']};
                    border: 1px solid {THEME['border']};
                    border-radius: 8px;
                }}
            """)
            cl = QVBoxLayout(card)
            cl.setContentsMargins(14, 12, 14, 12)
            cl.setSpacing(6)

            lbl = QLabel(label)
            lbl.setStyleSheet(f"""
                color: {THEME['text_secondary']};
                font-size: 10px;
                font-weight: bold;
                letter-spacing: 0.8px;
                background: transparent;
                border: none;
                padding: 0px;
            """)

            val = QLabel("—")
            val.setStyleSheet(f"""
                color: {THEME['text_primary']};
                font-size: 20px;
                font-weight: 500;
                background: transparent;
                border: none;
                padding: 0px;
            """)

            cl.addWidget(lbl)
            cl.addWidget(val)
            stats_row.addWidget(card)
            return val

        self._txn_used_val  = make_stat("USED")
        self._txn_limit_val = make_stat("LIMIT")
        self._overage_val   = make_stat("OVERAGE")
        self._users_val     = make_stat("USERS")
        sc.addLayout(stats_row)

        sc.addWidget(divider())

        # Usage bar label
        bar_lbl = QLabel("Transaction usage this year")
        bar_lbl.setStyleSheet(
            f"color: {THEME['text_secondary']}; font-size: 11px; font-weight: bold;"
        )
        sc.addWidget(bar_lbl)

        # Custom bar using QFrame fill
        bar_bg = QFrame()
        bar_bg.setFixedHeight(12)
        bar_bg.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_input']};
                border-radius: 6px;
                border: 1px solid {THEME['border']};
            }}
        """)
        bar_layout = QHBoxLayout(bar_bg)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.setSpacing(0)

        self._bar_fill = QFrame()
        self._bar_fill.setFixedHeight(12)
        self._bar_fill.setStyleSheet(f"""
            QFrame {{
                background: {THEME['success']};
                border-radius: 6px;
                border: none;
            }}
        """)
        self._bar_fill.setFixedWidth(0)
        bar_layout.addWidget(self._bar_fill)
        bar_layout.addStretch()
        sc.addWidget(bar_bg)
        self._bar_bg = bar_bg

        self._usage_detail = QLabel("")
        self._usage_detail.setStyleSheet(
            f"color: {THEME['text_secondary']}; font-size: 11px;"
        )
        sc.addWidget(self._usage_detail)

        layout.addWidget(status_card)

        # ── Upgrade nudge ────────────────────────────────────────────────────
        self._nudge_frame = QFrame()
        self._nudge_frame.setVisible(False)
        self._nudge_frame.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['warning']};
                border-radius: 10px;
            }}
        """)
        nf = QHBoxLayout(self._nudge_frame)
        nf.setContentsMargins(16, 12, 16, 12)
        nf.setSpacing(12)

        self._nudge_lbl = QLabel("")
        self._nudge_lbl.setWordWrap(True)
        self._nudge_lbl.setStyleSheet(
            f"color: {THEME['warning']}; font-size: 12px;"
            f" border: none; background: transparent;"
        )

        nudge_btn = QPushButton("Upgrade now")
        nudge_btn.setObjectName("btn_primary")
        nudge_btn.setFixedHeight(34)
        nudge_btn.setFixedWidth(130)
        nudge_btn.clicked.connect(lambda: webbrowser.open(UPGRADE_URL))

        nf.addWidget(self._nudge_lbl, 1)
        nf.addWidget(nudge_btn)
        layout.addWidget(self._nudge_frame)

        # ── SECTION 2: License key ───────────────────────────────────────────
        layout.addWidget(section_label("License key"))

        key_card = QFrame()
        key_card.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        kc = QVBoxLayout(key_card)
        kc.setContentsMargins(20, 16, 20, 16)
        kc.setSpacing(10)

        info = QLabel(
            "Purchase a plan at accgenie.in "
            "to receive your license key by email."
        )
        info.setStyleSheet(
            f"color: {THEME['text_secondary']}; font-size: 12px;"
        )
        info.setWordWrap(True)
        kc.addWidget(info)

        key_row = QHBoxLayout()
        key_row.setSpacing(8)

        self._key_edit = QLineEdit()
        self._key_edit.setPlaceholderText(
            "Enter license key — ACCG-XXXX-XXXX-XXXX"
        )
        self._key_edit.setFixedHeight(38)
        self._key_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {THEME['bg_input']};
                border: 1px solid {THEME['border']};
                border-radius: 7px;
                padding: 6px 12px;
                color: {THEME['text_primary']};
                font-size: 12px;
            }}
            QLineEdit:focus {{
                border: 1px solid {THEME['border_focus']};
            }}
        """)
        current_key = self._mgr.license_key
        if current_key not in ("FREE-DEMO", "", None):
            self._key_edit.setText(current_key)

        self._activate_btn = QPushButton("Activate")
        self._activate_btn.setFixedHeight(38)
        self._activate_btn.setFixedWidth(110)
        self._activate_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['accent']};
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                background: {THEME['accent_hover']};
            }}
            QPushButton:disabled {{
                background: {THEME['text_dim']};
            }}
        """)
        self._activate_btn.clicked.connect(self._activate)

        key_row.addWidget(self._key_edit, 1)
        key_row.addWidget(self._activate_btn)
        kc.addLayout(key_row)

        self._key_status = QLabel("")
        self._key_status.setStyleSheet(
            f"font-size: 11px; color: transparent;"
        )
        kc.addWidget(self._key_status)

        layout.addWidget(key_card)

        # ── SECTION 3: Plan comparison ───────────────────────────────────────
        layout.addWidget(section_label("Available plans"))

        plans_card = QFrame()
        plans_card.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        pc2 = QVBoxLayout(plans_card)
        pc2.setContentsMargins(20, 16, 20, 16)
        pc2.setSpacing(10)

        plan_defs = [
            ("FREE",     "Rs.0 / year",
             "5,000 transactions",
             "Basic ledger, day book"),
            ("STANDARD", "Rs.1,999 / year",
             "20,000 transactions",
             "Reports, export, backup, 2 users"),
            ("PRO",      "Rs.4,999 / year",
             "50,000 transactions",
             "GST, TDS, AI reader, 5 users"),
            ("PREMIUM",  "Rs.9,999 / year",
             "Unlimited transactions",
             "All features, WhatsApp, audit"),
        ]

        for plan_key, price, txns, desc in plan_defs:
            is_current = (plan_key == self._mgr.plan)

            row = QFrame()
            row.setStyleSheet(f"""
                QFrame {{
                    background: {THEME['accent_dim'] if is_current else THEME['bg_input']};
                    border: {'1.5px solid ' + THEME['accent'] if is_current else '1px solid ' + THEME['border']};
                    border-radius: 8px;
                }}
            """)
            rl = QHBoxLayout(row)
            rl.setContentsMargins(14, 12, 14, 12)
            rl.setSpacing(12)

            left = QVBoxLayout()
            left.setSpacing(3)

            name_lbl = QLabel(plan_key)
            name_lbl.setStyleSheet(f"""
                color: {THEME['accent'] if is_current else THEME['text_primary']};
                font-size: 13px;
                font-weight: bold;
                background: transparent;
                border: none;
                padding: 0px;
            """)

            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"""
                color: {THEME['text_secondary']};
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0px;
            """)
            desc_lbl.setWordWrap(True)

            left.addWidget(name_lbl)
            left.addWidget(desc_lbl)
            rl.addLayout(left, 2)

            mid = QVBoxLayout()
            mid.setSpacing(3)

            price_lbl = QLabel(price)
            price_lbl.setStyleSheet(f"""
                color: {THEME['text_primary']};
                font-size: 13px;
                font-weight: 500;
                background: transparent;
                border: none;
                padding: 0px;
            """)

            txn_lbl = QLabel(txns)
            txn_lbl.setStyleSheet(f"""
                color: {THEME['success']};
                font-size: 11px;
                background: transparent;
                border: none;
                padding: 0px;
            """)

            mid.addWidget(price_lbl)
            mid.addWidget(txn_lbl)
            rl.addLayout(mid, 1)

            if is_current:
                cur_lbl = QLabel("✓ Current")
                cur_lbl.setStyleSheet(f"""
                    color: {THEME['accent']};
                    font-size: 12px;
                    font-weight: bold;
                    background: transparent;
                    border: none;
                    padding: 0px;
                """)
                cur_lbl.setAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
                rl.addWidget(cur_lbl)
            else:
                up_btn = QPushButton("Upgrade →")
                up_btn.setFixedHeight(34)
                up_btn.setFixedWidth(110)
                up_btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {THEME['accent']};
                        color: white;
                        border: none;
                        border-radius: 7px;
                        font-size: 12px;
                        font-weight: bold;
                        padding: 6px 14px;
                    }}
                    QPushButton:hover {{
                        background: {THEME['accent_hover']};
                    }}
                """)
                target = plan_key
                up_btn.clicked.connect(
                    lambda _, p=target: webbrowser.open(f"{UPGRADE_URL}?plan={p}")
                )
                rl.addWidget(up_btn)

            pc2.addWidget(row)

        buy_note = QLabel(
            "Pay via Razorpay · UPI · Cards · NetBanking · Get key instantly by email"
        )
        buy_note.setStyleSheet(
            f"color: {THEME['text_dim']}; font-size: 10px;"
        )
        buy_note.setWordWrap(True)
        pc2.addWidget(buy_note)

        layout.addWidget(plans_card)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

    # ── Refresh ──────────────────────────────────────────────────────────────

    def refresh(self):
        s     = self._mgr.status_summary()
        plan  = s["plan"]
        used  = s["txn_used"]
        limit = s["txn_limit"]
        pct   = s["txn_pct"]

        colours = {
            "FREE":     (THEME["text_secondary"], THEME["bg_hover"]),
            "STANDARD": (THEME["accent"],         THEME["accent_dim"]),
            "PRO":      (THEME["success"],         "#0A2A0A"),
            "PREMIUM":  (THEME["warning"],         "#2A1A00"),
        }
        fc, bc = colours.get(plan, (THEME["accent"], THEME["accent_dim"]))
        self._plan_badge.setText(plan)
        self._plan_badge.setStyleSheet(f"""
            background: {bc};
            color: {fc};
            border: 1px solid {fc};
            border-radius: 6px;
            padding: 4px 16px;
            font-size: 14px;
            font-weight: bold;
        """)

        days = s["days_to_expiry"]
        if s["is_expired"]:
            self._expiry_lbl.setText("EXPIRED — renew now")
            self._expiry_lbl.setStyleSheet(
                f"color: {THEME['danger']}; font-size: 12px; font-weight: bold;"
            )
        elif days <= 30:
            self._expiry_lbl.setText(f"Expires in {days} days")
            self._expiry_lbl.setStyleSheet(
                f"color: {THEME['warning']}; font-size: 12px;"
            )
        else:
            self._expiry_lbl.setText(f"Valid until {s['expires_at']}")
            self._expiry_lbl.setStyleSheet(
                f"color: {THEME['text_secondary']}; font-size: 12px;"
            )

        self._txn_used_val.setText(f"{used:,}")
        self._txn_limit_val.setText(
            "Unlimited" if plan == "PREMIUM" else f"{limit:,}"
        )

        overage = s["overage_count"]
        cost    = s["overage_cost"]
        if overage > 0:
            self._overage_val.setText(f"Rs.{cost:.2f}")
            self._overage_val.setStyleSheet(f"""
                color: {THEME['warning']};
                font-size: 20px; font-weight: 500;
                background: transparent; border: none;
            """)
        else:
            self._overage_val.setText("Rs.0.00")
            self._overage_val.setStyleSheet(f"""
                color: {THEME['success']};
                font-size: 20px; font-weight: 500;
                background: transparent; border: none;
            """)

        ul = self._mgr.user_limit
        self._users_val.setText("Unlimited" if ul >= 999 else str(ul))

        fill_pct = min(pct, 100) / 100
        if pct >= 100:
            bar_color = THEME["danger"]
        elif pct >= 80:
            bar_color = THEME["warning"]
        else:
            bar_color = THEME["success"]

        self._bar_fill.setStyleSheet(f"""
            QFrame {{
                background: {bar_color};
                border-radius: 6px;
                border: none;
            }}
        """)

        from PySide6.QtCore import QTimer
        def _set_bar():
            total_w = self._bar_bg.width()
            fill_w  = max(0, int(total_w * fill_pct))
            self._bar_fill.setFixedWidth(fill_w)
        QTimer.singleShot(100, _set_bar)

        remaining = max(0, limit - used)
        if plan == "PREMIUM":
            detail = f"{used:,} transactions used"
        elif used > limit:
            ov   = used - limit
            rate = 0.30
            detail = (
                f"{used:,} of {limit:,} — "
                f"{ov:,} over limit (Rs.{ov*rate:.2f} overage)"
            )
        else:
            detail = (
                f"{used:,} of {limit:,} used — {remaining:,} remaining"
            )
        self._usage_detail.setText(detail)

        nudge = self._mgr.upgrade_savings()
        if nudge:
            self._nudge_frame.setVisible(True)
            self._nudge_lbl.setText(
                f"{nudge['overage_txn']:,} overage txn = Rs.{nudge['overage_cost']:.2f}."
                f" Upgrading to {nudge['next_plan']} saves Rs.{nudge['would_save']:.2f}."
            )
        else:
            self._nudge_frame.setVisible(False)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _activate(self):
        key = self._key_edit.text().strip().upper()
        if not key:
            self._show_key_status(
                "Please enter your license key.", THEME["danger"]
            )
            return

        self._activate_btn.setEnabled(False)
        self._activate_btn.setText("Checking...")
        self._show_key_status(
            "Contacting license server...", THEME["text_secondary"]
        )

        self._thread = ValidateThread(self._mgr, key)
        self._thread.finished.connect(self._on_validate)
        self._thread.start()

    def _on_validate(self, ok: bool, msg: str):
        self._activate_btn.setEnabled(True)
        self._activate_btn.setText("Activate")

        if ok:
            self._show_key_status(f"✓  {msg}", THEME["success"])
            self.refresh()
            self.plan_changed.emit(self._mgr.plan)
            QMessageBox.information(
                self, "Activated",
                f"License activated!\n\nPlan: {self._mgr.plan}\n"
                f"Expires: {self._mgr.expires_at}"
            )
        else:
            self._show_key_status(f"✗  {msg}", THEME["danger"])

    def _show_key_status(self, text: str, colour: str):
        self._key_status.setText(text)
        self._key_status.setStyleSheet(
            f"font-size: 11px; color: {colour};"
        )
