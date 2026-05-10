"""
Shared Widgets
  - CalculatorWidget  : floating calculator (Alt+C anywhere)
  - LedgerSearchEdit  : auto-complete ledger search with inline add (F2)
  - QuickAddLedger    : modal to create a ledger on the fly
  - AmountEdit        : numeric input with comma formatting
  - FieldLabel        : styled label with optional required star
  - StatusPill        : coloured badge (Dr / Cr / voucher type)
"""
from PyQt6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLineEdit, QPushButton, QLabel, QCompleter, QComboBox,
    QFrame, QSizePolicy, QFormLayout, QApplication, QMessageBox,
    QDoubleSpinBox
)
from PyQt6.QtCore import (
    Qt, QStringListModel, pyqtSignal, QTimer, QEvent, QPoint
)
from PyQt6.QtGui import QFont, QKeySequence, QShortcut, QColor, QPalette

from ui.theme import THEME


# ── Helpers ───────────────────────────────────────────────────────────────────

def make_label(text: str, required=False, dim=False) -> QLabel:
    lbl = QLabel(text + (" *" if required else ""))
    lbl.setObjectName("field_label")
    if dim:
        lbl.setStyleSheet(f"color: {THEME['text_dim']};")
    return lbl


def make_separator() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.HLine)
    return line


# ── Amount Edit ───────────────────────────────────────────────────────────────

class AmountEdit(QDoubleSpinBox):
    """Numeric spinbox formatted as Indian currency ₹1,23,456.78"""

    focused = pyqtSignal(object)  # emits self when this field receives focus

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDecimals(2)
        self.setMaximum(99_99_99_999.99)
        self.setMinimum(0.0)
        self.setGroupSeparatorShown(True)
        self.setPrefix("₹ ")
        self.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.setFixedHeight(36)
        self.setAlignment(Qt.AlignmentFlag.AlignRight)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focused.emit(self)
        QTimer.singleShot(0, self.selectAll)

    def keyPressEvent(self, event):
        if self.value() == 0 and event.text().isdigit():
            self.setValue(0)
            self.selectAll()
        super().keyPressEvent(event)

    def paste_amount(self, value: float):
        self.setValue(value)


# ── Status Pill ───────────────────────────────────────────────────────────────

class StatusPill(QLabel):
    """Small colour-coded badge."""

    def __init__(self, text: str, colour: str, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(f"""
            background-color: {colour}22;
            color: {colour};
            border: 1px solid {colour}55;
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 10px;
            font-weight: bold;
        """)
        self.setFixedHeight(20)


# ── Calculator ────────────────────────────────────────────────────────────────

class CalculatorWidget(QDialog):
    """
    Floating calculator.  Opens with Alt+C.
    Has a "Paste to field" button that sends the result
    to the last focused AmountEdit.
    """
    result_ready = pyqtSignal(float)   # emitted when user hits Paste

    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.setWindowTitle("Calculator")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._expr = ""
        self._build_ui()
        self.setFixedSize(260, 340)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        # Container card
        card = QFrame()
        card.setStyleSheet(f"""
            QFrame {{
                background-color: {THEME['bg_card']};
                border: 1px solid {THEME['border_focus']};
                border-radius: 12px;
            }}
        """)
        layout = QVBoxLayout(card)
        layout.setSpacing(6)
        layout.setContentsMargins(12, 12, 12, 12)

        # Title bar
        title_row = QHBoxLayout()
        title = QLabel("⌨  Calculator")
        title.setStyleSheet(f"color: {THEME['text_secondary']}; font-size:10px; font-weight:bold;")
        close_btn = QPushButton("✕")
        close_btn.setObjectName("btn_icon")
        close_btn.setFixedSize(20, 20)
        close_btn.clicked.connect(self.hide)
        title_row.addWidget(title)
        title_row.addStretch()
        title_row.addWidget(close_btn)
        layout.addLayout(title_row)

        # Display
        self.display = QLabel("0")
        self.display.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.display.setFixedHeight(52)
        self.display.setStyleSheet(f"""
            background: {THEME['bg_input']};
            border-radius: 8px;
            padding: 6px 12px;
            font-size: 22px;
            font-weight: bold;
            color: {THEME['text_primary']};
        """)
        self.expr_label = QLabel("")
        self.expr_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.expr_label.setStyleSheet(f"color: {THEME['text_dim']}; font-size: 10px; padding-right: 4px;")
        layout.addWidget(self.expr_label)
        layout.addWidget(self.display)

        # Button grid
        grid = QGridLayout()
        grid.setSpacing(5)

        btn_defs = [
            ("C",   0, 0, THEME["danger"]),
            ("⌫",   0, 1, THEME["warning"]),
            ("%",   0, 2, THEME["text_secondary"]),
            ("÷",   0, 3, THEME["accent"]),
            ("7",   1, 0, None),
            ("8",   1, 1, None),
            ("9",   1, 2, None),
            ("×",   1, 3, THEME["accent"]),
            ("4",   2, 0, None),
            ("5",   2, 1, None),
            ("6",   2, 2, None),
            ("−",   2, 3, THEME["accent"]),
            ("1",   3, 0, None),
            ("2",   3, 1, None),
            ("3",   3, 2, None),
            ("+",   3, 3, THEME["accent"]),
            ("±",   4, 0, None),
            ("0",   4, 1, None),
            (".",   4, 2, None),
            ("=",   4, 3, THEME["success"]),
        ]

        for (label, row, col, colour) in btn_defs:
            btn = QPushButton(label)
            btn.setFixedHeight(38)
            c = colour or THEME["bg_hover"]
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {c}{'33' if not colour else '22' if colour != THEME['bg_hover'] else ''};
                    color: {colour if colour else THEME['text_primary']};
                    border: 1px solid {c}{'44' if colour else THEME['border']};
                    border-radius: 7px;
                    font-size: 14px;
                    font-weight: {'bold' if colour else 'normal'};
                }}
                QPushButton:hover {{
                    background-color: {c}44;
                }}
                QPushButton:pressed {{
                    background-color: {c}66;
                }}
            """)
            btn.clicked.connect(lambda _, l=label: self._on_btn(l))
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)

        # Paste button
        paste_btn = QPushButton("⬆  Paste to amount field")
        paste_btn.setObjectName("btn_primary")
        paste_btn.clicked.connect(self._paste)
        layout.addWidget(paste_btn)

        outer.addWidget(card)

        # Drag support
        self._drag_pos = None
        card.mousePressEvent   = self._mouse_press
        card.mouseMoveEvent    = self._mouse_move
        card.mouseReleaseEvent = self._mouse_release

    def _mouse_press(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def _mouse_move(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def _mouse_release(self, _):
        self._drag_pos = None

    def _on_btn(self, label: str):
        if label == "C":
            self._expr = ""
            self.display.setText("0")
            self.expr_label.setText("")
        elif label == "⌫":
            self._expr = self._expr[:-1]
            self.display.setText(self._expr or "0")
        elif label == "=":
            self._evaluate()
        elif label == "±":
            if self._expr and self._expr[0] == "-":
                self._expr = self._expr[1:]
            else:
                self._expr = "-" + self._expr
            self.display.setText(self._expr or "0")
        elif label == "%":
            try:
                val = eval(self._expr.replace("×", "*").replace("÷", "/").replace("−", "-"))
                self._expr = str(val / 100)
                self.display.setText(self._expr)
            except Exception:
                pass
        else:
            map_ = {"×": "*", "÷": "/", "−": "-"}
            self._expr += map_.get(label, label)
            self.display.setText(self._expr)

    def _evaluate(self):
        try:
            expr = self._expr.replace("×", "*").replace("÷", "/").replace("−", "-")
            result = eval(expr)
            self.expr_label.setText(self._expr + " =")
            self._expr = str(round(result, 2))
            self.display.setText(f"{result:,.2f}")
        except Exception:
            self.display.setText("Error")
            self._expr = ""

    def _paste(self):
        try:
            val = float(self._expr or "0")
            self.result_ready.emit(val)
            self.hide()
        except ValueError:
            pass

    def connect_to(self, widget):
        """Point result_ready at widget.paste_amount (called via AmountEdit.focused signal)."""
        try:
            self.result_ready.disconnect()
        except TypeError:
            pass
        self.result_ready.connect(widget.paste_amount)

    def keyPressEvent(self, e):
        key_map = {
            Qt.Key.Key_0: "0", Qt.Key.Key_1: "1", Qt.Key.Key_2: "2",
            Qt.Key.Key_3: "3", Qt.Key.Key_4: "4", Qt.Key.Key_5: "5",
            Qt.Key.Key_6: "6", Qt.Key.Key_7: "7", Qt.Key.Key_8: "8",
            Qt.Key.Key_9: "9", Qt.Key.Key_Period: ".", Qt.Key.Key_Plus: "+",
            Qt.Key.Key_Minus: "−", Qt.Key.Key_Asterisk: "×",
            Qt.Key.Key_Slash: "÷", Qt.Key.Key_Percent: "%",
            Qt.Key.Key_Return: "=", Qt.Key.Key_Enter: "=",
            Qt.Key.Key_Backspace: "⌫", Qt.Key.Key_Escape: None,
        }
        label = key_map.get(e.key())
        if label is None:
            self.hide()
        elif label:
            self._on_btn(label)


# ── Quick Add Ledger Dialog ───────────────────────────────────────────────────

class QuickAddLedgerDialog(QDialog):
    """
    Add or edit a ledger account.

    - F2 from a ledger search → create mode (existing_ledger_id=None).
    - F3 / pencil button on a ledger search → edit mode (existing_ledger_id
      set, fields pre-populated, save calls update_ledger).
    """
    ledger_created = pyqtSignal(int, str)   # id, name (create mode)
    ledger_updated = pyqtSignal(int, str)   # id, name (edit mode)

    def __init__(self, tree, initial_name: str = "", parent=None,
                 allowed_group_ids=None, existing_ledger_id: int | None = None):
        super().__init__(parent)
        self.tree = tree
        self._allowed_group_ids = allowed_group_ids or []
        self._existing_id = existing_ledger_id
        self._existing = (
            tree.get_ledger(existing_ledger_id)
            if existing_ledger_id else None
        )
        self.setWindowTitle(
            "Edit Ledger" if self._existing else "New Ledger"
        )
        self.setMinimumWidth(440)
        self.setModal(True)
        # In edit mode, prefill name from the existing record (overrides any
        # initial_name passed in).
        prefill_name = (
            self._existing["name"] if self._existing else initial_name
        )
        self._build_ui(prefill_name)
        if self._existing:
            self._populate_from_existing()

    def _build_ui(self, initial_name: str):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # Header
        is_edit = self._existing is not None
        hdr = QLabel(
            "✎ Edit Ledger Account" if is_edit else "+ Add Ledger Account"
        )
        hdr.setStyleSheet(f"font-size:14px; font-weight:bold; color:{THEME['accent']};")
        layout.addWidget(hdr)
        layout.addWidget(make_separator())

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Name
        self.name_edit = QLineEdit(initial_name)
        self.name_edit.setPlaceholderText("e.g. HDFC Current Account")
        form.addRow(make_label("Ledger Name", required=True), self.name_edit)

        # Group
        self.group_combo = QComboBox()
        rows = self.tree.db.execute(
            "SELECT name FROM account_groups WHERE company_id=? ORDER BY name",
            (self.tree.company_id,)
        ).fetchall()
        groups = [r["name"] for r in rows]
        if self._allowed_group_ids:
            allowed_rows = self.tree.db.execute(
                "SELECT name FROM account_groups WHERE id IN ({})".format(
                    ",".join("?" * len(self._allowed_group_ids))
                ),
                self._allowed_group_ids
            ).fetchall()
            allowed_names = {r["name"] for r in allowed_rows}
            groups = [g for g in groups if g in allowed_names]
        self.group_combo.addItems(groups)
        if self._allowed_group_ids and groups:
            self.group_combo.setCurrentIndex(0)
        else:
            idx = self.group_combo.findText("Indirect Expenses")
            if idx >= 0:
                self.group_combo.setCurrentIndex(idx)
        form.addRow(make_label("Under Group", required=True), self.group_combo)

        # Bank-only fields (Account No / IFSC / Bank Name) — visible only when
        # the chosen group is a bank-style group. Show/hide on group change.
        self.acct_edit = QLineEdit()
        self.acct_edit.setPlaceholderText("e.g. 912010012345678")
        self._acct_label = make_label("Account Number")
        form.addRow(self._acct_label, self.acct_edit)

        self.ifsc_edit = QLineEdit()
        self.ifsc_edit.setPlaceholderText("e.g. HDFC0001234")
        self._ifsc_label = make_label("IFSC")
        form.addRow(self._ifsc_label, self.ifsc_edit)

        self.bank_name_edit = QLineEdit()
        self.bank_name_edit.setPlaceholderText("e.g. HDFC Bank")
        self._bank_name_label = make_label("Bank Name")
        form.addRow(self._bank_name_label, self.bank_name_edit)

        self.group_combo.currentTextChanged.connect(self._on_group_changed)
        self._on_group_changed(self.group_combo.currentText())

        # Opening balance
        self.ob_edit = AmountEdit()
        form.addRow(make_label("Opening Balance"), self.ob_edit)

        # Opening type
        self.ob_type = QComboBox()
        self.ob_type.addItems(["Dr", "Cr"])
        form.addRow(make_label("Opening Type"), self.ob_type)

        # GSTIN
        self.gstin_edit = QLineEdit()
        self.gstin_edit.setPlaceholderText("Optional — auto-fills state code")
        self.gstin_edit.textChanged.connect(self._on_gstin_change)
        form.addRow(make_label("GSTIN"), self.gstin_edit)

        # PAN
        self.pan_edit = QLineEdit()
        self.pan_edit.setPlaceholderText("Optional")
        form.addRow(make_label("PAN"), self.pan_edit)

        # TDS
        tds_row = QHBoxLayout()
        self.tds_combo = QComboBox()
        self.tds_combo.addItem("Not applicable")
        for sec, info in {
            "194C": "Contractor", "194H": "Commission",
            "194I": "Rent", "194J": "Professional",
            "194A": "Interest", "194Q": "Purchases"
        }.items():
            self.tds_combo.addItem(f"{sec} — {info}", sec)
        self.tds_rate = QDoubleSpinBox()
        self.tds_rate.setSuffix(" %")
        self.tds_rate.setMaximum(30)
        self.tds_rate.setValue(10)
        self.tds_rate.setFixedWidth(80)
        self.tds_rate.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.tds_combo.currentIndexChanged.connect(self._on_tds_change)
        tds_row.addWidget(self.tds_combo, 3)
        tds_row.addWidget(self.tds_rate, 1)
        form.addRow(make_label("TDS Section"), tds_row)
        self._on_tds_change(0)

        layout.addLayout(form)
        layout.addWidget(make_separator())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save_label = (
            "Update Ledger" if self._existing else "Create Ledger"
        )
        save = QPushButton(save_label)
        save.setObjectName("btn_primary")
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        layout.addLayout(btn_row)

        self.name_edit.setFocus()

    # ── Helpers ──────────────────────────────────────────────────────────

    @staticmethod
    def _is_bank_group(group_name: str) -> bool:
        return "bank accounts" in (group_name or "").lower()

    @staticmethod
    def _is_cash_group(group_name: str) -> bool:
        return "cash-in-hand" in (group_name or "").lower()

    def _on_group_changed(self, group_name: str):
        is_bank = self._is_bank_group(group_name)
        for w in (
            self._acct_label, self.acct_edit,
            self._ifsc_label, self.ifsc_edit,
            self._bank_name_label, self.bank_name_edit,
        ):
            w.setVisible(is_bank)

    def _populate_from_existing(self):
        e = self._existing
        if not e:
            return
        # Group
        idx = self.group_combo.findText(e.get("group_name") or "")
        if idx >= 0:
            self.group_combo.setCurrentIndex(idx)
        # Opening balance + type
        try:
            self.ob_edit.setValue(float(e.get("opening_balance") or 0))
        except Exception:
            pass
        ob_type = (e.get("opening_type") or "Dr").strip() or "Dr"
        ot_idx = self.ob_type.findText(ob_type)
        if ot_idx >= 0:
            self.ob_type.setCurrentIndex(ot_idx)
        # Tax fields
        self.gstin_edit.setText(e.get("gstin") or "")
        self.pan_edit.setText(e.get("pan") or "")
        # TDS
        section = e.get("tds_section")
        if section and (e.get("is_tds_applicable") or 0):
            for i in range(self.tds_combo.count()):
                if self.tds_combo.itemData(i) == section:
                    self.tds_combo.setCurrentIndex(i)
                    break
            try:
                self.tds_rate.setValue(float(e.get("tds_rate") or 0))
            except Exception:
                pass
        # Bank fields
        self.acct_edit.setText(e.get("account_number") or "")
        self.ifsc_edit.setText(e.get("ifsc") or "")
        self.bank_name_edit.setText(e.get("bank_name") or "")

    def _on_gstin_change(self, text: str):
        """Auto-set group hint based on GSTIN state."""
        pass  # extend later

    def _on_tds_change(self, idx: int):
        self.tds_rate.setEnabled(idx > 0)

    def _save(self):
        name  = self.name_edit.text().strip()
        group = self.group_combo.currentText()
        if not name:
            self.name_edit.setProperty("error", "true")
            self.name_edit.setStyleSheet(f"border: 1px solid {THEME['border_error']};")
            return

        kwargs = {
            "opening_balance": self.ob_edit.value(),
            "opening_type":    self.ob_type.currentText(),
        }
        if self._is_bank_group(group):
            kwargs["is_bank"] = True
            kwargs["is_cash"] = False
        elif self._is_cash_group(group):
            kwargs["is_cash"] = True
            kwargs["is_bank"] = False
        else:
            kwargs["is_bank"] = False
            kwargs["is_cash"] = False
        if self.gstin_edit.text().strip():
            kwargs["gstin"]      = self.gstin_edit.text().strip()
            kwargs["state_code"] = self.gstin_edit.text().strip()[:2]
        else:
            kwargs["gstin"] = None
            kwargs["state_code"] = None
        if self.pan_edit.text().strip():
            kwargs["pan"] = self.pan_edit.text().strip()
        else:
            kwargs["pan"] = None
        if self.tds_combo.currentIndex() > 0:
            kwargs["is_tds_applicable"] = True
            kwargs["tds_section"]       = self.tds_combo.currentData()
            kwargs["tds_rate"]          = self.tds_rate.value()
        else:
            kwargs["is_tds_applicable"] = False
            kwargs["tds_section"] = None
            kwargs["tds_rate"] = None
        # Bank fields — only meaningful when group is bank
        if self._is_bank_group(group):
            kwargs["account_number"] = self.acct_edit.text().strip() or None
            kwargs["ifsc"]           = self.ifsc_edit.text().strip() or None
            kwargs["bank_name"]      = self.bank_name_edit.text().strip() or None
        else:
            kwargs["account_number"] = None
            kwargs["ifsc"] = None
            kwargs["bank_name"] = None

        try:
            if self._existing:
                kwargs["name"]       = name
                kwargs["group_name"] = group
                self.tree.update_ledger(self._existing_id, **kwargs)
                self.ledger_updated.emit(self._existing_id, name)
            else:
                lid = self.tree.add_ledger(name, group, **kwargs)
                self.ledger_created.emit(lid, name)
            self.accept()
        except Exception as e:
            QMessageBox.warning(self, "Error", str(e))


# ── Ledger Search Edit ────────────────────────────────────────────────────────

class LedgerSearchEdit(QWidget):
    """
    Auto-complete ledger search field.
    F2      → open QuickAddLedger dialog
    Alt+C  → open calculator
    Emits ledger_selected(id, name) when a match is chosen.
    """
    ledger_selected = pyqtSignal(int, str, dict)   # id, name, full ledger dict
    add_requested   = pyqtSignal(str)              # user wants to create ledger

    def __init__(self, tree, calculator: CalculatorWidget,
                 placeholder="Type ledger name…", parent=None):
        super().__init__(parent)
        self.tree       = tree
        self.calculator = calculator
        self._ledger_map: dict[str, dict] = {}
        self._selected_id: int | None = None

        self.setFixedHeight(36)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setFixedHeight(36)
        self.search.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        # Inherit the global QLineEdit / :focus styles — gives a clean,
        # complete focus ring instead of a half-coloured merged border.

        self._add_btn = self._make_chip_btn(
            "F2", "F2 — Create new ledger on the fly"
        )
        self._add_btn.clicked.connect(self._open_add_dialog)

        self._edit_btn = self._make_chip_btn(
            "F3", "F3 — Edit the selected ledger"
        )
        self._edit_btn.clicked.connect(self._open_edit_dialog)

        layout.addWidget(self.search)
        layout.addWidget(self._add_btn)
        layout.addWidget(self._edit_btn)

        # Completer
        self._model = QStringListModel()
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setMaxVisibleItems(10)
        self._completer.activated.connect(self._on_completion)
        self.search.setCompleter(self._completer)

        # Shortcuts
        self._f2 = QShortcut(QKeySequence("F2"), self.search)
        self._f2.activated.connect(self._open_add_dialog)
        self._f3 = QShortcut(QKeySequence("F3"), self.search)
        self._f3.activated.connect(self._open_edit_dialog)

        self.search.textChanged.connect(self._on_text_changed)
        self.reload_ledgers()

    @staticmethod
    def _make_chip_btn(label: str, tooltip: str) -> QPushButton:
        b = QPushButton(label)
        b.setFixedSize(38, 36)
        b.setToolTip(tooltip)
        b.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['bg_hover']};
                border: 1px solid {THEME['border']};
                border-radius: 7px;
                color: {THEME['text_secondary']};
                font-size: 10px;
                font-weight: bold;
                min-height: 0;
                padding: 0;
            }}
            QPushButton:hover {{
                background: {THEME['accent_dim']};
                color: {THEME['accent']};
                border-color: {THEME['accent']};
            }}
        """)
        return b

    def _open_edit_dialog(self):
        lid = self.selected_id
        if not lid:
            QMessageBox.information(
                self, "No ledger selected",
                "Pick a ledger from the list, then press F3 to edit it.",
            )
            return
        dlg = QuickAddLedgerDialog(
            self.tree, parent=self, existing_ledger_id=lid,
        )
        dlg.ledger_updated.connect(self._on_ledger_updated)
        dlg.exec()

    def _on_ledger_updated(self, lid: int, name: str):
        self.reload_ledgers()
        self.search.setText(name)
        self._selected_id = lid
        ldg = self._ledger_map.get(name, {"id": lid, "name": name})
        self.ledger_selected.emit(lid, name, ldg)

    def reload_ledgers(self):
        """Refresh from DB — call after a ledger is created."""
        ledgers = self.tree.get_all_ledgers()
        self._ledger_map = {l["name"]: l for l in ledgers}
        self._model.setStringList(sorted(self._ledger_map.keys()))

    def _on_text_changed(self, text: str):
        if text not in self._ledger_map:
            self._selected_id = None

    def _on_completion(self, text: str):
        ldg = self._ledger_map.get(text)
        if ldg:
            self._selected_id = ldg["id"]
            self.search.setText(text)
            self.ledger_selected.emit(ldg["id"], text, ldg)

    def _open_add_dialog(self):
        initial = self.search.text().strip()
        dlg = QuickAddLedgerDialog(self.tree, initial_name=initial, parent=self)
        dlg.ledger_created.connect(self._on_ledger_created)
        dlg.exec()

    def _on_ledger_created(self, lid: int, name: str):
        self.reload_ledgers()
        self.search.setText(name)
        ldg = self._ledger_map.get(name, {"id": lid, "name": name})
        self._selected_id = lid
        self.ledger_selected.emit(lid, name, ldg)

    @property
    def selected_id(self) -> int | None:
        if self._selected_id is not None:
            return self._selected_id
        text = self.search.text().strip()
        # Exact match
        ldg = self._ledger_map.get(text)
        if ldg:
            return ldg["id"]
        # Case-insensitive fallback
        text_lower = text.lower()
        for name, l in self._ledger_map.items():
            if name.lower() == text_lower:
                return l["id"]
        return None

    @property
    def selected_ledger(self) -> dict | None:
        return self._ledger_map.get(self.search.text().strip())

    def clear(self):
        self.search.clear()
        self._selected_id = None

    def set_ledger(self, name: str):
        self.search.setText(name)
        ldg = self._ledger_map.get(name)
        if ldg:
            self._selected_id = ldg["id"]


# ── Filtered Ledger Search Edit ───────────────────────────────────────────────

class FilteredLedgerSearchEdit(QWidget):
    """
    Ledger search restricted to a pre-filtered subset of ledgers.
    F2 opens QuickAddLedgerDialog restricted to allowed groups only.
    """
    ledger_selected = pyqtSignal(int, str, dict)

    def __init__(self, tree, calculator,
                 ledger_list: list,
                 allowed_group_ids: list = None,
                 placeholder="Search...",
                 parent=None):
        super().__init__(parent)
        self.tree               = tree
        self.calculator         = calculator
        self._ledger_map: dict[str, dict] = {}
        self._selected_id: int | None = None
        self._allowed_group_ids = allowed_group_ids or []

        self.setFixedHeight(36)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.search = QLineEdit()
        self.search.setPlaceholderText(placeholder)
        self.search.setFixedHeight(36)
        self.search.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        # Inherit the global QLineEdit / :focus styles for a clean focus ring.

        add_btn = LedgerSearchEdit._make_chip_btn(
            "F2", "F2 — Create new account"
        )
        add_btn.clicked.connect(self._open_add_dialog)

        edit_btn = LedgerSearchEdit._make_chip_btn(
            "F3", "F3 — Edit the selected account"
        )
        edit_btn.clicked.connect(self._open_edit_dialog)

        layout.addWidget(self.search)
        layout.addWidget(add_btn)
        layout.addWidget(edit_btn)

        self._model = QStringListModel()
        self._completer = QCompleter(self._model, self)
        self._completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self._completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self._completer.setMaxVisibleItems(12)
        self._completer.activated.connect(self._on_completion)
        self.search.setCompleter(self._completer)

        f2 = QShortcut(QKeySequence("F2"), self.search)
        f2.activated.connect(self._open_add_dialog)
        f3 = QShortcut(QKeySequence("F3"), self.search)
        f3.activated.connect(self._open_edit_dialog)

        self.search.textChanged.connect(
            lambda t: setattr(self, '_selected_id', None)
            if t not in self._ledger_map else None
        )

        self.load_ledgers(ledger_list)

    def _open_edit_dialog(self):
        lid = self.selected_id
        if not lid:
            QMessageBox.information(
                self, "No ledger selected",
                "Pick an account from the list, then press F3 to edit it.",
            )
            return
        dlg = QuickAddLedgerDialog(
            self.tree, parent=self, existing_ledger_id=lid,
        )
        dlg.ledger_updated.connect(self._on_ledger_updated)
        dlg.exec()

    def _on_ledger_updated(self, lid: int, name: str):
        # Refresh from the full ledger list, keeping the same allowed scope
        try:
            all_ledgers = self.tree.get_all_ledgers()
            filtered = [
                l for l in all_ledgers
                if l["name"] in self._ledger_map or l["id"] == lid
            ]
            self.load_ledgers(filtered)
        except Exception:
            pass
        self.search.setText(name)
        self._selected_id = lid
        ldg = self._ledger_map.get(name, {"id": lid, "name": name})
        self.ledger_selected.emit(lid, name, ldg)

    def load_ledgers(self, ledger_list: list):
        self._ledger_map = {l["name"]: l for l in ledger_list}
        self._model.setStringList(sorted(self._ledger_map.keys()))

    def _on_completion(self, text: str):
        ldg = self._ledger_map.get(text)
        if ldg:
            self._selected_id = ldg["id"]
            self.search.setText(text)
            self.ledger_selected.emit(ldg["id"], text, ldg)

    def _open_add_dialog(self):
        try:
            dlg = QuickAddLedgerDialog(
                self.tree,
                self.search.text().strip(),
                parent=self,
                allowed_group_ids=self._allowed_group_ids,
            )
            dlg.ledger_created.connect(self._on_ledger_created)
            dlg.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", str(e))

    def _on_ledger_created(self, lid: int, name: str):
        try:
            all_ledgers = self.tree.get_all_ledgers()
            filtered = [
                l for l in all_ledgers
                if l["name"] in self._ledger_map or l["id"] == lid
            ]
            self.load_ledgers(filtered)
        except Exception:
            pass
        self.search.setText(name)
        self._selected_id = lid
        ldg = self._ledger_map.get(name, {"id": lid, "name": name})
        self.ledger_selected.emit(lid, name, ldg)

    @property
    def selected_id(self) -> int | None:
        if self._selected_id is None:
            ldg = self._ledger_map.get(self.search.text().strip())
            return ldg["id"] if ldg else None
        return self._selected_id

    @property
    def selected_ledger(self) -> dict | None:
        return self._ledger_map.get(self.search.text().strip())

    def clear(self):
        self.search.clear()
        self._selected_id = None

    def set_ledger(self, name: str):
        self.search.setText(name)
        ldg = self._ledger_map.get(name)
        if ldg:
            self._selected_id = ldg["id"]


# ── Voucher Line Row widget ───────────────────────────────────────────────────

class VoucherLineRow(QWidget):
    """One journal line: ledger | single amount | Dr/Cr toggle | narration | delete"""
    delete_requested = pyqtSignal(object)

    def __init__(self, tree, calculator, row_num: int, parent=None):
        super().__init__(parent)
        self.row_num = row_num
        self._calculator = calculator

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 3, 0, 3)
        layout.setSpacing(8)

        # Row number
        num = QLabel(str(row_num))
        num.setFixedWidth(24)
        num.setStyleSheet(f"color:{THEME['text_dim']}; font-size:11px;")
        num.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(num)

        # Dr/Cr type toggle — first so user picks direction before ledger
        self.type_toggle = QComboBox()
        self.type_toggle.setFixedWidth(120)
        self.type_toggle.setFixedHeight(34)
        self._refresh_toggle_labels()
        self.type_toggle.setStyleSheet(f"""
            QComboBox {{
                background: {THEME['accent_dim']};
                border: 1px solid {THEME['accent']};
                border-radius: 7px;
                padding: 6px 10px;
                font-size: 12px;
                font-weight: bold;
                color: {THEME['accent']};
            }}
            QComboBox:focus {{
                border-color: {THEME['border_focus']};
            }}
            QComboBox QAbstractItemView {{
                background: {THEME['bg_card']};
                font-size: 12px;
            }}
        """)
        layout.addWidget(self.type_toggle)

        # Ledger search
        self.ledger_search = LedgerSearchEdit(tree, calculator, "Search ledger...")
        self.ledger_search.setMinimumWidth(240)
        layout.addWidget(self.ledger_search, 3)

        # Single amount field
        self.amount_edit = AmountEdit()
        self.amount_edit.setFixedWidth(150)
        self.amount_edit.focused.connect(self._on_focused)
        layout.addWidget(self.amount_edit, 1)

        # Line narration
        self.narration = QLineEdit()
        self.narration.setPlaceholderText("Line note...")
        self.narration.setFixedHeight(34)
        layout.addWidget(self.narration, 2)

        # Delete
        del_btn = QPushButton("✕")
        del_btn.setObjectName("btn_icon")
        del_btn.setFixedSize(30, 30)
        del_btn.setStyleSheet(f"color:{THEME['danger']}; font-size:14px;")
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self))
        layout.addWidget(del_btn)

    def _refresh_toggle_labels(self):
        from core.config import get_dr_label, get_cr_label
        current = self.type_toggle.currentIndex() if self.type_toggle.count() > 0 else 0
        self.type_toggle.clear()
        self.type_toggle.addItem(get_dr_label(short=True), "dr")
        self.type_toggle.addItem(get_cr_label(short=True), "cr")
        self.type_toggle.setCurrentIndex(current)

    def _on_focused(self, widget):
        self._calculator.connect_to(widget)

    @property
    def ledger_id(self) -> int | None:
        return self.ledger_search.selected_id

    @property
    def dr_amount(self) -> float:
        return self.amount_edit.value() if self.type_toggle.currentData() == "dr" else 0.0

    @property
    def cr_amount(self) -> float:
        return self.amount_edit.value() if self.type_toggle.currentData() == "cr" else 0.0

    def to_dict(self) -> dict:
        return {
            "ledger_id":      self.ledger_id,
            "ledger_name":    self.ledger_search.search.text().strip(),
            "dr_amount":      self.dr_amount,
            "cr_amount":      self.cr_amount,
            "line_narration": self.narration.text().strip(),
        }
