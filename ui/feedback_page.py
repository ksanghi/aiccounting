"""
Feedback page — Feature Request and Bug Report.
Opens pre-filled Google Form in browser with
license, plan, OS info auto-populated.
"""
import platform
import webbrowser
import urllib.parse
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit,
    QLineEdit, QFrame,
)
from PyQt6.QtCore import Qt

from ui.theme import THEME
from core.license_manager import LicenseManager

# Replace with your real Google Form URL after creating at forms.google.com
FORM_BASE_URL = (
    "https://docs.google.com/forms/d/e/"
    "PLACEHOLDER_FORM_ID/viewform"
)

# Replace with real entry IDs from your form's pre-filled link
ENTRY_TYPE        = "entry.1000001"
ENTRY_SUBJECT     = "entry.1000002"
ENTRY_DESCRIPTION = "entry.1000003"
ENTRY_STEPS       = "entry.1000004"
ENTRY_LICENSE     = "entry.1000005"
ENTRY_PLAN        = "entry.1000006"
ENTRY_VERSION     = "entry.1000007"
ENTRY_OS          = "entry.1000008"

APP_VERSION = "1.0.0"


def _get_os_info() -> str:
    return f"{platform.system()} {platform.release()} {platform.machine()}"


class FeedbackPage(QWidget):

    def __init__(self, license_mgr: LicenseManager, parent=None):
        super().__init__(parent)
        self._mgr          = license_mgr
        self._current_type = "feature"
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 24, 32, 24)
        layout.setSpacing(12)

        title = QLabel("Feedback")
        title.setObjectName("page_title")
        layout.addWidget(title)

        sub = QLabel(
            "Report a bug or request a feature — your feedback shapes the product"
        )
        sub.setObjectName("page_subtitle")
        layout.addWidget(sub)

        # ── Type toggle ────────────────────────────────────────────────────────
        toggle_frame = QFrame()
        toggle_frame.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        tf = QHBoxLayout(toggle_frame)
        tf.setContentsMargins(16, 14, 16, 14)
        tf.setSpacing(10)

        want_lbl = QLabel("I want to:")
        want_lbl.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:12px; font-weight:bold;"
            f" background:transparent; border:none;"
        )
        tf.addWidget(want_lbl)

        self._feat_btn = QPushButton("  ✨  Request a Feature")
        self._feat_btn.setCheckable(True)
        self._feat_btn.setChecked(True)
        self._feat_btn.setFixedHeight(36)
        self._feat_btn.clicked.connect(lambda: self._set_type("feature"))

        self._bug_btn = QPushButton("  🐛  Report a Bug")
        self._bug_btn.setCheckable(True)
        self._bug_btn.setChecked(False)
        self._bug_btn.setFixedHeight(36)
        self._bug_btn.clicked.connect(lambda: self._set_type("bug"))

        tf.addWidget(self._feat_btn)
        tf.addWidget(self._bug_btn)
        tf.addStretch()
        layout.addWidget(toggle_frame)

        # ── Form card ──────────────────────────────────────────────────────────
        form_card = QFrame()
        form_card.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        fc = QVBoxLayout(form_card)
        fc.setContentsMargins(20, 16, 20, 16)
        fc.setSpacing(12)

        def _field_label(text: str) -> QLabel:
            lbl = QLabel(text)
            lbl.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
                f" background:transparent; border:none;"
            )
            return lbl

        fc.addWidget(_field_label("Subject *"))
        self._subject = QLineEdit()
        self._subject.setFixedHeight(36)
        fc.addWidget(self._subject)

        fc.addWidget(_field_label("Description *"))
        self._description = QTextEdit()
        self._description.setFixedHeight(100)
        fc.addWidget(self._description)

        self._steps_lbl = _field_label("Steps to reproduce")
        fc.addWidget(self._steps_lbl)

        self._steps = QTextEdit()
        self._steps.setPlaceholderText(
            "1. Go to voucher entry\n2. Click Post\n3. Error appears..."
        )
        self._steps.setFixedHeight(80)
        fc.addWidget(self._steps)

        layout.addWidget(form_card)

        # ── System info card ───────────────────────────────────────────────────
        sys_card = QFrame()
        sys_card.setStyleSheet(f"""
            QFrame {{
                background: {THEME['bg_card']};
                border: 1px solid {THEME['border']};
                border-radius: 10px;
            }}
        """)
        sc = QVBoxLayout(sys_card)
        sc.setContentsMargins(20, 14, 20, 14)
        sc.setSpacing(6)

        sys_hdr = QLabel("System information (auto-filled)")
        sys_hdr.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:11px; font-weight:bold;"
            f" background:transparent; border:none;"
        )
        sc.addWidget(sys_hdr)

        key = self._mgr.license_key
        if key in ("FREE-DEMO", "", None):
            key = "Free (no key)"
        self._sys_key  = key
        self._sys_plan = self._mgr.plan

        for label, value in [
            ("License key", key),
            ("Plan",        self._sys_plan),
            ("App version", APP_VERSION),
            ("OS",          _get_os_info()),
        ]:
            row = QHBoxLayout()
            row.setSpacing(8)
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(90)
            lbl.setStyleSheet(
                f"color:{THEME['text_dim']}; font-size:11px;"
                f" background:transparent; border:none;"
            )
            val = QLabel(str(value))
            val.setStyleSheet(
                f"color:{THEME['text_secondary']}; font-size:11px;"
                f" background:transparent; border:none;"
            )
            val.setWordWrap(True)
            row.addWidget(lbl)
            row.addWidget(val, 1)
            sc.addLayout(row)

        note = QLabel(
            "This information helps us reproduce issues faster. "
            "It is sent only when you click Submit."
        )
        note.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px;"
            f" background:transparent; border:none;"
        )
        note.setWordWrap(True)
        sc.addWidget(note)
        layout.addWidget(sys_card)

        # ── Submit row ─────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(38)
        clear_btn.setFixedWidth(90)
        clear_btn.clicked.connect(self._clear)
        btn_row.addWidget(clear_btn)

        self._submit_btn = QPushButton("Submit via Browser  ↗")
        self._submit_btn.setFixedHeight(38)
        self._submit_btn.setMinimumWidth(180)
        self._submit_btn.setStyleSheet(f"""
            QPushButton {{
                background: {THEME['accent']};
                color: white;
                border: none;
                border-radius: 7px;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 20px;
            }}
            QPushButton:hover {{ background: {THEME['accent_hover']}; }}
        """)
        self._submit_btn.clicked.connect(self._submit)
        btn_row.addWidget(self._submit_btn)
        layout.addLayout(btn_row)

        hint = QLabel(
            "Clicking Submit opens Google Forms in your browser with your details "
            "pre-filled. Review and click Submit there to send."
        )
        hint.setStyleSheet(f"color:{THEME['text_dim']}; font-size:10px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch()

        # Apply initial state
        self._set_type("feature")

    # ── Type toggle ───────────────────────────────────────────────────────────

    def _set_type(self, ftype: str):
        self._current_type = ftype
        is_bug = (ftype == "bug")

        self._steps_lbl.setVisible(is_bug)
        self._steps.setVisible(is_bug)

        if is_bug:
            self._description.setPlaceholderText(
                "Describe what went wrong — what did you expect vs what happened?"
            )
            self._subject.setPlaceholderText(
                "e.g. App crashes when posting a receipt voucher"
            )
        else:
            self._description.setPlaceholderText(
                "Describe the feature you need and why it would help your workflow..."
            )
            self._subject.setPlaceholderText(
                "e.g. Add WhatsApp notification when voucher is posted"
            )

        self._update_toggle_style(ftype)

    def _update_toggle_style(self, active: str):
        active_css = f"""
            QPushButton {{
                background: {THEME['accent']};
                color: white; border: none;
                border-radius: 7px;
                font-size: 12px; font-weight: bold;
                padding: 6px 16px;
            }}
        """
        inactive_css = f"""
            QPushButton {{
                background: {THEME['bg_input']};
                color: {THEME['text_secondary']};
                border: 1px solid {THEME['border']};
                border-radius: 7px;
                font-size: 12px;
                padding: 6px 16px;
            }}
            QPushButton:hover {{
                border-color: {THEME['accent']};
                color: {THEME['accent']};
            }}
        """
        self._feat_btn.setStyleSheet(active_css if active == "feature" else inactive_css)
        self._bug_btn.setStyleSheet(active_css if active == "bug" else inactive_css)
        self._feat_btn.setChecked(active == "feature")
        self._bug_btn.setChecked(active == "bug")

    # ── Actions ───────────────────────────────────────────────────────────────

    def _submit(self):
        subject     = self._subject.text().strip()
        description = self._description.toPlainText().strip()

        err_input_css = f"""
            background:{THEME['bg_input']};
            border:1px solid {THEME['danger']};
            border-radius:7px;
            padding:6px 12px;
            color:{THEME['text_primary']};
            font-size:12px;
        """

        if not subject:
            self._subject.setStyleSheet(f"QLineEdit {{ {err_input_css} }}")
            self._subject.setFocus()
            return

        if not description:
            self._description.setStyleSheet(
                f"QTextEdit {{ {err_input_css} }}"
            )
            self._description.setFocus()
            return

        # Reset error styles
        self._subject.setStyleSheet("")
        self._description.setStyleSheet("")

        ftype = "Feature Request" if self._current_type == "feature" else "Bug Report"
        steps = self._steps.toPlainText().strip()

        full_desc = description
        if steps:
            full_desc += f"\n\nSteps to reproduce:\n{steps}"

        params = {
            ENTRY_TYPE:        ftype,
            ENTRY_SUBJECT:     subject,
            ENTRY_DESCRIPTION: full_desc,
            ENTRY_STEPS:       steps,
            ENTRY_LICENSE:     self._sys_key,
            ENTRY_PLAN:        self._sys_plan,
            ENTRY_VERSION:     APP_VERSION,
            ENTRY_OS:          _get_os_info(),
        }

        url = FORM_BASE_URL + "?" + urllib.parse.urlencode(params)
        webbrowser.open(url)

    def _clear(self):
        self._subject.clear()
        self._description.clear()
        self._steps.clear()
        self._subject.setStyleSheet("")
        self._description.setStyleSheet("")
        self._set_type("feature")
