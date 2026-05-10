"""
Migration page (sidebar, DATA section).

Hosts:
  • A button that launches the MigrationWizard for the current company
  • A history table of past migration runs (status + counts + when)
"""
from __future__ import annotations

import json
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame,
)
from PySide6.QtCore import Qt

from ui.theme import THEME


class MigrationPage(QWidget):

    def __init__(self, db, company_id, tree, parent=None):
        super().__init__(parent)
        self.db         = db
        self.company_id = company_id
        self.tree       = tree
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 0, 24, 24)
        root.setSpacing(0)

        title = QLabel("Book Migration")
        title.setObjectName("page_title")
        root.addWidget(title)
        sub = QLabel(
            "Import groups + ledger master + opening balances from Tally, "
            "Zoho Books, QuickBooks, or a prepared Excel chart of accounts."
        )
        sub.setObjectName("page_subtitle")
        root.addWidget(sub)

        # Action card
        card = QFrame()
        card.setObjectName("card")
        cl = QHBoxLayout(card)
        cl.setContentsMargins(20, 14, 20, 14)
        cl.setSpacing(14)

        info = QLabel(
            "Run a migration when this company is empty (no posted vouchers). "
            "Historical transactions stay in your old system; reports here "
            "start from the post-migration opening balances."
        )
        info.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        info.setWordWrap(True)
        cl.addWidget(info, 1)

        launch = QPushButton("Launch migration wizard")
        launch.setObjectName("btn_primary")
        launch.setFixedHeight(36)
        launch.clicked.connect(self._launch_wizard)
        cl.addWidget(launch)
        root.addWidget(card)

        # History
        hist_card = QFrame()
        hist_card.setObjectName("card")
        hl = QVBoxLayout(hist_card)
        hl.setContentsMargins(20, 14, 20, 14)
        hl.setSpacing(8)
        ht = QLabel("Past migration runs")
        ht.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        hl.addWidget(ht)

        self._history_table = QTableWidget(0, 6)
        self._history_table.setHorizontalHeaderLabels(
            ["Started", "Source", "File", "Status", "Counts", "Errors"]
        )
        self._history_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers,
        )
        self._history_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._history_table.verticalHeader().setDefaultSectionSize(36)
        hl.addWidget(self._history_table, 1)
        root.addWidget(hist_card, 1)

    def _launch_wizard(self):
        from ui.migration_wizard import MigrationWizard
        dlg = MigrationWizard(self.db, self.company_id, self.tree, parent=self)
        dlg.completed.connect(lambda *_: self.refresh())
        dlg.exec()

    def refresh(self):
        from core.migration import Migrator
        m = Migrator(self.db, self.company_id, self.tree)
        rows = m.history()
        self._history_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self._history_table.setItem(r, 0, QTableWidgetItem(
                (row.get("started_at") or "")[:16]
            ))
            self._history_table.setItem(r, 1, QTableWidgetItem(
                row.get("source_label") or row.get("source_type") or ""
            ))
            self._history_table.setItem(r, 2, QTableWidgetItem(
                row.get("file_name") or ""
            ))
            self._history_table.setItem(r, 3, QTableWidgetItem(
                row.get("status") or ""
            ))
            counts = row.get("counts") or ""
            try:
                c = json.loads(counts) if counts else {}
                summary = (
                    f"{c.get('groups_added', 0)} groups · "
                    f"{c.get('ledgers_added', 0)} ledgers"
                )
            except Exception:
                summary = counts
            self._history_table.setItem(r, 4, QTableWidgetItem(summary))
            self._history_table.setItem(r, 5, QTableWidgetItem(
                (row.get("error_log") or "")[:120]
            ))
