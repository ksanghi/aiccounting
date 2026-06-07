"""
In-app document preview for the Document Inbox.

DocumentPreview renders the selected file INSIDE the app (no external
window, so AHQ never loses focus) — images and PDFs as pictures with
Fit / zoom controls, data files (Excel/CSV/Word/text) as their extracted
text. Rendering runs off the UI thread so the queue stays responsive.

Used by ui/document_inbox_page.py beside the editable voucher panel, so
the reviewer eyeballs the document and the proposed voucher side by side.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QPlainTextEdit,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QImage, QPixmap

from ui.theme import THEME

_IMG_EXT = {".jpg", ".jpeg", ".png"}
_PDF_EXT = {".pdf"}

# Render PDFs/scans at a high-ish DPI so zooming in stays sharp.
_PDF_DPI = 180


def _pil_to_qimage(pil) -> QImage:
    """Convert a PIL image to a QImage that owns its own buffer."""
    pil = pil.convert("RGBA")
    data = pil.tobytes("raw", "RGBA")
    qim = QImage(data, pil.width, pil.height, QImage.Format.Format_RGBA8888)
    return qim.copy()


class PreviewThread(QThread):
    """Render a document to page-images, or fall back to extracted text.
    QImages are built here (safe off-thread); QPixmaps are made on the GUI
    thread by the receiver."""
    images = Signal(list)   # list[QImage]
    text   = Signal(str)
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            ext = Path(self.path).suffix.lower()
            if ext in _IMG_EXT:
                qim = QImage(self.path)
                if qim.isNull():
                    self.failed.emit("Could not load image.")
                    return
                self.images.emit([qim])
                return

            if ext in _PDF_EXT:
                import pdfplumber
                imgs = []
                with pdfplumber.open(self.path) as pdf:
                    for page in pdf.pages[:15]:
                        pil = page.to_image(resolution=_PDF_DPI).original
                        imgs.append(_pil_to_qimage(pil))
                if imgs:
                    self.images.emit(imgs)
                else:
                    self.failed.emit("Empty PDF.")
                return

            # Data files → show the text we'd extract anyway.
            from ai.document_parser import DocumentParser
            res = DocumentParser().parse(self.path)
            if res.success and res.full_text.strip():
                self.text.emit(res.full_text)
            else:
                self.text.emit("(No readable text in this file.)")
        except Exception as e:
            self.failed.emit(str(e))


class DocumentPreview(QWidget):
    """In-app preview pane with a Fit / zoom toolbar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(280)
        self._images: list[QImage] = []
        self._zoom = 1.0          # multiplier applied to the fit-width
        self._fit = True          # True = scale each page to the viewport width
        self._thread: PreviewThread | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(4)

        # Zoom toolbar
        self._bar = QHBoxLayout()
        self._bar.setContentsMargins(0, 0, 0, 0)
        self._fit_btn = self._tool("Fit", self._do_fit)
        self._out_btn = self._tool("−", lambda: self._zoom_by(1 / 1.25))
        self._in_btn = self._tool("＋", lambda: self._zoom_by(1.25))
        self._bar.addWidget(self._fit_btn)
        self._bar.addWidget(self._out_btn)
        self._bar.addWidget(self._in_btn)
        self._bar.addStretch()
        self._page_lbl = QLabel("")
        self._page_lbl.setStyleSheet(
            f"color:{THEME['text_dim']};font-size:10px;"
        )
        self._bar.addWidget(self._page_lbl)
        outer.addLayout(self._bar)

        # Scroll area holding the rendered pages / text
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            f"QScrollArea {{ border:1px solid {THEME['border']}; "
            f"border-radius:8px; background:{THEME['bg_input']}; }}"
        )
        self._host = QWidget()
        self._lay = QVBoxLayout(self._host)
        self._lay.setContentsMargins(8, 8, 8, 8)
        self._lay.setSpacing(8)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._host)
        outer.addWidget(self._scroll, 1)

        self._set_zoom_enabled(False)
        self._show_message("No document selected.")

    # ── public ────────────────────────────────────────────────────────────
    def show_file(self, path: str):
        if not path or not Path(path).exists():
            self._images = []
            self._set_zoom_enabled(False)
            self._show_message("File not found.")
            return
        self._images = []
        self._fit = True
        self._zoom = 1.0
        self._set_zoom_enabled(False)
        self._show_message("Loading preview…")
        self._thread = PreviewThread(path)
        self._thread.images.connect(self._on_images)
        self._thread.text.connect(self._on_text)
        self._thread.failed.connect(
            lambda m: self._show_message(f"Cannot preview this file.\n{m}")
        )
        self._thread.start()

    def clear(self):
        self._images = []
        self._set_zoom_enabled(False)
        self._page_lbl.setText("")
        self._show_message("No document selected.")

    # ── toolbar ───────────────────────────────────────────────────────────
    def _tool(self, text: str, slot) -> QPushButton:
        b = QPushButton(text)
        b.setFixedSize(34, 24)
        b.clicked.connect(slot)
        return b

    def _set_zoom_enabled(self, on: bool):
        for b in (self._fit_btn, self._out_btn, self._in_btn):
            b.setEnabled(on)

    def _do_fit(self):
        self._fit = True
        self._zoom = 1.0
        self._render_images()

    def _zoom_by(self, factor: float):
        self._fit = False
        self._zoom = max(0.25, min(self._zoom * factor, 6.0))
        self._render_images()

    # ── internals ─────────────────────────────────────────────────────────
    def _wipe(self):
        while self._lay.count():
            it = self._lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _show_message(self, msg: str):
        self._wipe()
        lbl = QLabel(msg)
        lbl.setWordWrap(True)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            f"color:{THEME['text_dim']};font-size:12px;padding:24px;"
        )
        self._lay.addWidget(lbl)

    def _on_images(self, images: list):
        self._images = images
        self._set_zoom_enabled(True)
        self._page_lbl.setText(
            f"{len(images)} page(s)" if len(images) != 1 else ""
        )
        self._render_images()

    def _render_images(self):
        if not self._images:
            return
        self._wipe()
        base = max(120, self._scroll.viewport().width() - 24)
        target = int(base * self._zoom) if not self._fit else base
        for qim in self._images:
            pix = QPixmap.fromImage(qim)
            pix = pix.scaledToWidth(
                target, Qt.TransformationMode.SmoothTransformation
            )
            lbl = QLabel()
            lbl.setPixmap(pix)
            lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            self._lay.addWidget(lbl)

    def _on_text(self, text: str):
        self._images = []
        self._set_zoom_enabled(False)
        self._page_lbl.setText("")
        self._wipe()
        box = QPlainTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        box.setStyleSheet(
            f"QPlainTextEdit {{ border:none; background:transparent; "
            f"color:{THEME['text_primary']}; font-family:Consolas,monospace; "
            f"font-size:11px; }}"
        )
        self._lay.addWidget(box)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        # Re-fit on resize so the page always fills the width in Fit mode.
        if self._fit and self._images:
            self._render_images()
