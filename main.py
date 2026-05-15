"""
main.py — Launch the Accounting App
=====================================
Double-click this file or run:
    python main.py

Requirements:
    pip install -r requirements.txt
"""
import sys
import os

# Always resolve paths relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from PySide6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QFormLayout, QFrame,
    QDoubleSpinBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui  import QFont, QPixmap, QIcon

LOGO_PATH = os.path.join(BASE_DIR, "ui", "AccGenie final logo.png")

from core.models        import Database
from core.account_tree  import AccountTree
from core.voucher_engine import VoucherEngine
from ui.theme           import THEME, get_stylesheet


# ── Company Selector / Creator Dialog ────────────────────────────────────────

class CompanyDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AccGenie — Open Company")
        self.setMinimumWidth(460)
        self.setMinimumHeight(320)
        self.setStyleSheet(get_stylesheet())
        self.selected_db   = None
        self.selected_cid  = None
        self.selected_tree = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 24, 24, 24)

        # Logo
        logo = QLabel()
        logo.setPixmap(
            QPixmap(LOGO_PATH).scaledToHeight(
                160, Qt.TransformationMode.SmoothTransformation
            )
        )
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Existing companies
        existing = self._get_existing()
        if existing:
            open_lbl = QLabel("Open existing company")
            open_lbl.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;")
            layout.addWidget(open_lbl)

            self.company_combo = QComboBox()
            self.company_combo.setFixedHeight(34)
            for slug, name in existing:
                self.company_combo.addItem(name, slug)
            layout.addWidget(self.company_combo)

            open_btn = QPushButton("Open")
            open_btn.setObjectName("btn_primary")
            open_btn.setFixedHeight(36)
            open_btn.clicked.connect(self._open_existing)
            layout.addWidget(open_btn)

            sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
            layout.addWidget(sep2)

        # Create new
        new_lbl = QLabel("Create new company" if existing else "Set up your company")
        new_lbl.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;")
        layout.addWidget(new_lbl)

        form = QFormLayout()
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText("e.g. My Trading Co Pvt Ltd")
        self.name_edit.setFixedHeight(34)
        form.addRow(QLabel("Company Name *"), self.name_edit)

        self.gstin_edit = QLineEdit()
        self.gstin_edit.setPlaceholderText("e.g. 07AABCD1234E1ZK")
        self.gstin_edit.setFixedHeight(34)
        form.addRow(QLabel("GSTIN"), self.gstin_edit)

        self.state_edit = QLineEdit("07")
        self.state_edit.setFixedHeight(34)
        self.state_edit.setMaximumWidth(60)
        form.addRow(QLabel("State Code"), self.state_edit)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        create_btn = QPushButton("Create & Open")
        create_btn.setObjectName("btn_primary")
        create_btn.setFixedHeight(36)
        create_btn.clicked.connect(self._create_company)
        btn_row.addWidget(create_btn)

        migrate_btn = QPushButton("Create & Migrate from another system…")
        migrate_btn.setFixedHeight(36)
        migrate_btn.setToolTip(
            "Create the company, then launch the migration wizard "
            "(Tally / Excel / Zoho / QuickBooks)."
        )
        migrate_btn.clicked.connect(lambda: self._create_company(migrate=True))
        btn_row.addWidget(migrate_btn)
        layout.addLayout(btn_row)

        self.name_edit.returnPressed.connect(self._create_company)

    def _get_existing(self):
        """Return list of (slug, company_name) from the companies dir."""
        from core.paths import companies_dir
        db_dir = companies_dir()
        result = []
        if db_dir.exists():
            for f in sorted(db_dir.glob("*.db")):
                try:
                    db_tmp = Database(f.stem)
                    row = db_tmp.execute(
                        "SELECT name FROM companies LIMIT 1"
                    ).fetchone()
                    if row:
                        result.append((f.stem, row["name"]))
                    db_tmp.close()
                except Exception:
                    pass
        return result

    def _open_existing(self):
        slug = self.company_combo.currentData()
        try:
            db = Database(slug)
            row = db.execute("SELECT id FROM companies LIMIT 1").fetchone()
            if not row:
                QMessageBox.warning(self, "Error", "Company data not found.")
                return
            company_id = row["id"]
            tree = AccountTree(db, company_id)
            self.selected_db  = db
            self.selected_cid = company_id
            self.selected_tree = tree
            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _create_company(self, migrate: bool = False):
        name = self.name_edit.text().strip()
        if not name:
            self.name_edit.setStyleSheet(f"border: 1px solid {THEME['danger']};")
            return

        gstin      = self.gstin_edit.text().strip()
        state_code = self.state_edit.text().strip() or "07"
        if gstin and len(gstin) >= 2:
            state_code = gstin[:2]

        slug = name.lower()
        for ch in " .,()&'\"":
            slug = slug.replace(ch, "_")
        slug = slug[:30].strip("_")

        try:
            db   = Database(slug)
            conn = db.connect()
            conn.execute(
                "INSERT OR IGNORE INTO companies (name, gstin, state_code) VALUES (?,?,?)",
                (name, gstin, state_code)
            )
            db.commit()

            row = conn.execute(
                "SELECT id FROM companies WHERE name=?", (name,)
            ).fetchone()
            company_id = row["id"]

            # Setup FY
            conn.execute(
                "INSERT OR IGNORE INTO financial_years (company_id,fy,start_date,end_date) VALUES (?,?,?,?)",
                (company_id, "2025-26", "2025-04-01", "2026-03-31")
            )
            db.commit()

            # Seed chart of accounts
            tree = AccountTree(db, company_id)
            tree.seed_defaults()

            self.selected_db   = db
            self.selected_cid  = company_id
            self.selected_tree = tree

            # If launched via "Create & Migrate", run the wizard before
            # accepting the dialog. The user can still cancel — the
            # company is already created either way.
            if migrate:
                try:
                    from ui.migration_wizard import MigrationWizard
                    w = MigrationWizard(db, company_id, tree, parent=self)
                    w.exec()
                except Exception as e:
                    QMessageBox.warning(
                        self, "Migration",
                        f"Company created, but migration wizard failed: {e}\n"
                        "You can run migration later from the sidebar.",
                    )

            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AccGenie")
    app.setWindowIcon(QIcon(LOGO_PATH))
    app.setStyle("Fusion")

    # Anonymous install heartbeat — fire-and-forget on a background thread.
    try:
        from core.telemetry import send_install_heartbeat
        send_install_heartbeat()
    except Exception:
        pass

    # Silent license re-validation in the background — refreshes seat counts
    # without blocking the splash. The cached license still gates posting if
    # the server is offline (7-day grace).
    try:
        import threading
        from core.license_manager import LicenseManager
        threading.Thread(
            target=lambda: LicenseManager().validate_on_startup(),
            daemon=True,
        ).start()
    except Exception:
        pass

    # Show company selector
    dlg = CompanyDialog()
    if dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    db         = dlg.selected_db
    company_id = dlg.selected_cid
    tree       = dlg.selected_tree
    engine     = VoucherEngine(db, company_id)

    # Launch main window
    from ui.main_window import MainWindow
    window = MainWindow(db, company_id, tree, engine)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
