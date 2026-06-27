"""Headless smoke test for the 1.0.31 UI changes.

Builds a real MainWindow against the seeded demo company under the OFFSCREEN
Qt platform, then exercises the new entry points:
  • the tile launcher populates (exercises the Quick Setup action-tile)
  • the status-bar  ⚙ Setup  button is wired to open_setup_wizard
  • the Quick Setup launcher tile is wired to open_setup_wizard
  • the window icon is set (non-null)

open_setup_wizard is stubbed at the CLASS level before construction, so the
modal wizard never actually opens (which would block headlessly).
"""
import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.setdefault("APP_LICENSE_PRODUCT", "accgenie")
os.environ["ACCGENIE_DATA_DIR"] = os.path.join(os.environ["APPDATA"], "AccGenie")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from PySide6.QtWidgets import QApplication, QPushButton, QLabel  # noqa: E402

app = QApplication(sys.argv)

# Mirror main(): the app-level window icon (windows inherit it).
from PySide6.QtGui import QIcon                                   # noqa: E402
from core import branding                                        # noqa: E402
_ico = QIcon(branding.icon_path())
app.setWindowIcon(_ico)
if _ico.isNull():
    print("WARN: QIcon(branding.icon_path()) is NULL — icon file failed to load")

# Stub the wizard + the update check at the class level BEFORE the window wires
# its buttons, so neither blocks nor hits the network during the test.
import ui.main_window as mw                                       # noqa: E402
fired = {"setup": 0}
mw.MainWindow.open_setup_wizard = lambda self, *a, **k: fired.__setitem__("setup", fired["setup"] + 1)
mw.MainWindow._check_updates = lambda self, *a, **k: None

from core.models import Database                                 # noqa: E402
from core.account_tree import AccountTree                        # noqa: E402
from core.voucher_engine import VoucherEngine                    # noqa: E402

SLUG = "sharma_trading_co"
db = Database(SLUG)
db.connect()
cid = db.execute("SELECT id FROM companies LIMIT 1").fetchone()["id"]
tree = AccountTree(db, cid)
engine = VoucherEngine(db, cid)

from ui.main_window import MainWindow                            # noqa: E402
w = MainWindow(db, cid, tree, engine)
w.show()
app.processEvents()

problems = []

# 1) window icon present
if w.windowIcon().isNull():
    problems.append("window icon is NULL (taskbar would show default)")

# 2) status-bar setup button exists + wired
btn = getattr(w, "_setup_chrome_btn", None)
if btn is None:
    problems.append("status-bar _setup_chrome_btn missing")
else:
    btn.click()
    app.processEvents()
    if fired["setup"] < 1:
        problems.append("status-bar Setup button did not call open_setup_wizard")

# 3) launcher populates without error + has a Quick Setup tile that's wired
launcher = w._ensure_launcher()
launcher.open_launcher()       # runs _populate (exercises _make_action_tile)
app.processEvents()

def find_tile(root, text):
    for b in root.findChildren(QPushButton):
        for lab in b.findChildren(QLabel):
            if lab.text().strip().lower() == text.lower():
                return b
    return None

qs = find_tile(launcher, "Quick Setup")
if qs is None:
    problems.append("Quick Setup tile not found in launcher")
else:
    before = fired["setup"]
    qs.click()
    app.processEvents()
    if fired["setup"] <= before:
        problems.append("Quick Setup tile did not call open_setup_wizard")

# 4) page count sanity (the window built all its screens)
n_pages = len(getattr(w, "_pages", []))
if n_pages < 5:
    problems.append(f"only {n_pages} pages registered — window may be half-built")

print(f"pages registered: {n_pages}")
print(f"open_setup_wizard fired: {fired['setup']} time(s)")
if problems:
    print("SMOKE FAIL:")
    for p in problems:
        print("  -", p)
    sys.exit(1)
print("SMOKE OK: window builds, icon set, both Setup entry points wired, launcher populates.")
sys.exit(0)
