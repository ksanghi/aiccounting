"""Store HQ — main window: sidebar nav + the store screens, wired to the store
backend (StoreEngine + StoreSales). Ctrl+Q opens the tile launcher."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QStackedWidget,
    QLabel, QButtonGroup,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from ui.theme import THEME
from core import branding
from ui.store.dashboard_page import DashboardPage
from ui.store.pos_page import POSPage
from ui.store.inventory_page import InventoryPage
from ui.store.purchasing_page import PurchasingPage
from ui.store.customers_page import CustomersPage
from ui.store.returns_page import ReturnsPage
from ui.store.settings_page import SettingsPage
from ui.store.store_launcher import StoreLauncher


class StoreWindow(QMainWindow):
    # roadmap tiles shown (disabled) in the launcher so the scope is visible
    COMING_SOON = [("AI Assistant", "🤖"), ("Multi-location sync", "🔗")]

    def __init__(self, store_engine, store_sales, company_name: str = "", parent=None):
        super().__init__(parent)
        self.se = store_engine
        self.ss = store_sales
        self.setWindowTitle(f"{branding.PRODUCT_NAME} — Store — {company_name}".strip(" —"))
        self.resize(1180, 760)

        central = QWidget()
        h = QHBoxLayout(central)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        side = QWidget()
        side.setFixedWidth(196)
        side.setStyleSheet(f"background:{THEME.get('bg_sidebar', THEME.get('bg_panel', '#10182a'))};")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(10, 16, 10, 16)
        sv.setSpacing(4)
        brand = QLabel("Store HQ")
        brand.setStyleSheet(f"font-size:17px; font-weight:bold; color:{THEME['accent']}; padding:8px 6px;")
        sv.addWidget(brand)

        self.stack = QStackedWidget()
        # (label, icon, widget)
        self._pages = [
            ("Dashboard",  "📊", DashboardPage(store_engine, store_sales)),
            ("Counter",    "🛒", POSPage(store_sales, store_engine)),
            ("Inventory",  "📦", InventoryPage(store_engine)),
            ("Purchasing", "🏭", PurchasingPage(store_engine)),
            ("Customers",  "👥", CustomersPage(store_sales, store_engine)),
            ("Returns",    "↩",  ReturnsPage(store_sales, store_engine)),
            ("Settings",   "⚙",  SettingsPage(store_engine, store_sales)),
        ]
        self._grp = QButtonGroup(self)
        for idx, (label, icon, page) in enumerate(self._pages):
            self.stack.addWidget(page)
            b = QPushButton(f"  {icon}   {label}")
            b.setCheckable(True)
            b.setStyleSheet("QPushButton{text-align:left; padding:10px 12px; border:none; border-radius:8px;}"
                            "QPushButton:checked{background:" + THEME["accent"] + "; color:white;}")
            b.clicked.connect(lambda _=False, i=idx: self._select(i))
            self._grp.addButton(b)
            sv.addWidget(b)
        sv.addStretch()
        menu_hint = QPushButton("  ☰   Menu  (Ctrl+Q)")
        menu_hint.setStyleSheet(
            f"QPushButton{{text-align:left; padding:10px 12px; border:1px solid {THEME['border']};"
            f"border-radius:8px; color:{THEME['text_secondary']};}}"
            f"QPushButton:hover{{border-color:{THEME['accent']}; color:{THEME['accent']};}}")
        menu_hint.clicked.connect(self._open_menu)
        sv.addWidget(menu_hint)

        h.addWidget(side)
        h.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self._launcher = StoreLauncher(self)
        self._grp.buttons()[0].setChecked(True)
        self._go(0)

        QShortcut(QKeySequence("Ctrl+Q"), self).activated.connect(self._open_menu)
        QShortcut(QKeySequence(Qt.Key.Key_Menu), self).activated.connect(self._open_menu)
        for i in range(len(self._pages)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self).activated.connect(
                lambda _=False, idx=i: self._select(idx))

    def _open_menu(self):
        self._launcher.toggle()

    def _select(self, i: int):
        self._grp.buttons()[i].setChecked(True)
        self._go(i)

    def _go(self, i: int):
        self.stack.setCurrentIndex(i)
        page = self._pages[i][2]
        if hasattr(page, "refresh"):
            try:
                page.refresh()
            except Exception:
                pass
