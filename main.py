"""
main.py — Launch the Accounting App
=====================================
Double-click this file or run:
    python main.py

Requirements:
    pip install pyqt6
"""
import sys
import os

# Always resolve paths relative to this file
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from PyQt6.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QLineEdit, QComboBox, QFormLayout, QFrame,
    QDoubleSpinBox, QMessageBox
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui  import QFont

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
        logo = QLabel("⬡  LEDGER")
        logo.setStyleSheet(f"font-size:22px; font-weight:bold; color:{THEME['accent']}; letter-spacing:2px;")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(logo)

        tagline = QLabel("Indian accounting • GST • TDS • Multi-company")
        tagline.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        tagline.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tagline)

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
        self.name_edit.setFixedHeight(32)
        form.addRow(QLabel("Company Name *"), self.name_edit)

        self.gstin_edit = QLineEdit()
        self.gstin_edit.setPlaceholderText("e.g. 07AABCD1234E1ZK")
        self.gstin_edit.setFixedHeight(32)
        form.addRow(QLabel("GSTIN"), self.gstin_edit)

        self.state_edit = QLineEdit("07")
        self.state_edit.setFixedHeight(32)
        self.state_edit.setMaximumWidth(60)
        form.addRow(QLabel("State Code"), self.state_edit)

        layout.addLayout(form)

        create_btn = QPushButton("Create & Open")
        create_btn.setObjectName("btn_primary")
        create_btn.setFixedHeight(36)
        create_btn.clicked.connect(self._create_company)
        layout.addWidget(create_btn)

        self.name_edit.returnPressed.connect(self._create_company)

    def _get_existing(self):
        """Return list of (slug, company_name) from data/companies/."""
        from pathlib import Path
        db_dir = Path(BASE_DIR) / "data" / "companies"
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

    def _create_company(self):
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
            self.accept()

        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))


# ── Entry Point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("AccGenie")
    app.setStyle("Fusion")

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
