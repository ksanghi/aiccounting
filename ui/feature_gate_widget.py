"""
Feature gate widget — shows upgrade prompt when user tries to access a locked feature.
"""
import webbrowser
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton,
)
from PyQt6.QtCore import Qt

from ui.theme import THEME
from core.license_manager import PLAN_PRICES, PLAN_FEATURES

UPGRADE_URL = "https://aiccounting.in/pricing"


class FeatureGateWidget(QWidget):
    """Drop-in replacement for any locked page. Shows a friendly upgrade prompt."""

    def __init__(self, feature: str, required_plan: str, current_plan: str,
                 feature_label: str = "", parent=None):
        super().__init__(parent)
        self._build_ui(feature, required_plan, current_plan, feature_label)

    def _build_ui(self, feature, required_plan, current_plan, feature_label):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        lock = QLabel("🔒")
        lock.setStyleSheet("font-size:40px;")
        lock.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(lock)

        name = QLabel(feature_label or feature.replace("_", " ").title())
        name.setStyleSheet(
            f"font-size:18px; font-weight:500; color:{THEME['text_primary']};"
        )
        name.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(name)

        price = PLAN_PRICES.get(required_plan, 0)
        msg = QLabel(
            f"This feature is available on the {required_plan} plan "
            f"(Rs.{price:,}/year).\n\n"
            f"You are currently on the {current_plan} plan."
        )
        msg.setStyleSheet(
            f"color:{THEME['text_secondary']}; font-size:12px;"
        )
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setWordWrap(True)
        layout.addWidget(msg)

        btn = QPushButton(f"Upgrade to {required_plan} →")
        btn.setObjectName("btn_primary")
        btn.setFixedHeight(40)
        btn.setFixedWidth(220)
        btn.clicked.connect(lambda: webbrowser.open(UPGRADE_URL))
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

        features = PLAN_FEATURES.get(required_plan, [])
        hint_items = [
            f.replace("_", " ").title()
            for f in features
            if f != "vouchers"
        ][:5]
        hint = QLabel(
            required_plan + " includes: " + " · ".join(hint_items)
        )
        hint.setStyleSheet(
            f"color:{THEME['text_dim']}; font-size:10px;"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setWordWrap(True)
        layout.addWidget(hint)
