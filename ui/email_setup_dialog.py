"""
Email setup dialog for the Document Inbox.

The customer connects THEIR OWN mailbox (read-only) so invoices that land
in their email flow into the inbox automatically. v1 is IMAP + an
app-password — universal, no OAuth app to register, nothing on our servers.

This is the seed of the PRO+ "guided connect wizard": it auto-fills the
IMAP host from the email domain and explains the app-password step (the
#1 thing non-technical users get stuck on).
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit,
    QPushButton, QCheckBox, QSpinBox, QFrame,
)
from PySide6.QtCore import Qt

from ui.theme import THEME
from core import email_fetcher as ef


_APP_PW_HELP = {
    "imap.gmail.com": "Gmail: turn on 2-Step Verification, then create an "
                      "App Password at myaccount.google.com → Security → "
                      "App passwords. Use that 16-char code below, not your "
                      "normal password.",
    "outlook.office365.com": "Outlook/Microsoft 365: create an app password "
                      "at account.microsoft.com → Security → Advanced "
                      "security options. Use it below.",
    "imap.mail.yahoo.com": "Yahoo: create an app password at "
                      "account.yahoo.com → Account Security → Generate "
                      "app password.",
}


class EmailSetupDialog(QDialog):

    def __init__(self, slug: str, parent=None):
        super().__init__(parent)
        self._slug = slug
        self.cfg = ef.load_config(slug)
        self.fetch_after = False
        self.setWindowTitle("Connect your email — Document Inbox")
        self.setMinimumWidth(480)
        self._build()
        self._load()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        intro = QLabel(
            "Point the inbox at a folder in <b>your own</b> mailbox. We read "
            "it <b>read-only</b> — invoices that arrive there flow in "
            "automatically. Your password never leaves this PC and nothing "
            "passes through our servers."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet(f"color:{THEME['text_secondary']};font-size:11px;")
        lay.addWidget(intro)

        form = QFormLayout()
        form.setSpacing(8)

        self._enabled = QCheckBox("Check this mailbox automatically")
        form.addRow("", self._enabled)

        self._email = QLineEdit()
        self._email.setPlaceholderText("accounts@yourbusiness.com")
        self._email.editingFinished.connect(self._autofill_host)
        form.addRow("Email", self._email)

        self._password = QLineEdit()
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setPlaceholderText("app-password (not your normal password)")
        form.addRow("App-password", self._password)

        host_row = QHBoxLayout()
        self._host = QLineEdit()
        self._host.setPlaceholderText("imap.yourprovider.com")
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(993)
        self._port.setFixedWidth(80)
        host_row.addWidget(self._host, 1)
        host_row.addWidget(QLabel("Port"))
        host_row.addWidget(self._port)
        hw = QFrame()
        hw.setLayout(host_row)
        form.addRow("IMAP host", hw)

        self._folder = QLineEdit()
        self._folder.setPlaceholderText("INBOX  (or a label, e.g. Invoices)")
        form.addRow("Folder / label", self._folder)

        lay.addLayout(form)

        self._help = QLabel("")
        self._help.setWordWrap(True)
        self._help.setStyleSheet(
            f"color:{THEME['warning']};font-size:11px;"
            f"background:{THEME['bg_input']};border-radius:6px;padding:8px;"
        )
        lay.addWidget(self._help)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"font-size:11px;color:{THEME['text_secondary']};")
        lay.addWidget(self._status)

        btns = QHBoxLayout()
        test_btn = QPushButton("Test Connection")
        test_btn.clicked.connect(self._test)
        btns.addWidget(test_btn)
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(lambda: self._save(fetch=False))
        save_fetch = QPushButton("Save & Check Now")
        save_fetch.setObjectName("btn_primary")
        save_fetch.clicked.connect(lambda: self._save(fetch=True))
        btns.addWidget(cancel)
        btns.addWidget(save)
        btns.addWidget(save_fetch)
        lay.addLayout(btns)

    def _load(self):
        c = self.cfg
        self._enabled.setChecked(c.enabled)
        self._email.setText(c.email)
        self._password.setText(c.password)
        self._host.setText(c.host)
        self._port.setValue(c.port or 993)
        self._folder.setText(c.folder or "INBOX")
        self._update_help()

    def _autofill_host(self):
        if not self._host.text().strip():
            host, port = ef.guess_host(self._email.text().strip())
            if host:
                self._host.setText(host)
                self._port.setValue(port)
        self._update_help()

    def _update_help(self):
        host = self._host.text().strip()
        self._help.setText(_APP_PW_HELP.get(
            host,
            "Most providers need an 'app-password' (a one-time code from your "
            "email security settings) and IMAP enabled — your normal login "
            "password usually won't work."
        ))

    def _collect(self) -> ef.EmailConfig:
        self.cfg.enabled = self._enabled.isChecked()
        self.cfg.email = self._email.text().strip()
        self.cfg.password = self._password.text()
        self.cfg.host = self._host.text().strip()
        self.cfg.port = self._port.value()
        self.cfg.folder = self._folder.text().strip() or "INBOX"
        return self.cfg

    def _test(self):
        cfg = self._collect()
        self._status.setText("Testing…")
        self.repaint()
        ok, msg = ef.test_connection(cfg)
        self._status.setText(("✓ " if ok else "✕ ") + msg)
        self._status.setStyleSheet(
            f"font-size:11px;color:{THEME['success'] if ok else THEME['danger']};"
        )

    def _save(self, fetch: bool):
        cfg = self._collect()
        if not cfg.email or not cfg.host:
            self._status.setText("✕ Email and IMAP host are required.")
            self._status.setStyleSheet(f"font-size:11px;color:{THEME['danger']};")
            return
        ef.save_config(self._slug, cfg)
        self.fetch_after = fetch
        self.accept()
