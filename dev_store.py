"""
DEV-ONLY launcher for the Store HQ window (US / Books HQ flavor).

Opens the store screens on an existing company's books + its own store DB
(<company>_store.db). NOT shipped. Run:  python dev_store.py [company_slug]
"""
import sys

from core import country, branding
country.set_active("US")
country.reset_active = lambda: None
branding.apply_country_branding()

from PySide6.QtWidgets import QApplication  # noqa: E402
from core.models import Database            # noqa: E402
from core.account_tree import AccountTree   # noqa: E402
from core.voucher_engine import VoucherEngine  # noqa: E402
from core.store import StoreDB, StoreEngine, StoreSales  # noqa: E402
from ui.store.store_window import StoreWindow  # noqa: E402


def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "krishan_sanghi_us"
    app = QApplication(sys.argv)
    try:
        from core.config import current_theme_mode
        from ui.theme import set_theme_mode, get_stylesheet
        set_theme_mode(current_theme_mode())
        app.setStyleSheet(get_stylesheet())
    except Exception:
        pass

    db = Database(slug); db.connect()
    row = db.execute("SELECT id, name FROM companies LIMIT 1").fetchone()
    if not row:
        print(f"No company in {slug}.db"); return
    cid, cname = row["id"], row["name"]
    tree = AccountTree(db, cid)
    eng = VoucherEngine(db, cid)
    se = StoreEngine(StoreDB.for_company(slug), eng, tree)
    ss = StoreSales(se)

    win = StoreWindow(se, ss, company_name=cname)
    win.show()
    app.exec()


if __name__ == "__main__":
    main()
