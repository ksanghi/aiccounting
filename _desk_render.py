# Render real desktop AHQ page widgets offscreen → PNG, for diffing vs the web port.
import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from core.models import Database
from core.account_tree import AccountTree
from ui.theme import set_theme_mode, get_stylesheet

app = QApplication([])
set_theme_mode("light")
app.setStyleSheet(get_stylesheet())

db = Database("sunrise_traders"); db.connect()
cid = db.execute("SELECT id FROM companies LIMIT 1").fetchone()["id"]
tree = AccountTree(db, cid)

OUT = os.path.dirname(os.path.abspath(__file__))


def shot(widget, name, w=1120, h=820):
    widget.resize(w, h)
    widget.setStyleSheet(get_stylesheet())
    widget.show()
    app.processEvents(); app.processEvents()
    widget.grab().save(os.path.join(OUT, name))
    print("saved", name)


# Dashboard (home_page.HomePage)
try:
    from ui.home_page import HomePage
    shot(HomePage(db, cid, tree), "_desk_home.png")
except Exception as e:
    print("home FAIL:", e)

# Report pages (_ReportBase(rpt))
try:
    from core.reports_engine import ReportsEngine
    import ui.reports_page as RP
    rpt = ReportsEngine(db, cid)
    for cls, fn in [("ProfitLossPage", "_desk_pnl.png"), ("BalanceSheetPage", "_desk_bs.png"),
                    ("TrialBalancePage", "_desk_tb.png"), ("CashBookPage", "_desk_cash.png"),
                    ("BankBookPage", "_desk_bank.png"), ("ReceiptsPaymentsPage", "_desk_rp.png")]:
        try:
            wd = getattr(RP, cls)(rpt)
            if hasattr(wd, "refresh"):
                wd.refresh()
            shot(wd, fn, 1120, 760)
        except Exception as e:
            print(cls, "FAIL:", e)
except Exception as e:
    print("reports FAIL:", e)
