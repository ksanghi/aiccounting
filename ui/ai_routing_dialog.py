"""
AI Routing dialog — one-time prompt when an AI feature is first used, plus
a Settings entry to revisit the choice.

Per-feature single mode (pooled OR own — never both for the same feature).
See `core/ai_routing.py` for the persistent store.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QRadioButton, QButtonGroup, QFrame, QCheckBox, QMessageBox,
)
from PySide6.QtCore import Qt

from ui.theme import THEME
from core.ai_routing import (
    RoutingConfig, routing as _routing_singleton,
    ROUTE_OWN, ROUTE_POOLED,
)


FEATURE_LABELS = {
    "document_reader":     "AI Document Reader",
    "bank_reconciliation": "Bank Reconciliation (AI fallback)",
    "verbal_entry":        "Verbal Voucher Entry",
}


class AIRoutingDialog(QDialog):
    """
    Prompts the user to pick pooled or own-key for `feature`, and offers
    a key field if they pick 'own'. Returns the chosen route via `result_route`.

    Usage:
        dlg = AIRoutingDialog(feature, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            route = dlg.result_route   # 'pooled' or 'own'
    """

    def __init__(self, feature: str, parent=None,
                 routing: RoutingConfig | None = None):
        super().__init__(parent)
        self._feature = feature
        self._routing = routing or _routing_singleton
        self.result_route: str | None = None

        self.setWindowTitle(f"AI Routing — {FEATURE_LABELS.get(feature, feature)}")
        self.setMinimumWidth(520)
        self._build_ui()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 20)
        outer.setSpacing(14)

        title = QLabel(
            f"How should AccGenie pay for AI in "
            f"<b>{FEATURE_LABELS.get(self._feature, self._feature)}</b>?"
        )
        title.setStyleSheet(f"color:{THEME['text_primary']}; font-size:13px;")
        title.setWordWrap(True)
        outer.addWidget(title)

        sub = QLabel(
            "Pick once per feature. You can change this any time from "
            "Settings → AI Routing."
        )
        sub.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:11px;")
        sub.setWordWrap(True)
        outer.addWidget(sub)

        outer.addWidget(self._sep())

        self._group = QButtonGroup(self)

        # Option A — pooled
        self._opt_pooled = QRadioButton(
            "Use AccGenie's pooled credits"
        )
        self._opt_pooled.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:12px; font-weight:bold;"
        )
        pooled_hint = QLabel(
            "Charged in paise from your AccGenie credit balance. No "
            "Anthropic account needed. Requires an activated paid license."
        )
        pooled_hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding-left:22px;"
        )
        pooled_hint.setWordWrap(True)
        self._group.addButton(self._opt_pooled, 0)
        outer.addWidget(self._opt_pooled)
        outer.addWidget(pooled_hint)

        # Option B — own key
        self._opt_own = QRadioButton(
            "Use my own Anthropic API key (BYOK)"
        )
        self._opt_own.setStyleSheet(
            f"color:{THEME['text_primary']}; font-size:12px; font-weight:bold;"
        )
        own_hint = QLabel(
            "Anthropic bills your account directly — no AccGenie credits "
            "consumed. Get a key at console.anthropic.com."
        )
        own_hint.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; padding-left:22px;"
        )
        own_hint.setWordWrap(True)
        self._group.addButton(self._opt_own, 1)
        outer.addWidget(self._opt_own)
        outer.addWidget(own_hint)

        # Own-key field
        self._key_edit = QLineEdit()
        self._key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_edit.setPlaceholderText("sk-ant-…")
        self._key_edit.setFixedHeight(34)
        self._key_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {THEME['bg_input']};
                border: 1px solid {THEME['border']};
                border-radius: 7px;
                padding: 6px 12px;
                color: {THEME['text_primary']};
                font-size: 12px;
                margin-left: 22px;
            }}
            QLineEdit:focus {{ border: 1px solid {THEME['border_focus']}; }}
        """)
        if self._routing.has_own_key():
            self._key_edit.setText(self._routing.get_own_key())
        self._key_edit.setEnabled(False)
        self._opt_own.toggled.connect(self._key_edit.setEnabled)
        outer.addWidget(self._key_edit)

        outer.addWidget(self._sep())

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(34)
        cancel_btn.clicked.connect(self.reject)
        ok_btn = QPushButton("Save")
        ok_btn.setObjectName("btn_primary")
        ok_btn.setFixedHeight(34)
        ok_btn.setDefault(True)
        ok_btn.clicked.connect(self._on_save)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        outer.addLayout(btn_row)

        # Initial selection — reflect current/default route
        current = self._routing.route_for(self._feature)
        if current == ROUTE_OWN:
            self._opt_own.setChecked(True)
            self._key_edit.setEnabled(True)
        else:
            self._opt_pooled.setChecked(True)

    @staticmethod
    def _sep() -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setStyleSheet(
            f"color:{THEME['border']}; background:{THEME['border']}; "
            f"border:none; max-height:1px;"
        )
        return f

    # ── Save ──────────────────────────────────────────────────────────────────

    def _on_save(self):
        if self._opt_own.isChecked():
            key = self._key_edit.text().strip()
            if not key:
                QMessageBox.warning(
                    self, "Key required",
                    "Paste your Anthropic API key, or switch to pooled credits.",
                )
                return
            if not key.startswith("sk-ant-"):
                # Not a hard error — just a friendly check.
                reply = QMessageBox.question(
                    self, "Unexpected key format",
                    "That doesn't look like an Anthropic key "
                    "(expected to start with 'sk-ant-'). Save anyway?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return
            self._routing.set_own_key(key)
            self._routing.set_route(self._feature, ROUTE_OWN)
            self.result_route = ROUTE_OWN
        else:
            self._routing.set_route(self._feature, ROUTE_POOLED)
            self.result_route = ROUTE_POOLED
        self.accept()


def ensure_routed(feature: str, parent=None) -> str | None:
    """
    Convenience: if the user hasn't configured this feature, pop the dialog.
    Returns the chosen route, or None if the user cancelled.

    Caller pattern:
        from ui.ai_routing_dialog import ensure_routed
        if ensure_routed("document_reader", parent=self) is None:
            return                                  # user cancelled
        # … now safe to make the AI call …
    """
    if _routing_singleton.is_configured(feature):
        return _routing_singleton.route_for(feature)
    dlg = AIRoutingDialog(feature, parent=parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.result_route
