"""User Manual page — downloads the current manual PDF and opens it.

Registered as a normal page so it appears in BOTH nav modes (sidebar flyout
and the tile launcher) under Tools. Always fetches the latest PDF from the
server, so the manual stays in sync with the app rather than shipping a stale
copy inside the installer.
"""
from __future__ import annotations

import urllib.request
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, QStandardPaths
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QApplication, QMessageBox,
)

from ui.theme import THEME

_MANUAL_URL = {
    "accgenie": "https://apps.ai-consultants.in/downloads/AccountsHQ-Manual.pdf",
    "rwagenie": "https://apps.ai-consultants.in/downloads/RWAHQ-Manual.pdf",
}


def _manual_url() -> str:
    try:
        from core.app_release import current_product
        return _MANUAL_URL.get(current_product(), _MANUAL_URL["accgenie"])
    except Exception:
        return _MANUAL_URL["accgenie"]


class ManualPage(QWidget):
    """Tools ▸ Help ▸ User Manual — download + open the current manual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.setSpacing(12)

        title = QLabel("User Manual")
        title.setStyleSheet(
            f"font-size:20px; font-weight:bold; color:{THEME['text_primary']};")
        lay.addWidget(title)

        desc = QLabel(
            "Download the latest user manual (PDF) and open it. The newest "
            "version is fetched from the server each time, so it always matches "
            "the current app — and you keep an offline copy in your Downloads "
            "folder.")
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:13px;")
        lay.addWidget(desc)

        btn = QPushButton("⬇  Download & open the manual")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(42)
        btn.setStyleSheet(f"""
            QPushButton {{
                background:{THEME['accent']}; color:white; border:none;
                border-radius:8px; font-size:13px; font-weight:bold; padding:0 18px;
            }}
            QPushButton:hover {{ background:{THEME['accent']}; opacity:0.9; }}
        """)
        btn.clicked.connect(self._download)
        lay.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color:{THEME['text_dim']}; font-size:12px;")
        lay.addWidget(self._status)
        lay.addStretch()

    def _download(self) -> None:
        url = _manual_url()
        fname = url.rsplit("/", 1)[-1] or "manual.pdf"
        dl_dir = (QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.DownloadLocation)
            or str(Path.home() / "Downloads"))
        dest = Path(dl_dir) / fname

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._status.setText("Downloading the latest manual…")
        QApplication.processEvents()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "BooksHQ"})
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            dest.write_bytes(data)
        except Exception as exc:
            QApplication.restoreOverrideCursor()
            self._status.setText("")
            QMessageBox.warning(
                self, "User Manual",
                "Could not download the manual.\n\n"
                f"{exc}\n\nCheck your internet connection and try again.")
            return
        QApplication.restoreOverrideCursor()
        self._status.setText(f"Saved to {dest}  —  opening…")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest)))
