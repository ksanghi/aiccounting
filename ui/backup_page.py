"""
Backup & Restore page — one-click local backup with history table.
"""
import os
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QHeaderView, QSizePolicy,
)
from PySide6.QtCore  import Qt, QThread, Signal
from PySide6.QtGui   import QFont

from ui.theme import THEME


def _fmt_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 ** 2:
        return f"{n/1024:.1f} KB"
    return f"{n/1024**2:.1f} MB"


# ── Worker thread ─────────────────────────────────────────────────────────────

class BackupThread(QThread):
    finished = Signal(str)   # backup path
    error    = Signal(str)

    def __init__(self, mgr, dest_dir: str = ""):
        super().__init__()
        self._mgr      = mgr
        self._dest_dir = dest_dir

    def run(self):
        try:
            path = self._mgr.create_backup(self._dest_dir)
            self.finished.emit(str(path))
        except Exception as e:
            self.error.emit(str(e))


# ── Page ──────────────────────────────────────────────────────────────────────

class BackupPage(QWidget):

    def __init__(self, mgr, parent=None):
        super().__init__(parent)
        self._mgr    = mgr
        self._thread = None
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(20)

        # Title
        title = QLabel("Backup & Restore")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel("Keep your data safe. Backups are stored locally.")
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # ── Status card ──
        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setSpacing(12)
        card_layout.setContentsMargins(20, 16, 20, 16)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Last backup:"))
        self._last_lbl = QLabel(self._mgr.last_backup_display)
        self._last_lbl.setStyleSheet(f"color:{THEME['accent']}; font-weight:bold;")
        row1.addWidget(self._last_lbl)
        row1.addStretch()
        card_layout.addLayout(row1)

        row2 = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color:{THEME['text_dim']}; font-size:11px;")
        row2.addWidget(self._status_lbl)
        row2.addStretch()
        card_layout.addLayout(row2)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self._backup_btn = QPushButton("  💾  Backup Now")
        self._backup_btn.setFixedHeight(34)
        self._backup_btn.setStyleSheet(self._primary_btn_css())
        self._backup_btn.clicked.connect(self._do_backup)
        btn_row.addWidget(self._backup_btn)

        saveas_btn = QPushButton("  📂  Backup to…")
        saveas_btn.setFixedHeight(34)
        saveas_btn.setStyleSheet(self._secondary_btn_css())
        saveas_btn.clicked.connect(self._do_backup_saveas)
        btn_row.addWidget(saveas_btn)

        restore_btn = QPushButton("  ↩  Restore from file…")
        restore_btn.setFixedHeight(34)
        restore_btn.setStyleSheet(self._danger_btn_css())
        restore_btn.clicked.connect(self._do_restore)
        btn_row.addWidget(restore_btn)

        btn_row.addStretch()
        card_layout.addLayout(btn_row)
        layout.addWidget(card)

        # ── History table ──
        hist_lbl = QLabel("Backup History")
        hist_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
        )
        layout.addWidget(hist_lbl)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Date & Time", "File", "Size", "Location", ""]
        )
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive
        )
        self._table.horizontalHeader().setStretchLastSection(False)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(1, 220)
        self._table.setColumnWidth(2, 80)
        self._table.setColumnWidth(3, 300)
        self._table.setColumnWidth(4, 100)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(
            QTableWidget.SelectionBehavior.SelectRows
        )
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(f"""
            QTableWidget {{
                background: {THEME['bg_card']};
                alternate-background-color: {THEME['bg_input']};
                gridline-color: {THEME['border']};
                color: {THEME['text_primary']};
                border: none;
            }}
            QHeaderView::section {{
                background: {THEME['bg_input']};
                color: {THEME['text_secondary']};
                padding: 6px;
                border: none;
                font-size: 11px;
            }}
        """)
        layout.addWidget(self._table, 1)

        self._refresh_table()

    # ── Backup actions ────────────────────────────────────────────────────────

    def _do_backup(self):
        self._start_backup("")

    def _do_backup_saveas(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Select Backup Destination", str(Path.home())
        )
        if folder:
            self._start_backup(folder)

    def _start_backup(self, dest_dir: str):
        self._backup_btn.setEnabled(False)
        self._set_status("Creating backup…")
        self._thread = BackupThread(self._mgr, dest_dir)
        self._thread.finished.connect(self._on_backup_done)
        self._thread.error.connect(self._on_backup_error)
        self._thread.start()

    def _on_backup_done(self, path: str):
        self._backup_btn.setEnabled(True)
        self._last_lbl.setText(self._mgr.last_backup_display)
        self._set_status(f"Saved: {Path(path).name}")
        self._refresh_table()

    def _on_backup_error(self, msg: str):
        self._backup_btn.setEnabled(True)
        self._set_status("")
        QMessageBox.critical(self, "Backup Failed", msg)

    # ── Restore action ────────────────────────────────────────────────────────

    def _do_restore(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Backup File", str(Path.home()),
            "SQLite Database (*.db);;All Files (*)"
        )
        if not path:
            return

        reply = QMessageBox.question(
            self, "Confirm Restore",
            f"This will replace the current database with:\n{path}\n\n"
            "A safety copy of the current database will be made first.\n\n"
            "The application must be restarted after restore.\n\n"
            "Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            safety = self._mgr.restore_backup(path)
            QMessageBox.information(
                self, "Restore Complete",
                f"Database restored successfully.\n\n"
                f"Safety copy saved to:\n{safety}\n\n"
                "Please restart the application now."
            )
        except Exception as e:
            QMessageBox.critical(self, "Restore Failed", str(e))

    # ── Table helpers ─────────────────────────────────────────────────────────

    def _refresh_table(self):
        entries = self._mgr.list_backups()
        self._table.setRowCount(len(entries))
        for row, entry in enumerate(entries):
            try:
                dt_str = datetime.fromisoformat(
                    entry["timestamp"]
                ).strftime("%d %b %Y  %H:%M")
            except Exception:
                dt_str = entry.get("timestamp", "")

            bpath  = Path(entry.get("path", ""))
            size   = _fmt_size(entry.get("size_bytes", 0))
            exists = bpath.exists()

            self._table.setItem(row, 0, QTableWidgetItem(dt_str))
            self._table.setItem(row, 1, QTableWidgetItem(bpath.name))
            sz_item = QTableWidgetItem(size)
            sz_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._table.setItem(row, 2, sz_item)
            self._table.setItem(
                row, 3,
                QTableWidgetItem(str(bpath.parent) if exists else "(file missing)")
            )

            open_btn = QPushButton("Open Folder")
            open_btn.setFixedHeight(24)
            open_btn.setEnabled(exists)
            open_btn.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    color: {THEME['accent']};
                    border: none;
                    font-size: 11px;
                    text-decoration: underline;
                }}
                QPushButton:hover {{ color: {THEME['accent_hover']}; }}
                QPushButton:disabled {{ color: {THEME['text_dim']}; }}
            """)
            folder = str(bpath.parent)
            open_btn.clicked.connect(
                lambda _, f=folder: self._open_folder(f)
            )
            self._table.setCellWidget(row, 4, open_btn)

        self._table.resizeRowsToContents()

    def _open_folder(self, folder: str):
        try:
            os.startfile(folder)
        except Exception as e:
            QMessageBox.warning(self, "Cannot Open Folder", str(e))

    def _set_status(self, msg: str):
        self._status_lbl.setText(msg)

    def refresh(self):
        self._last_lbl.setText(self._mgr.last_backup_display)
        self._refresh_table()

    # ── Style helpers ─────────────────────────────────────────────────────────

    def _primary_btn_css(self) -> str:
        return f"""
            QPushButton {{
                background: {THEME['accent']};
                color: #000;
                border: none;
                border-radius: 6px;
                padding: 0px 16px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{ background: {THEME['accent_hover']}; }}
            QPushButton:disabled {{ background: {THEME['text_dim']}; color: #555; }}
        """

    def _secondary_btn_css(self) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {THEME['text_secondary']};
                border: 1px solid {THEME['border']};
                border-radius: 6px;
                padding: 0px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {THEME['accent']};
                color: {THEME['accent']};
            }}
        """

    def _danger_btn_css(self) -> str:
        return f"""
            QPushButton {{
                background: transparent;
                color: {THEME['danger']};
                border: 1px solid {THEME['danger']};
                border-radius: 6px;
                padding: 0px 16px;
                font-size: 12px;
            }}
            QPushButton:hover {{ background: {THEME['danger_dim']}; }}
        """
