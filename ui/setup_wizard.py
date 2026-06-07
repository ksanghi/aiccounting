"""
Accounts HQ — Quick Setup wizard.

A licence-aware onboarding wizard. It captures the OPTIONAL settings, and for
each one tells the user WHY it helps and WHAT IT TAKES (the overhead), so they
can set it up or skip. It checks the licence first and only shows the pages the
plan actually unlocks.

Runs once automatically on first launch (flag: prefs 'setup_wizard_done') and
can be re-run any time from the sidebar "Setup" button.

It writes to the existing plumbing — nothing new:
  • core.config.set_theme_mode / set_label_style        (look & feel)
  • core.user_prefs.prefs                                (date, backup, bill-wise opt-in)
  • companies table                                      (GSTIN / state / TAN / portal user)
  • core.ai_routing.routing.set_own_key                  (BYOK Anthropic key)
  • ui.email_setup_dialog.EmailSetupDialog               (read-only mailbox)
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWizard, QWizardPage, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QLineEdit,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QPushButton, QApplication,
)

from ui.theme import THEME
from core.user_prefs import prefs


def _why_what(why: str, what: str) -> QFrame:
    """The reusable 'Why this helps / What it takes' explanation block."""
    f = QFrame(); f.setObjectName("card")
    l = QVBoxLayout(f); l.setContentsMargins(14, 12, 14, 12); l.setSpacing(3)
    w1 = QLabel("Why this helps")
    w1.setStyleSheet(f"color:{THEME['accent']}; font-weight:bold; font-size:12px;")
    l.addWidget(w1)
    wb = QLabel(why); wb.setWordWrap(True); l.addWidget(wb)
    l.addSpacing(6)
    w2 = QLabel("What it takes")
    w2.setStyleSheet(f"color:{THEME['text_secondary']}; font-weight:bold; font-size:12px;")
    l.addWidget(w2)
    ob = QLabel(what); ob.setWordWrap(True)
    ob.setStyleSheet(f"color:{THEME['text_secondary']};")
    l.addWidget(ob)
    return f


def _skip_note() -> QLabel:
    lbl = QLabel("Optional — leave blank to skip. You can set this up later from "
                 "the sidebar “Setup” button.")
    lbl.setWordWrap(True)
    lbl.setStyleSheet(f"color:{THEME['text_dim']}; font-size:11px; font-style:italic;")
    return lbl


# ── Pages ──────────────────────────────────────────────────────────────────────

class _Page(QWizardPage):
    def __init__(self, wizard):
        super().__init__()
        self.wiz = wizard
        self._lay = QVBoxLayout(self)
        self._lay.setSpacing(10)

    def add(self, w):
        self._lay.addWidget(w)

    def save(self):
        pass

    def validatePage(self):
        try:
            self.save()
        except Exception:
            pass
        return True


class WelcomePage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        plan = (getattr(wizard.lmgr, "plan", "") or "FREE")
        self.setTitle("Welcome to Accounts HQ")
        self.setSubTitle("A two-minute setup of the optional bits — skip anything you don't need.")
        intro = QLabel(
            f"You're on the <b>{plan}</b> plan. This wizard walks through the optional "
            f"features your plan includes. For each one it tells you why it helps and "
            f"what effort it takes, so you can decide.\n\nNothing here is required — you "
            f"can finish in seconds and configure more later.")
        intro.setWordWrap(True)
        self.add(intro)


class LookFeelPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Look & feel")
        self.setSubTitle("Make the app comfortable to use.")
        self.add(_why_what(
            "Set the theme and wording to your taste so day-to-day entry feels natural.",
            "10 seconds. No downside — change it any time in the sidebar."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self._light = QRadioButton("Light"); self._dark = QRadioButton("Dark")
        from core.config import current_theme_mode
        (self._dark if current_theme_mode() == "dark" else self._light).setChecked(True)
        g = QButtonGroup(self); g.addButton(self._light); g.addButton(self._dark)
        row.addWidget(self._light); row.addWidget(self._dark); row.addStretch()
        self._lay.addLayout(row)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Debit/Credit wording:"))
        self._style = QComboBox()
        self._style.addItem("Plain (Money in / out)", "natural")
        self._style.addItem("Traditional (Dr / Cr)", "traditional")
        self._style.addItem("Accounting (Debit / Credit)", "accounting")
        from core.config import current_style
        i = self._style.findData(current_style()); self._style.setCurrentIndex(max(0, i))
        row2.addWidget(self._style, 1)
        self._lay.addLayout(row2)

        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Default voucher date:"))
        self._date = QComboBox()
        self._date.addItem("Today", "today")
        self._date.addItem("Last used (sticky)", "last_used")
        i = self._date.findData(prefs.get("default_voucher_date", "today"))
        self._date.setCurrentIndex(max(0, i))
        row3.addWidget(self._date, 1)
        self._lay.addLayout(row3)

    def save(self):
        from core.config import set_theme_mode, set_label_style
        mode = "dark" if self._dark.isChecked() else "light"
        set_theme_mode(mode)
        try:
            from ui.theme import set_theme_mode as ui_set, get_stylesheet
            ui_set(mode)
            app = QApplication.instance()
            if app:
                app.setStyleSheet(get_stylesheet())
        except Exception:
            pass
        set_label_style(self._style.currentData())
        prefs.set("default_voucher_date", self._date.currentData())


class GSTPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("GST")
        self.setSubTitle("So GST calculates and your returns are ready.")
        self.add(_why_what(
            "With your GSTIN and state, Accounts HQ auto-splits CGST/SGST/IGST on every "
            "invoice and prepares GSTR-3B, GSTR-1 and HSN summaries. Add your portal "
            "username too if you want GSTR-2B reconciliation pulled for you.",
            "Just type your GSTIN (15 chars) and pick your state. The portal username is "
            "optional and only needed for automatic 2B."))
        row = wizard._company_row()
        self._gstin = QLineEdit(row.get("gstin") or ""); self._gstin.setPlaceholderText("22ABCDE1234F1Z5")
        self._state = QLineEdit(row.get("state_code") or "07"); self._state.setPlaceholderText("State code e.g. 07")
        self._user = QLineEdit(row.get("gst_username") or ""); self._user.setPlaceholderText("GST portal username (optional)")
        for lab, w in (("GSTIN", self._gstin), ("State code", self._state),
                       ("Portal username", self._user)):
            r = QHBoxLayout(); r.addWidget(QLabel(lab + ":")); r.addWidget(w, 1)
            self._lay.addLayout(r)
        self.add(_skip_note())

    def save(self):
        self.wiz._update_company(
            gstin=self._gstin.text().strip().upper(),
            state_code=self._state.text().strip() or "07",
            gst_username=self._user.text().strip())


class TDSPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("TDS")
        self.setSubTitle("For tax deducted at source.")
        self.add(_why_what(
            "Your TAN lets Accounts HQ produce TDS reports and a section-wise TDS register.",
            "Just type your 10-character TAN. Skip if you don't deduct TDS."))
        row = wizard._company_row()
        self._tan = QLineEdit(row.get("tan") or ""); self._tan.setPlaceholderText("e.g. DELA12345B")
        r = QHBoxLayout(); r.addWidget(QLabel("TAN:")); r.addWidget(self._tan, 1)
        self._lay.addLayout(r)
        self.add(_skip_note())

    def save(self):
        self.wiz._update_company(tan=self._tan.text().strip().upper())


class BillWisePage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Track invoices bill-by-bill")
        self.setSubTitle("“Against Reference” — invoice-level outstanding.")
        self.add(_why_what(
            "See exactly which invoices are still open for each customer/supplier and how "
            "overdue each one is — not just their overall balance.",
            "One extra click when recording a receipt/payment: “Allocate to bills…”. If you "
            "don't turn it on, parties are tracked by their overall balance as usual."))
        self._chk = QCheckBox("Yes, let me allocate receipts/payments to specific bills")
        self._chk.setChecked(bool(prefs.get("bill_wise_enabled", True)))
        self.add(self._chk)

    def save(self):
        prefs.set("bill_wise_enabled", self._chk.isChecked())


class AIKeyPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("AI document reading (your own key)")
        self.setSubTitle("Let AI read invoices and draft the vouchers.")
        self.add(_why_what(
            "Drop or email an invoice and the AI reads it, decides its type and drafts the "
            "voucher for you to approve — a big time saver on data entry.",
            "Get a key from console.anthropic.com (one-time, free to create). The AI then "
            "runs on YOUR key, so there's a small per-document cost billed by Anthropic, not "
            "us. No key = the AI features simply stay locked."))
        from core.ai_routing import routing
        self._key = QLineEdit(routing.get_own_key())
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("sk-ant-...")
        r = QHBoxLayout(); r.addWidget(QLabel("Anthropic key:")); r.addWidget(self._key, 1)
        self._lay.addLayout(r)
        get = QPushButton("Get a key (opens console.anthropic.com)")
        get.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://console.anthropic.com/settings/keys")))
        self.add(get)
        self.add(_skip_note())

    def save(self):
        from core.ai_routing import routing
        k = self._key.text().strip()
        if k:
            routing.set_own_key(k)


class EmailPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Auto-import invoices from email")
        self.setSubTitle("Read-only — your mailbox, nothing on our servers.")
        self.add(_why_what(
            "Point Accounts HQ at a folder/label in your own inbox and invoice attachments "
            "are pulled in automatically for AI processing.",
            "A one-time connect (~5 min) — most providers need an “app password”, and the "
            "setup screen has step-by-step help per provider. We read only; your password is "
            "stored only on this PC."))
        self._status = QLabel("")
        self.add(self._status)
        btn = QPushButton("Connect email…")
        btn.clicked.connect(self._connect)
        self.add(btn)
        self.add(_skip_note())
        self._refresh()

    def _refresh(self):
        try:
            from core import email_fetcher as ef
            c = ef.load_config(self.wiz.slug)
            self._status.setText(f"Connected: {c.email}" if (c.email and c.host and c.password)
                                 else "Not connected yet.")
        except Exception:
            self._status.setText("Not connected yet.")

    def _connect(self):
        try:
            from ui.email_setup_dialog import EmailSetupDialog
            EmailSetupDialog(self.wiz.slug, self).exec()
        except Exception:
            pass
        self._refresh()


class ScannerPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Scan paper invoices straight in")
        self.setSubTitle("Point your scanner at one folder.")
        folder = wizard._inbox_folder()
        self.add(_why_what(
            "Anything your scanner saves into the inbox folder is picked up by the Document "
            "Inbox automatically — no importing.",
            "Set your scanner software's save location to the folder below, once."))
        path = QLabel(folder); path.setWordWrap(True)
        path.setStyleSheet(f"color:{THEME['text_primary']}; font-weight:bold;")
        self.add(path)
        btn = QPushButton("Open this folder")
        btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(folder)))
        self.add(btn)
        self.add(_skip_note())


class BackupPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Backups — your safety net")
        self.setSubTitle("Your data lives on this PC.")
        self.add(_why_what(
            "A backup protects you against a disk failure, theft or a mistake. Without one, "
            "lost data is gone.",
            "Pick how often you'd like a reminder. Backing up itself is two clicks (Data → "
            "Backup & Restore) to a pen-drive or cloud folder."))
        r = QHBoxLayout(); r.addWidget(QLabel("Remind me to back up:"))
        self._freq = QComboBox()
        self._freq.addItem("Every week", 7)
        self._freq.addItem("Every fortnight", 14)
        self._freq.addItem("Every month", 30)
        self._freq.addItem("Don't remind me", 0)
        i = self._freq.findData(int(prefs.get("backup_reminder_days", 7) or 7))
        self._freq.setCurrentIndex(max(0, i))
        r.addWidget(self._freq, 1)
        self._lay.addLayout(r)

    def save(self):
        prefs.set("backup_reminder_days", self._freq.currentData())


class FinishPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("You're set up")
        self.setSubTitle("")
        self.add(QLabel(
            "That's it — you're ready to use Accounts HQ.\n\nYou can run this wizard again "
            "any time from the sidebar “Setup” button to add or change any of these settings."))

    def save(self):
        prefs.set("setup_wizard_done", True)


# ── Wizard ──────────────────────────────────────────────────────────────────────

class SetupWizard(QWizard):
    def __init__(self, db, company_id: int, slug: str, lmgr, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.slug = slug
        self.lmgr = lmgr
        self.setWindowTitle("Accounts HQ — Quick Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(620, 520)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        def has(f):
            try:
                return bool(lmgr.has_feature(f))
            except Exception:
                return False

        self.addPage(WelcomePage(self))
        self.addPage(LookFeelPage(self))
        if has("gst"):
            self.addPage(GSTPage(self))
        if has("tds"):
            self.addPage(TDSPage(self))
        if has("bill_wise_refs"):
            self.addPage(BillWisePage(self))
        if has("document_inbox"):
            self.addPage(AIKeyPage(self))
            self.addPage(EmailPage(self))
            self.addPage(ScannerPage(self))
        self.addPage(BackupPage(self))
        self.addPage(FinishPage(self))

    # ── helpers shared by pages ────────────────────────────────────────────
    def _company_row(self) -> dict:
        try:
            r = self.db.execute(
                "SELECT gstin, state_code, gst_username, tan FROM companies WHERE id=?",
                (self.company_id,)).fetchone()
            return dict(r) if r else {}
        except Exception:
            return {}

    def _update_company(self, **fields):
        cols = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [self.company_id]
        try:
            self.db.execute(f"UPDATE companies SET {cols} WHERE id=?", vals)
            self.db.commit()
        except Exception:
            pass

    def _inbox_folder(self) -> str:
        try:
            from core.paths import inbox_dir
            import os
            return str(os.path.join(str(inbox_dir(self.slug)), "incoming"))
        except Exception:
            return "(inbox folder)"
