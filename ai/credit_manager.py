"""
Credit Manager — tracks usage locally.
Billing server integration added later.
"""
import json
from pathlib import Path
from datetime import datetime

from core.paths import credits_file as _credits_file_path
CREDIT_FILE = _credits_file_path()


class CreditManager:

    RATE_LOCAL_PAISE  = 10    # Rs.0.10 per page
    RATE_CLAUDE_PAISE = 500   # Rs.5.00 per page

    def __init__(self):
        self._data = self._load()

    def _load(self) -> dict:
        try:
            if CREDIT_FILE.exists():
                with open(CREDIT_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"license_key": "", "balance_paise": 0, "usage_log": []}

    def _save(self):
        CREDIT_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(CREDIT_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    @property
    def license_key(self) -> str:
        return self._data.get("license_key", "")

    @license_key.setter
    def license_key(self, key: str):
        self._data["license_key"] = key
        self._save()

    @property
    def balance_paise(self) -> int:
        return self._data.get("balance_paise", 0)

    @property
    def balance_display(self) -> str:
        return f"Rs.{self.balance_paise / 100:.2f}"

    def can_afford(self, local_pages: int, claude_pages: int) -> bool:
        cost = (local_pages * self.RATE_LOCAL_PAISE +
                claude_pages * self.RATE_CLAUDE_PAISE)
        return self.balance_paise >= cost

    def deduct(self, local_pages: int, claude_pages: int,
               filename: str = "") -> bool:
        cost = (local_pages * self.RATE_LOCAL_PAISE +
                claude_pages * self.RATE_CLAUDE_PAISE)
        if self.balance_paise < cost:
            return False
        self._data["balance_paise"] -= cost
        self._data["usage_log"].append({
            "timestamp":    datetime.now().isoformat(),
            "filename":     filename,
            "local_pages":  local_pages,
            "claude_pages": claude_pages,
            "cost_paise":   cost,
        })
        self._save()
        return True

    def add_credits(self, paise: int):
        """Called when license server confirms payment."""
        self._data["balance_paise"] += paise
        self._save()

    def get_usage_log(self) -> list:
        return self._data.get("usage_log", [])

    def add_demo_credits(self):
        """Add Rs.50 demo credits for testing."""
        self.add_credits(5000)
