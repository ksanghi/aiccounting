"""
Main Window — sidebar navigation + pluggable page stack.

To add a new module later, just:
    main_window.register_page("Reports", "📊", ReportsPage(...))
That's it — no other code changes needed.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QPushButton, QFrame, QStackedWidget, QStatusBar,
    QSizePolicy, QMessageBox, QSplitter
)
from PyQt6.QtCore  import Qt, QTimer, pyqtSignal, QSize
from PyQt6.QtGui   import QFont, QIcon, QKeySequence, QShortcut

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

        self.setWindowTitle(f"Accounting — {self._company_name}")
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

        logo_lbl = QLabel("⬡ LEDGER")
        logo_lbl.setObjectName("logo_text")
        co_lbl = QLabel(self._company_name[:26])
        co_lbl.setObjectName("company_text")
        co_lbl.setWordWrap(True)
        logo_layout.addWidget(logo_lbl)
        logo_layout.addWidget(co_lbl)
        sidebar_layout.addWidget(logo_box)

        # Nav section header
        nav_section = QLabel("TRANSACTIONS")
        nav_section.setObjectName("nav_section")
        sidebar_layout.addWidget(nav_section)

        # Nav buttons container (populated by register_page)
        self._nav_container = QVBoxLayout()
        self._nav_container.setSpacing(0)
        self._nav_container.setContentsMargins(0, 0, 0, 0)
        sidebar_layout.addLayout(self._nav_container)

        sidebar_layout.addStretch()

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

    def _build_pages_inner(self):
        from ui.voucher_form     import VoucherEntryPage
        from ui.daybook          import DayBookPage, LedgerBalancePage
        from ui.feature_gate_widget import FeatureGateWidget
        from core.reports_engine import ReportsEngine

        lmgr = self.license_mgr

        voucher_page = VoucherEntryPage(self.engine, self.tree, self.calculator)
        voucher_page.voucher_posted.connect(self._on_voucher_posted)
        self.register_page("Post Voucher", "✏", voucher_page)

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
            )
            rpt = ReportsEngine(self.db, self.company_id)
            self.register_page("Trial Balance", "📊", TrialBalancePage(rpt))
            self.register_page("P & L",         "📈", ProfitLossPage(rpt))
            self.register_page("Balance Sheet", "🏦", BalanceSheetPage(rpt))
            self.register_page("Cash Book",     "💵", CashBookPage(rpt))
            self.register_page("Bank Book",     "🏛", BankBookPage(rpt))
            self.register_page("Rcpts & Pmts",  "↕",  ReceiptsPaymentsPage(rpt))
        else:
            self.register_page(
                "Reports", "📊",
                FeatureGateWidget(
                    "reports", "STANDARD", lmgr.plan, "Financial Reports"
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
                FeatureGateWidget("gst", "PRO", lmgr.plan, "GST Returns"),
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
                FeatureGateWidget("tds", "PRO", lmgr.plan, "TDS Reports"),
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
                FeatureGateWidget(
                    "ai_document_reader", "PRO", lmgr.plan, "AI Document Reader"
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
                FeatureGateWidget("backup", "STANDARD", lmgr.plan, "Backup & Restore"),
                section_above="DATA",
            )

        # ── License page ──
        from ui.license_page import LicensePage
        lic_page = LicensePage(lmgr)
        lic_page.plan_changed.connect(self._on_plan_changed)
        self.register_page("License & Plan", "🔑", lic_page, section_above="ACCOUNT")

        from ui.feedback_page import FeedbackPage
        feedback_page = FeedbackPage(self.license_mgr)
        self.register_page("Feedback", "💬", feedback_page)

        settings_page = self._build_settings_page()
        self.register_page("Settings", "⚙", settings_page, section_above="SETTINGS")

    def _build_settings_page(self) -> QWidget:
        from ui.widgets import make_label, make_separator
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        title = QLabel("Settings")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel("Customise labels and display preferences.")
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # ── Label style section ──
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
        layout.addStretch()
        return page

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
    app.setApplicationName("Accounting")
    app.setOrganizationName("Aiccounting")

    window = MainWindow(db, company_id, tree, engine)
    window.show()
    sys.exit(app.exec())
