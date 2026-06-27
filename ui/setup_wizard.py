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
from core import branding


# Per-product user-manual download. Lives next to the installers in
# marketing/downloads/. The PDF itself is produced by the manual task (A6);
# until it lands the link 404s, but the wizard button is ready.
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


class _Choice(QPushButton):
    """A selectable option that shows an explicit ✓ when chosen — clearer than a
    colour-filled radio/checkbox. Put mutually-exclusive options in a
    QButtonGroup; use standalone for a yes/no toggle."""
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._label = text
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "QPushButton{text-align:left; padding:11px 14px; border:1px solid "
            f"{THEME['border']}; border-radius:8px; background:transparent; "
            f"color:{THEME['text_primary']}; font-size:13px;}}"
            f"QPushButton:checked{{border-color:{THEME['accent']}; "
            f"color:{THEME['accent']}; font-weight:bold;}}")
        self.toggled.connect(self._render)
        self._render(self.isChecked())

    def _render(self, on: bool):
        self.setText(("✓   " if on else "      ") + self._label)


_FY_PRESETS = [
    ("04-01", "April – March (India default)"),
    ("01-01", "January – December"),
    ("07-01", "July – June"),
    ("10-01", "October – September"),
]


def _fy_label(val: str) -> str:
    for v, lbl in _FY_PRESETS:
        if v == val:
            return lbl
    return f"Custom ({val})"


def _locked_banner(tier: str, on_upgrade) -> QFrame:
    """Shown in place of a feature's controls when the current plan doesn't
    include it — so the user SEES the feature (and what unlocks it) instead of
    it being hidden. 'all-tier, not a tier-gated tour'."""
    f = QFrame(); f.setObjectName("card")
    l = QVBoxLayout(f); l.setContentsMargins(14, 12, 14, 12); l.setSpacing(6)
    head = QLabel(f"🔒  Unlocks with {tier}")
    head.setStyleSheet(f"color:{THEME['accent']}; font-weight:bold; font-size:13px;")
    l.addWidget(head)
    note = QLabel("You don't have this on your current plan. Upgrade to switch it on — "
                  "your other settings stay as they are.")
    note.setWordWrap(True); note.setStyleSheet(f"color:{THEME['text_secondary']};")
    l.addWidget(note)
    btn = QPushButton(f"Upgrade to {tier}")
    btn.clicked.connect(on_upgrade)
    l.addWidget(btn, alignment=Qt.AlignmentFlag.AlignLeft)
    return f


# ── Pages ──────────────────────────────────────────────────────────────────────

class _Page(QWizardPage):
    # Subclasses set `feature` (licence id) + `tier` (what unlocks it). When the
    # current plan lacks the feature the page is shown LOCKED (upgrade teaser
    # instead of controls) rather than hidden — all-tier, not a tier-gated tour.
    feature: str | None = None
    tier: str = "Standard"

    def __init__(self, wizard):
        super().__init__()
        self.wiz = wizard
        self.locked = bool(self.feature) and not wizard._has(self.feature)
        self._lay = QVBoxLayout(self)
        self._lay.setSpacing(10)

    def add(self, w):
        self._lay.addWidget(w)

    def add_locked(self) -> bool:
        """Render the upgrade teaser (call after the why/what block, then
        `return` so the page skips its locked controls)."""
        self.add(_locked_banner(self.tier, self.wiz._open_upgrade))
        return True

    def save(self):
        pass

    def validatePage(self):
        if not self.locked:
            try:
                self.save()
            except Exception:
                pass
        return True


class WelcomePage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        plan = (getattr(wizard.lmgr, "plan", "") or "FREE")
        self.setTitle(f"Welcome to {branding.PRODUCT_NAME}")
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
        self._light = _Choice("Light"); self._dark = _Choice("Dark")
        from core.config import current_theme_mode
        (self._dark if current_theme_mode() == "dark" else self._light).setChecked(True)
        g = QButtonGroup(self); g.setExclusive(True)
        g.addButton(self._light); g.addButton(self._dark)
        row.addWidget(self._light); row.addWidget(self._dark); row.addStretch()
        self._lay.addLayout(row)

        # Menu style (the navigation mode — Mode A sidebar / Mode B launcher).
        self._lay.addWidget(QLabel("Menu style:"))
        self._nav_sidebar = _Choice("Sidebar — a list down the left (classic)")
        self._nav_launcher = _Choice("Launcher — a tile grid you open with one key (modern)")
        navg = QButtonGroup(self); navg.setExclusive(True)
        navg.addButton(self._nav_sidebar); navg.addButton(self._nav_launcher)
        (self._nav_launcher if prefs.get("nav_mode", "sidebar") == "launcher"
         else self._nav_sidebar).setChecked(True)
        self._lay.addWidget(self._nav_sidebar); self._lay.addWidget(self._nav_launcher)

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
        prefs.set("nav_mode",
                  "launcher" if self._nav_launcher.isChecked() else "sidebar")


class GSTPage(_Page):
    feature = "gst"; tier = "Pro"

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
        if self.locked:
            self.add_locked(); return
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
    feature = "tds"; tier = "Pro"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("TDS")
        self.setSubTitle("For tax deducted at source.")
        self.add(_why_what(
            "Your TAN lets Accounts HQ produce TDS reports and a section-wise TDS register.",
            "Just type your 10-character TAN. Skip if you don't deduct TDS."))
        if self.locked:
            self.add_locked(); return
        row = wizard._company_row()
        self._tan = QLineEdit(row.get("tan") or ""); self._tan.setPlaceholderText("e.g. DELA12345B")
        r = QHBoxLayout(); r.addWidget(QLabel("TAN:")); r.addWidget(self._tan, 1)
        self._lay.addLayout(r)
        self.add(_skip_note())

    def save(self):
        self.wiz._update_company(tan=self._tan.text().strip().upper())


class SalesTaxPage(_Page):
    """US (Books HQ) default sales-tax rate — applied on sales as a single line."""
    feature = "sales_tax"; tier = "Pro"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Sales tax")
        self.setSubTitle("Your default sales-tax rate, applied on sales.")
        self.add(_why_what(
            "Books HQ adds this rate as a single Sales Tax line on every sale and "
            "tracks it as tax you owe; use tax on purchases is recorded too.",
            "Type the rate you charge (e.g. 8.25). You can change it per sale or "
            "later. Leave 0 if you don't charge sales tax."))
        if self.locked:
            self.add_locked(); return
        from PySide6.QtWidgets import QDoubleSpinBox
        row = wizard._company_row()
        self._rate = QDoubleSpinBox()
        self._rate.setSuffix(" %"); self._rate.setDecimals(3); self._rate.setMaximum(30)
        self._rate.setValue(float(row.get("sales_tax_rate") or 0))
        self._rate.setFixedWidth(120)
        r = QHBoxLayout(); r.addWidget(QLabel("Sales tax rate:"))
        r.addWidget(self._rate); r.addStretch()
        self._lay.addLayout(r)
        self.add(_skip_note())

    def save(self):
        self.wiz._update_company(sales_tax_rate=self._rate.value())


class BillWisePage(_Page):
    feature = "bill_wise_refs"; tier = "Pro"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Track invoices bill-by-bill")
        self.setSubTitle("“Against Reference” — invoice-level outstanding.")
        self.add(_why_what(
            "See exactly which invoices are still open for each customer/supplier and how "
            "overdue each one is — not just their overall balance.",
            "One extra click when recording a receipt/payment: “Allocate to bills…”. If you "
            "don't turn it on, parties are tracked by their overall balance as usual."))
        if self.locked:
            self.add_locked(); return
        self._chk = _Choice("Yes — let me allocate receipts/payments to specific bills")
        self._chk.setChecked(bool(prefs.get("bill_wise_enabled", True)))
        self.add(self._chk)

    def save(self):
        prefs.set("bill_wise_enabled", self._chk.isChecked())


class AIChoicePage(_Page):
    feature = "ai_document_reader"; tier = "Pro"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("AI document reading")
        self.setSubTitle("Let AI read invoices and draft the vouchers.")
        self.add(_why_what(
            "Drop or email an invoice and the AI reads it, decides its type and drafts the "
            "voucher for you to approve — a big time saver on data entry.",
            "Pick how the AI is powered. You can change this any time."))
        if self.locked:
            self.add_locked(); return

        self._wallet = _Choice("Use our AI — pay per document from your wallet (simplest, nothing to set up)")
        self._byok = _Choice("Use my own AI key — also unlocks the bulk Document Inbox (email / scan import)")
        g = QButtonGroup(self); g.setExclusive(True)
        g.addButton(self._wallet); g.addButton(self._byok)
        from core.user_prefs import prefs
        (self._byok if prefs.get("ai_mode", "wallet") == "byok"
         else self._wallet).setChecked(True)
        self.add(self._wallet); self.add(self._byok)

        from core.ai_routing import routing
        self._key = QLineEdit(routing.get_own_key())
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("sk-ant-...")
        r = QHBoxLayout(); r.addWidget(QLabel("Your Anthropic key:")); r.addWidget(self._key, 1)
        self._lay.addLayout(r)
        self._get = QPushButton("Get a key (opens console.anthropic.com)")
        self._get.clicked.connect(lambda: QDesktopServices.openUrl(
            QUrl("https://console.anthropic.com/settings/keys")))
        self.add(self._get)

        self._byok.toggled.connect(self._sync)
        self._sync(self._byok.isChecked())

    def _sync(self, byok_on: bool):
        self._key.setEnabled(byok_on)
        self._get.setEnabled(byok_on)

    def save(self):
        from core.user_prefs import prefs
        from core.ai_routing import routing
        byok = self._byok.isChecked()
        if byok:
            prefs.set("ai_mode", "byok")
            k = self._key.text().strip()
            if k:
                routing.set_own_key(k)
        else:
            prefs.set("ai_mode", "wallet")
        # Activate one AI pipeline, deactivate the other. The menu/feature gates
        # honour these so only the chosen path is shown.
        prefs.set("document_inbox_active", byok)
        prefs.set("ai_doc_reader_active", not byok)


class EmailPage(_Page):
    feature = "ai_document_reader"; tier = "Pro"

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
        if self.locked:
            self.add_locked(); return
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
    feature = "ai_document_reader"; tier = "Pro"

    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Scan paper invoices straight in")
        self.setSubTitle("Point your scanner at one folder.")
        folder = wizard._inbox_folder()
        self.add(_why_what(
            "Anything your scanner saves into the inbox folder is picked up by the Document "
            "Inbox automatically — no importing.",
            "Set your scanner software's save location to the folder below, once."))
        if self.locked:
            self.add_locked(); return
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
            f"That's it — you're ready to use {branding.PRODUCT_NAME}.\n\nYou can run this wizard "
            "again any time from the “Setup” button to add or change any of these settings."))
        self.add(_why_what(
            "The user manual walks through every screen with examples — handy while "
            "you're finding your feet.",
            "Opens the PDF in your browser; save it for offline reading."))
        man = QPushButton("📘  Download the user manual")
        man.setCursor(Qt.CursorShape.PointingHandCursor)
        man.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(_manual_url())))
        self.add(man)

    def save(self):
        prefs.set("setup_wizard_done", True)
        # Remember the plan we ran for, so an upgrade can re-open the wizard
        # focused on the newly-unlocked features.
        try:
            prefs.set("setup_wizard_plan",
                      (getattr(self.wiz.lmgr, "plan", "") or "FREE"))
        except Exception:
            pass


class BusinessProfilePage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Your business")
        self.setSubTitle("Identity that appears on invoices and reports.")
        self.add(_why_what(
            "Your business name, PAN and address print on invoices, statements and "
            "reports, and identify your books.",
            "Type them once — you can edit them later from Settings."))
        row = wizard._company_row()
        self._name = QLineEdit(row.get("name") or ""); self._name.setPlaceholderText("Business / firm name")
        self._pan = QLineEdit(row.get("pan") or ""); self._pan.setPlaceholderText("PAN (10 chars)")
        self._addr = QLineEdit(row.get("address") or ""); self._addr.setPlaceholderText("Address")
        for lab, w in (("Name", self._name), ("PAN", self._pan), ("Address", self._addr)):
            r = QHBoxLayout(); r.addWidget(QLabel(lab + ":")); r.addWidget(w, 1)
            self._lay.addLayout(r)

        # Books year (financial year). Askable once, early; LOCKED read-only
        # once vouchers exist — changing it then would mislabel posted vouchers.
        self.add(QLabel("Books year — when your accounting year starts:"))
        cur_fy = row.get("fy_start") or "04-01"
        self._fy = None
        if self._fy_locked(wizard):
            msg = QLabel(f"🔒  {_fy_label(cur_fy)}  —  set when you started; it can't be "
                         "changed now that vouchers are posted (that would mislabel them).")
            msg.setWordWrap(True)
            msg.setStyleSheet(f"color:{THEME['text_secondary']}; font-size:12px;")
            self.add(msg)
        else:
            self._fy = QComboBox()
            for val, lbl in _FY_PRESETS:
                self._fy.addItem(lbl, val)
            i = self._fy.findData(cur_fy)
            if i < 0:
                self._fy.addItem(f"Custom ({cur_fy})", cur_fy); i = self._fy.findData(cur_fy)
            self._fy.setCurrentIndex(max(0, i))
            self.add(self._fy)
            note = QLabel("Set this before posting your first voucher — it locks afterwards.")
            note.setWordWrap(True)
            note.setStyleSheet(f"color:{THEME['text_dim']}; font-size:11px; font-style:italic;")
            self.add(note)
        self.add(_skip_note())

    def _fy_locked(self, wizard) -> bool:
        try:
            r = wizard.db.execute(
                "SELECT COUNT(*) AS c FROM vouchers WHERE company_id=?",
                (wizard.company_id,)).fetchone()
            return bool(r and (r["c"] if hasattr(r, "keys") else r[0]))
        except Exception:
            return False

    def save(self):
        fields = dict(
            name=self._name.text().strip(),
            pan=self._pan.text().strip().upper(),
            address=self._addr.text().strip())
        if self._fy is not None:          # only settable while unlocked
            fields["fy_start"] = self._fy.currentData()
        self.wiz._update_company(**fields)


class VoucherFormPage(_Page):
    def __init__(self, wizard):
        super().__init__(wizard)
        self.setTitle("Entry & reconciliation")
        self.setSubTitle("Small touches for daily work.")
        self.add(_why_what(
            "A success popup confirms each posting; switching it off lets you post "
            "silently and faster. When reconciling, a comment prompt records why you "
            "ignored a bank line (duplicate, already booked, etc.).",
            "Two toggles — vouchers and reconciliation work either way."))
        self._toast = _Choice("Show a success popup after posting a voucher")
        self._toast.setChecked(bool(prefs.get("after_post_toast", True)))
        self.add(self._toast)
        self._reco = _Choice("Ask for a comment when ignoring a bank-statement line")
        self._reco.setChecked(bool(prefs.get("bank_reco_comment_on_ignore", True)))
        self.add(self._reco)

    def save(self):
        prefs.set("after_post_toast", self._toast.isChecked())
        prefs.set("bank_reco_comment_on_ignore", self._reco.isChecked())


# ── Wizard ──────────────────────────────────────────────────────────────────────

class SetupWizard(QWizard):
    def __init__(self, db, company_id: int, slug: str, lmgr, parent=None):
        super().__init__(parent)
        self.db = db
        self.company_id = company_id
        self.slug = slug
        self.lmgr = lmgr
        self.setWindowTitle(f"{branding.PRODUCT_NAME} — Quick Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.resize(620, 520)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        # All-tier: every page is added; locked features show an upgrade teaser
        # instead of being hidden. RWA HQ overrides _page_set() for its pages.
        self.addPage(WelcomePage(self))
        self.addPage(LookFeelPage(self))
        for page_cls in self._page_set():
            self.addPage(page_cls(self))
        self.addPage(BackupPage(self))
        self.addPage(FinishPage(self))

    # ── product hook + shared helpers ──────────────────────────────────────
    def _page_set(self):
        """Middle pages between Welcome and Backup. Accounts HQ default; RWA HQ
        overrides with its own page set."""
        try:
            from core import country
            if country.active_profile().tax_system == "US_SALES_TAX":
                # Books HQ: swap India GST/TDS pages for the US sales-tax page.
                return [BusinessProfilePage, SalesTaxPage, BillWisePage,
                        AIChoicePage, EmailPage, ScannerPage, VoucherFormPage]
        except Exception:
            pass
        return [BusinessProfilePage, GSTPage, TDSPage, BillWisePage,
                AIChoicePage, EmailPage, ScannerPage, VoucherFormPage]

    def _has(self, feature: str) -> bool:
        try:
            return bool(self.lmgr.has_feature(feature))
        except Exception:
            return False

    def _open_upgrade(self):
        """Open the upgrade page in the browser WITHOUT closing the wizard.
        (Previously this closed the wizard and navigated the app, which lost the
        user's place — they had to restart. Never close the wizard from here.)"""
        QDesktopServices.openUrl(QUrl("https://apps.ai-consultants.in/"))

    # ── helpers shared by pages ────────────────────────────────────────────
    def _company_row(self) -> dict:
        try:
            r = self.db.execute(
                "SELECT name, gstin, state_code, gst_username, tan, pan, address, fy_start "
                "FROM companies WHERE id=?",
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
