"""
Main Window — sidebar navigation + pluggable page stack.

To add a new module later, just:
    main_window.register_page("Reports", "📊", ReportsPage(...))
That's it — no other code changes needed.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QStatusBar,
    QSizePolicy, QMessageBox, QSplitter, QScrollArea
)
from PySide6.QtCore  import Qt, QTimer, Signal, QSize
from PySide6.QtGui   import QFont, QIcon, QPixmap, QKeySequence, QShortcut

LOGO_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ui", "AccGenie final logo.png",
)

from ui.theme              import THEME, get_stylesheet
from ui.widgets            import CalculatorWidget
from core.config           import set_label_style, current_style
from core.license_manager  import LicenseManager


class NavButton(QPushButton):
    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(f"  {icon}   {label}", parent)
        self.setCheckable(True)
        self.setFixedHeight(36)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._update_style(False)

    def set_active(self, active: bool):
        self.setChecked(active)
        self._update_style(active)

    def _update_style(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {THEME['accent_dim']};
                    border: none;
                    border-left: 3px solid {THEME['accent']};
                    border-radius: 7px;
                    padding: 0px 14px 0px 11px;
                    text-align: left;
                    font-size: 12px;
                    color: {THEME['accent']};
                    font-weight: bold;
                    height: 36px;
                    min-height: 36px;
                    max-height: 36px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: none;
                    border-radius: 7px;
                    padding: 0px 14px;
                    text-align: left;
                    font-size: 12px;
                    color: {THEME['text_secondary']};
                    font-weight: normal;
                    height: 36px;
                    min-height: 36px;
                    max-height: 36px;
                }}
                QPushButton:hover {{
                    background-color: {THEME['bg_hover']};
                    color: {THEME['text_primary']};
                }}
            """)


class MainWindow(QMainWindow):
    def __init__(self, db, company_id: int, tree, engine):
        super().__init__()
        self.db         = db
        self.company_id = company_id
        self.tree       = tree
        self.engine     = engine

        # FY housekeeping — make sure current (and next, if within 60 days)
        # FY rows exist so period-lock checks have something to read.
        try:
            from core.fy_manager import ensure_current_and_next
            ensure_current_and_next(self.db, self.company_id)
        except Exception:
            pass

        self.license_mgr = LicenseManager()

        # Shared calculator (one instance, shown/hidden)
        self.calculator = CalculatorWidget(self)

        self._pages: list[tuple[str, str, QWidget, NavButton]] = []
        self._current_idx = -1

        self._setup_window()
        self._build_layout()
        self._build_pages()
        self._wire_shortcuts()
        self._select_page(0)

        # Backup reminder — fires 2 s after window opens (non-blocking)
        QTimer.singleShot(2000, self._check_backup_reminder)

    # ── Window setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        row = self.db.execute(
            "SELECT name, gstin FROM companies WHERE id=?",
            (self.company_id,)
        ).fetchone()
        self._company_name = row["name"] if row else "Company"
        self._company_gstin = row["gstin"] if row else ""

        self.setWindowTitle(f"AccGenie — {self._company_name}")
        self.resize(1280, 780)
        self.setMinimumSize(900, 600)
        self.setStyleSheet(get_stylesheet())

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_layout(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Sidebar ──
        self._sidebar = QFrame()
        self._sidebar.setObjectName("sidebar")
        self._sidebar.setFixedWidth(200)
        sidebar_layout = QVBoxLayout(self._sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.setSpacing(0)

        # Logo / company
        logo_box = QFrame()
        logo_box.setObjectName("sidebar_logo")
        logo_layout = QVBoxLayout(logo_box)
        logo_layout.setContentsMargins(16, 14, 16, 12)
        logo_layout.setSpacing(2)

        logo_lbl = QLabel()
        logo_lbl.setPixmap(
            QPixmap(LOGO_PATH).scaledToWidth(
                140, Qt.TransformationMode.SmoothTransformation
            )
        )
        logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        co_lbl = QLabel(self._company_name[:26])
        co_lbl.setObjectName("company_text")
        co_lbl.setWordWrap(True)
        co_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo_layout.addWidget(logo_lbl)
        logo_layout.addWidget(co_lbl)
        sidebar_layout.addWidget(logo_box)

        # Scrollable nav container — with many section + button entries the
        # sidebar overflows the window, and Qt was squeezing the unfixed
        # section labels to zero. A QScrollArea keeps the calc button at the
        # bottom pinned and lets the nav content scroll if it doesn't fit.
        self._nav_scroll = QScrollArea()
        self._nav_scroll.setWidgetResizable(True)
        self._nav_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._nav_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._nav_scroll.setStyleSheet(
            f"QScrollArea {{ background: {THEME['bg_sidebar']}; border: none; }}"
        )

        nav_host = QWidget()
        nav_host.setStyleSheet(f"background: {THEME['bg_sidebar']};")
        nav_outer = QVBoxLayout(nav_host)
        nav_outer.setContentsMargins(0, 0, 0, 0)
        nav_outer.setSpacing(0)

        nav_section = QLabel("TRANSACTIONS")
        nav_section.setObjectName("nav_section")
        nav_section.setMinimumHeight(34)
        nav_outer.addWidget(nav_section)

        # Nav buttons container (populated by register_page)
        self._nav_container = QVBoxLayout()
        self._nav_container.setSpacing(0)
        self._nav_container.setContentsMargins(0, 0, 0, 0)
        nav_outer.addLayout(self._nav_container)
        nav_outer.addStretch()

        self._nav_scroll.setWidget(nav_host)
        sidebar_layout.addWidget(self._nav_scroll, 1)

        # Switch company button (just above calc)
        switch_btn = QPushButton("  🔄   Switch Company…")
        switch_btn.setFixedHeight(36)
        switch_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 7px;
                padding: 0px 14px;
                text-align: left;
                font-size: 12px;
                color: {THEME['text_secondary']};
                height: 36px;
                min-height: 36px;
                max-height: 36px;
            }}
            QPushButton:hover {{
                background-color: {THEME['bg_hover']};
                color: {THEME['text_primary']};
            }}
        """)
        switch_btn.clicked.connect(self.change_company)
        sidebar_layout.addWidget(switch_btn)

        # Calc button at bottom
        calc_btn = QPushButton("  ⌨   Calculator   (Alt+C)")
        calc_btn.setFixedHeight(36)
        calc_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 7px;
                padding: 0px 14px;
                text-align: left;
                font-size: 12px;
                color: {THEME['text_secondary']};
                height: 36px;
                min-height: 36px;
                max-height: 36px;
            }}
            QPushButton:hover {{
                background-color: {THEME['bg_hover']};
                color: {THEME['text_primary']};
            }}
        """)
        calc_btn.clicked.connect(self._show_calculator)
        sidebar_layout.addWidget(calc_btn)

        # Version label
        ver = QLabel("v1.0  |  Python + SQLite")
        ver.setStyleSheet(f"color:{THEME['text_dim']}; font-size:9px; padding:8px 16px;")
        sidebar_layout.addWidget(ver)

        root.addWidget(self._sidebar)

        # ── Content stack ──
        self._stack = QStackedWidget()
        self._stack.setObjectName("content_area")
        root.addWidget(self._stack, 1)

        # Status bar
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self._all_co_label = QLabel("")
        self._all_co_label.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px; padding-right:10px;"
        )
        self.status.addPermanentWidget(self._all_co_label)
        self._refresh_all_co_total()
        self.status.showMessage(f"  {self._company_name}  |  Ready")

    # ── Page registration ─────────────────────────────────────────────────────

    def register_page(self, label: str, icon: str, widget: QWidget,
                      section_above: str = ""):
        """
        Add a new page to the sidebar and stack.
        Call this to plug in any future module (Reports, AI reader, etc.)
        """
        if section_above:
            sec = QLabel(section_above)
            sec.setObjectName("nav_section")
            sec.setMinimumHeight(34)
            self._nav_container.addWidget(sec)

        btn = NavButton(icon, label, self._sidebar)
        btn.clicked.connect(lambda _, idx=len(self._pages): self._select_page(idx))
        self._nav_container.addWidget(btn)

        self._stack.addWidget(widget)
        self._pages.append((label, icon, widget, btn))

    def _build_pages(self):
        import traceback
        try:
            self._build_pages_inner()
        except Exception:
            tb = traceback.format_exc()
            print("STARTUP CRASH in _build_pages:\n" + tb)
            QMessageBox.critical(
                None, "Startup Error",
                "Failed to build app pages:\n\n" + tb
            )
            raise

    def _locked_page(self, feature: str, required_plan: str,
                     feature_label: str) -> QWidget:
        """Build a FeatureGateWidget pre-wired to navigate to the License page."""
        from ui.feature_gate_widget import FeatureGateWidget
        w = FeatureGateWidget(
            feature, required_plan, self.license_mgr.plan, feature_label
        )
        w.upgrade_requested.connect(self._navigate_to_license)
        return w

    def _navigate_to_license(self):
        for idx, (label, _, _, _) in enumerate(self._pages):
            if label == "License & Plan":
                self._select_page(idx)
                return

    def open_voucher_for_edit(self, voucher_id: int) -> None:
        """
        Switch to the Post Voucher page and load the given voucher in
        edit mode. Remembers the origin page so we can return there
        after Update / Cancel.
        """
        if not hasattr(self, "_voucher_page"):
            return
        ok = self._voucher_page.load_voucher_for_edit(voucher_id)
        if not ok:
            return
        # Remember where we came from so update/cancel can return there.
        self._voucher_origin_idx = self._current_idx
        for idx, (label, _, _, _) in enumerate(self._pages):
            if label == "Post Voucher":
                self._select_page(idx)
                return

    def open_voucher_for_create(
        self, prefill: dict, on_post_callback=None,
        banner_text: str = "",
    ) -> None:
        """
        Switch to Post Voucher with the form prefilled for a fresh post,
        run on_post_callback after a successful post, then return to the
        page we came from. Used by Ledger Reconciliation's 'Add voucher'.
        """
        if not hasattr(self, "_voucher_page"):
            return
        self._voucher_page.prefill_for_create(
            prefill, on_post_callback=on_post_callback,
            banner_text=banner_text,
        )
        self._voucher_origin_idx = self._current_idx
        for idx, (label, _, _, _) in enumerate(self._pages):
            if label == "Post Voucher":
                self._select_page(idx)
                return

    def return_from_voucher_edit(self) -> None:
        """Called by VoucherEntryPage after Update / Cancel in edit mode."""
        idx = getattr(self, "_voucher_origin_idx", None)
        self._voucher_origin_idx = None
        if idx is None:
            return
        # _select_page calls widget.refresh() automatically if available,
        # so the ledger view picks up the updated voucher.
        self._select_page(idx)

    def _build_pages_inner(self):
        from ui.voucher_form     import VoucherEntryPage
        from ui.daybook          import DayBookPage, LedgerBalancePage
        from core.reports_engine import ReportsEngine

        lmgr = self.license_mgr

        voucher_page = VoucherEntryPage(self.engine, self.tree, self.calculator)
        voucher_page.voucher_posted.connect(self._on_voucher_posted)
        self.register_page("Post Voucher", "✏", voucher_page)
        self._voucher_page = voucher_page

        self._daybook_page = DayBookPage(self.engine)
        self.register_page("Day Book", "📋", self._daybook_page)

        # ── Ledger Balances — FREE ──
        self._balance_page = LedgerBalancePage(self.tree)
        self.register_page("Ledger Balances", "⚖", self._balance_page,
                            section_above="REPORTS")

        # ── Financial reports — STANDARD+ ──
        if lmgr.has_feature("reports"):
            from ui.reports_page import (
                TrialBalancePage, ProfitLossPage, BalanceSheetPage,
                CashBookPage, BankBookPage, ReceiptsPaymentsPage,
                LedgerAccountPage,
            )
            rpt = ReportsEngine(self.db, self.company_id)
            self.register_page("Trial Balance",  "📊", TrialBalancePage(rpt))
            self.register_page("P & L",          "📈", ProfitLossPage(rpt))
            self.register_page("Balance Sheet",  "🏦", BalanceSheetPage(rpt))
            self.register_page("Cash Book",      "💵", CashBookPage(rpt))
            self.register_page("Bank Book",      "🏛", BankBookPage(rpt))
            self.register_page("Ledger Account", "📒",
                LedgerAccountPage(rpt, self.tree, self.engine))
            self.register_page("Rcpts & Pmts",   "↕",  ReceiptsPaymentsPage(rpt))
        else:
            self.register_page(
                "Reports", "📊",
                self._locked_page("reports", "STANDARD", "Financial Reports"),
            )

        # ── Bank Reconciliation — STANDARD+ ──
        if lmgr.has_feature("bank_reconciliation"):
            from ui.bank_reconciliation_page import BankReconciliationPage
            self.register_page(
                "Bank Reconciliation", "🏦",
                BankReconciliationPage(
                    self.db, self.company_id, self.tree,
                    self.engine, self.calculator, lmgr,
                ),
                section_above="BANKING",
            )
        else:
            self.register_page(
                "Bank Reconciliation", "🏦",
                self._locked_page(
                    "bank_reconciliation", "STANDARD", "Bank Reconciliation"
                ),
                section_above="BANKING",
            )

        # ── Ledger Reconciliation — STANDARD+ ──
        if lmgr.has_feature("ledger_reconciliation"):
            from ui.ledger_reconciliation_page import LedgerReconciliationPage
            self.register_page(
                "Ledger Reconciliation", "📒",
                LedgerReconciliationPage(
                    self.db, self.company_id, self.tree,
                    self.engine, self.calculator, lmgr,
                ),
            )
        else:
            self.register_page(
                "Ledger Reconciliation", "📒",
                self._locked_page(
                    "ledger_reconciliation", "STANDARD", "Ledger Reconciliation"
                ),
            )

        # ── GST — PRO+ ──
        if lmgr.has_feature("gst"):
            from ui.reports_page import GSTSummaryPage
            rpt_gst = ReportsEngine(self.db, self.company_id)
            self.register_page("GST Returns", "🧾", GSTSummaryPage(rpt_gst),
                                section_above="TAX")
        else:
            self.register_page(
                "GST Returns", "🧾",
                self._locked_page("gst", "PRO", "GST Returns"),
                section_above="TAX",
            )

        # ── TDS — PRO+ ──
        if lmgr.has_feature("tds"):
            from ui.reports_page import TDSReportPage
            rpt_tds = ReportsEngine(self.db, self.company_id)
            self.register_page("TDS Reports", "📑", TDSReportPage(rpt_tds))
        else:
            self.register_page(
                "TDS Reports", "📑",
                self._locked_page("tds", "PRO", "TDS Reports"),
            )

        # ── AI Doc Reader — PRO+ ──
        if lmgr.has_feature("ai_document_reader"):
            from ui.document_reader_page import DocumentReaderPage
            self.register_page(
                "AI Doc Reader", "🤖",
                DocumentReaderPage(ReportsEngine(self.db, self.company_id), self.tree),
                section_above="AI",
            )
        else:
            self.register_page(
                "AI Doc Reader", "🤖",
                self._locked_page(
                    "ai_document_reader", "PRO", "AI Document Reader"
                ),
                section_above="AI",
            )

        self.register_page("Verbal Entry", "🎙",
                           self._placeholder("Speak a voucher — AI posts it\n(Coming next)"))

        # ── Backup — STANDARD+ ──
        if lmgr.has_feature("backup"):
            from ui.backup_page      import BackupPage
            from core.backup_manager import BackupManager
            backup_mgr = BackupManager(
                db_path      = str(self.db.path),
                company_slug = self.db.path.stem,
            )
            self._backup_mgr = backup_mgr
            self.register_page("Backup & Restore", "💾", BackupPage(backup_mgr),
                                section_above="DATA")
        else:
            self.register_page(
                "Backup & Restore", "💾",
                self._locked_page("backup", "STANDARD", "Backup & Restore"),
                section_above="DATA",
            )

        # ── Book Migration — STANDARD+ ──
        if lmgr.has_feature("book_migration"):
            from ui.migration_page import MigrationPage
            self.register_page(
                "Migration", "📦",
                MigrationPage(self.db, self.company_id, self.tree),
            )
        else:
            self.register_page(
                "Migration", "📦",
                self._locked_page(
                    "book_migration", "STANDARD", "Book Migration"
                ),
            )

        # ── License page ──
        from ui.license_page import LicensePage
        lic_page = LicensePage(lmgr)
        lic_page.plan_changed.connect(self._on_plan_changed)
        self.register_page("License & Plan", "🔑", lic_page, section_above="ACCOUNT")

        from ui.feedback_page import FeedbackPage
        feedback_page = FeedbackPage(self.license_mgr)
        self.register_page("Feedback", "💬", feedback_page)

        from ui.period_locks_page import PeriodLocksPage
        self.register_page(
            "Period Locks", "🔒",
            PeriodLocksPage(self.db, self.company_id),
            section_above="SETTINGS",
        )

        settings_page = self._build_settings_page()
        self.register_page("Settings", "⚙", settings_page)

    def _build_settings_page(self) -> QWidget:
        from PySide6.QtWidgets import QCheckBox, QComboBox
        from ui.widgets import make_label
        from core.user_prefs import prefs

        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(32, 24, 32, 24)
        outer.setSpacing(0)

        title = QLabel("Settings")
        title.setObjectName("page_title")
        outer.addWidget(title)

        sub = QLabel("Preferences are saved per machine and persist across restarts.")
        sub.setObjectName("page_subtitle")
        outer.addWidget(sub)

        # Scrollable body so the page stays usable as more cards are added.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 16, 8, 0)
        layout.setSpacing(20)

        # ── Card: Dr / Cr Label Style ─────────────────────────────────────────
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        card_layout.addWidget(make_label("Dr / Cr Label Style"))
        hint = QLabel("Choose how debit and credit labels appear throughout the app.")
        hint.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        card_layout.addWidget(hint)

        descriptions = {
            "natural":     ("Paid To / Recd From",  "Plain language — recommended for most users"),
            "traditional": ("By / To",               "Traditional Indian accounting style"),
            "accounting":  ("Debit / Credit",        "Standard accounting terminology"),
        }

        btn_row = QHBoxLayout()
        self._style_btns: dict[str, QPushButton] = {}
        for key, (short_lbl, desc) in descriptions.items():
            btn = QPushButton(f"{short_lbl}\n{desc}")
            btn.setCheckable(True)
            btn.setFixedHeight(52)
            btn.setChecked(key == current_style())
            btn.setStyleSheet(f"""
                QPushButton {{
                    border: 1px solid {THEME['border']};
                    border-radius: 6px;
                    padding: 4px 16px;
                    font-size: 11px;
                    color: {THEME['text_secondary']};
                    background: transparent;
                    text-align: left;
                }}
                QPushButton:checked {{
                    background: {THEME['accent']}22;
                    border-color: {THEME['accent']};
                    color: {THEME['accent']};
                    font-weight: bold;
                }}
                QPushButton:hover:!checked {{
                    border-color: {THEME['accent']};
                }}
            """)
            btn.clicked.connect(lambda _, k=key: self._apply_style(k))
            self._style_btns[key] = btn
            btn_row.addWidget(btn)
        btn_row.addStretch()
        card_layout.addLayout(btn_row)
        layout.addWidget(card)

        # ── Card: Voucher form ────────────────────────────────────────────────
        v_card = self._pref_card("Voucher form")

        v_card.addWidget(self._pref_checkbox(
            "Show success toast after posting a voucher",
            "Tick to keep the post-success popup. Untick for silent posting — "
            "the voucher still gets saved.",
            key="after_post_toast", default=True,
        ))

        v_card.addWidget(self._pref_choice(
            "Default voucher date",
            "What date the form should start with each time.",
            key="default_voucher_date", default="today",
            options=[("today", "Today"), ("last_used", "Last used date")],
        ))

        layout.addWidget(v_card.parentWidget())

        # ── Card: Bank reconciliation ─────────────────────────────────────────
        b_card = self._pref_card("Bank reconciliation")

        b_card.addWidget(self._pref_checkbox(
            "Ask for a comment when ignoring a statement line",
            "When you 'Ignore' a bank-statement line, AccGenie can ask why "
            "(e.g. 'duplicate', 'bank fee already booked'). Untick to ignore silently.",
            key="bank_reco_comment_on_ignore", default=True,
        ))

        layout.addWidget(b_card.parentWidget())

        # ── Card: Backups ─────────────────────────────────────────────────────
        bk_card = self._pref_card("Backups")

        bk_card.addWidget(self._pref_choice(
            "Backup reminder interval",
            "How often AccGenie should nudge you to back up the current "
            "company. The reminder fires when the app opens.",
            key="backup_reminder_days", default=7,
            options=[(1, "Every day"), (3, "Every 3 days"),
                     (7, "Every 7 days"), (14, "Every 14 days"),
                     (30, "Every 30 days")],
        ))

        layout.addWidget(bk_card.parentWidget())

        # ── Card: AI Routing ──────────────────────────────────────────────────
        ai_card = self._pref_card("AI Routing")
        ai_card_widget = ai_card.parentWidget()

        ai_hint = QLabel(
            "Pick how each AI feature reaches Anthropic — pooled credits "
            "(billed from your AccGenie balance) or your own Anthropic key "
            "(billed directly by Anthropic)."
        )
        ai_hint.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        ai_hint.setWordWrap(True)
        ai_card.addWidget(ai_hint)

        from core.ai_routing import routing as _routing, FEATURES
        from ui.ai_routing_dialog import FEATURE_LABELS

        for feat in FEATURES:
            row = QHBoxLayout()
            label = QLabel(FEATURE_LABELS.get(feat, feat))
            label.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px;")
            row.addWidget(label)
            row.addStretch()
            route_badge = QLabel(_routing.route_for(feat).upper())
            badge_color = (THEME['accent']
                           if _routing.route_for(feat) == "own"
                           else THEME['success'])
            route_badge.setStyleSheet(
                f"color: {badge_color}; font-size: 11px; font-weight: bold;"
                f" padding: 2px 8px; border: 1px solid {badge_color};"
                f" border-radius: 4px;"
            )
            row.addWidget(route_badge)
            edit_btn = QPushButton("Change…")
            edit_btn.setFixedHeight(28)
            edit_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {THEME['accent']};
                    border: 1px solid {THEME['accent']};
                    border-radius: 6px;
                    padding: 2px 12px;
                    font-size: 11px;
                }}
                QPushButton:hover {{ background: {THEME['accent']}; color: white; }}
            """)
            edit_btn.clicked.connect(
                lambda _, f=feat: self._edit_ai_route(f)
            )
            row.addWidget(edit_btn)
            ai_card.addLayout(row)

        layout.addWidget(ai_card_widget)

        # ── Card: Period locks shortcut ───────────────────────────────────────
        p_card = self._pref_card("Accounting period locks")
        p_card_widget = p_card.parentWidget()

        p_card.addWidget(QLabel(
            "Close financial years or lock arbitrary date ranges to prevent "
            "further posting / editing / cancelling. See the Period Locks page "
            "in the sidebar."
        ))
        # Style the label
        for w in p_card_widget.findChildren(QLabel):
            if "Close financial years" in (w.text() or ""):
                w.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
                w.setWordWrap(True)

        open_btn = QPushButton("Open Period Locks →")
        open_btn.setFixedHeight(34)
        open_btn.setFixedWidth(180)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {THEME['accent']};
                border: 1px solid {THEME['accent']};
                border-radius: 7px;
                padding: 4px 14px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['accent']}; color: white; }}
        """)
        open_btn.clicked.connect(self._navigate_to_period_locks)
        p_card.addWidget(open_btn)

        layout.addWidget(p_card_widget)

        layout.addStretch()
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return page

    # ── Settings-card helpers ─────────────────────────────────────────────────

    def _pref_card(self, title: str) -> QVBoxLayout:
        """Create a Settings card with a title; returns its inner layout."""
        from ui.widgets import make_label
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 16, 20, 16)
        cl.setSpacing(12)
        cl.addWidget(make_label(title))
        return cl

    def _pref_checkbox(self, label: str, hint: str, key: str,
                       default: bool) -> QWidget:
        from PySide6.QtWidgets import QCheckBox
        from core.user_prefs import prefs

        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)
        cb = QCheckBox(label)
        cb.setChecked(bool(prefs.get(key, default)))
        cb.toggled.connect(lambda v, k=key: prefs.set(k, bool(v)))
        cb.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px;")
        col.addWidget(cb)
        h = QLabel(hint)
        h.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px; padding-left:22px;")
        h.setWordWrap(True)
        col.addWidget(h)
        return w

    def _pref_choice(self, label: str, hint: str, key: str,
                     default, options: list[tuple]) -> QWidget:
        """One-of choice rendered as a labeled QComboBox."""
        from PySide6.QtWidgets import QComboBox
        from core.user_prefs import prefs

        w = QWidget()
        col = QVBoxLayout(w)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(4)

        head = QHBoxLayout()
        head_lbl = QLabel(label)
        head_lbl.setStyleSheet(f"color:{THEME['text_primary']}; font-size:12px;")
        head.addWidget(head_lbl)
        head.addStretch()

        combo = QComboBox()
        combo.setFixedHeight(30)
        combo.setMinimumWidth(180)
        current = prefs.get(key, default)
        for value, text in options:
            combo.addItem(text, value)
        # Select the current value
        for i in range(combo.count()):
            if combo.itemData(i) == current:
                combo.setCurrentIndex(i)
                break
        combo.currentIndexChanged.connect(
            lambda _i, c=combo, k=key: prefs.set(k, c.currentData())
        )
        head.addWidget(combo)
        col.addLayout(head)

        h = QLabel(hint)
        h.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        h.setWordWrap(True)
        col.addWidget(h)
        return w

    def _navigate_to_period_locks(self) -> None:
        for idx, (label, _, _, _) in enumerate(self._pages):
            if label == "Period Locks":
                self._select_page(idx)
                return

    def _edit_ai_route(self, feature: str) -> None:
        """Open the AI Routing dialog for a feature and refresh Settings."""
        from ui.ai_routing_dialog import AIRoutingDialog
        dlg = AIRoutingDialog(feature, parent=self)
        dlg.exec()
        # Rebuild the Settings page so the badges and key field reflect the
        # new state. Cheap — it's just one QWidget tree.
        settings_idx = next(
            (i for i, (l, _, _, _) in enumerate(self._pages) if l == "Settings"),
            None,
        )
        if settings_idx is not None:
            old_widget = self._pages[settings_idx][2]
            new_widget = self._build_settings_page()
            self._stack.removeWidget(old_widget)
            old_widget.deleteLater()
            self._stack.insertWidget(settings_idx, new_widget)
            self._pages[settings_idx] = (
                self._pages[settings_idx][0],
                self._pages[settings_idx][1],
                new_widget,
                self._pages[settings_idx][3],
            )
            if self._current_idx == settings_idx:
                self._stack.setCurrentWidget(new_widget)

    def _apply_style(self, style: str):
        set_label_style(style)
        for k, btn in self._style_btns.items():
            btn.setChecked(k == style)
        self._refresh_all_pages()
        QMessageBox.information(
            self, "Applied",
            f"Labels updated to '{style}' style."
        )

    def _refresh_all_pages(self):
        """Rebuild label text on all pages without restarting."""
        for label, icon, widget, btn in self._pages:
            if label == "Post Voucher":
                if hasattr(widget, 'apply_label_style'):
                    widget.apply_label_style()

    def _placeholder(self, text: str) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(f"color:{THEME['text_dim']}; font-size:18px;")
        layout.addWidget(lbl)
        return w

    # ── Navigation ────────────────────────────────────────────────────────────

    def _select_page(self, idx: int):
        if not self._pages:
            return
        idx = max(0, min(idx, len(self._pages) - 1))

        # Deactivate ALL buttons first
        for _, _, _, btn in self._pages:
            btn.set_active(False)
            btn.update()
            btn.repaint()

        # Activate selected
        label, icon, widget, btn = self._pages[idx]
        btn.set_active(True)
        btn.update()
        btn.repaint()

        self._stack.setCurrentWidget(widget)
        self._current_idx = idx
        self.status.showMessage(
            f"  {self._company_name}  |  {icon}  {label}"
        )

        # Refresh data-driven pages when switched to
        if hasattr(widget, "refresh"):
            widget.refresh()

    def _on_voucher_posted(self, vno: str, vtype: str, amount: float):
        self.status.showMessage(
            f"  ✓  {vno}  posted  |  ₹{amount:,.2f}  |  {self._company_name}"
        )
        self._refresh_all_co_total()

    def _refresh_all_co_total(self):
        try:
            from core.paths import all_companies_voucher_count
            n_co, total = all_companies_voucher_count()
            self._all_co_label.setText(
                f"All companies: {n_co} co · {total:,} vouchers"
            )
        except Exception:
            self._all_co_label.setText("")

    def change_company(self):
        """Close the current company and re-open the selector. The new
        MainWindow is parked on the QApplication so it survives this
        window closing."""
        from main import CompanyDialog
        from core.voucher_engine import VoucherEngine

        dlg = CompanyDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return

        new_db    = dlg.selected_db
        new_cid   = dlg.selected_cid
        new_tree  = dlg.selected_tree
        new_engine = VoucherEngine(new_db, new_cid)

        old_db = self.db
        new_window = MainWindow(new_db, new_cid, new_tree, new_engine)

        # Stash on the QApplication so Python doesn't GC it when `self` dies.
        app = QApplication.instance()
        if app is not None:
            existing = getattr(app, "_accgenie_windows", [])
            existing.append(new_window)
            app._accgenie_windows = existing

        new_window.show()
        self.close()
        try:
            old_db.close()
        except Exception:
            pass

    def _show_calculator(self):
        sidebar_pos = self._sidebar.mapToGlobal(self._sidebar.rect().bottomLeft())
        self.calculator.move(sidebar_pos.x() + 10, sidebar_pos.y() - 360)
        self.calculator.show()
        self.calculator.raise_()

    def _on_plan_changed(self, new_plan: str):
        QMessageBox.information(
            self, "Plan updated",
            f"Your plan is now {new_plan}.\n"
            f"Please restart the app to unlock all features.",
        )

    def _check_backup_reminder(self):
        if hasattr(self, "_backup_mgr") and self._backup_mgr.needs_reminder():
            self._show_backup_reminder(self._backup_mgr)

    def _show_backup_reminder(self, backup_mgr):
        days = backup_mgr.days_since_backup()
        if days < 0:
            msg = "You have never backed up this company."
        else:
            msg = f"Your last backup was {days} day(s) ago."

        reply = QMessageBox.question(
            self,
            "Backup Reminder",
            f"{msg}\n\nWould you like to back up now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Switch to the Backup page
            for idx, (label, _, _, _) in enumerate(self._pages):
                if label == "Backup & Restore":
                    self._select_page(idx)
                    break

    def _wire_shortcuts(self):
        calc_sc = QShortcut(QKeySequence("Alt+C"), self)
        calc_sc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        calc_sc.activated.connect(self._show_calculator)
        # Number keys 1-9 jump to nav pages
        for i in range(min(9, 9)):
            QShortcut(QKeySequence(f"Ctrl+{i+1}"), self).activated.connect(
                lambda _, idx=i: self._select_page(idx)
            )


# ── App bootstrap ─────────────────────────────────────────────────────────────

def launch_app(db, company_id: int, tree, engine):
    """Call this from main.py to launch the GUI."""
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("AccGenie")
    app.setOrganizationName("Aiccounting")

    window = MainWindow(db, company_id, tree, engine)
    window.show()
    sys.exit(app.exec())
