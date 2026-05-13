"""
Credit Manager — server is the source of truth (Phase 2b).

The license server holds the authoritative balance and meters AI usage
inside `/api/v1/ai/proxy`. This client-side helper:

  - Reads balance via GET /api/v1/credits/balance (cached locally for offline).
  - Surfaces a `balance_display` for UI.
  - No longer deducts locally — that happens server-side per AI call.

The local `credits.json` is now a *display cache only*. It exists so the
License page / AI screens can show "₹4.23 remaining" even when the
server is unreachable; the next online call refreshes it.
"""
import json
import urllib.error
import urllib.request
from datetime import datetime

from core.paths import credits_file as _credits_file_path

CREDIT_FILE = _credits_file_path()


class CreditManager:

    # Legacy per-page rates — kept for the doc-reader cost estimate display
    # (showing "this file will cost ~Rs.X" before sending). Server is the
    # one that actually meters tokens, so these are now approximate.
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

    # ── Server sync ───────────────────────────────────────────────────────────

    def refresh_from_server(self) -> bool:
        """
        Hit GET /api/v1/credits/balance and update the local cache.
        Returns True on success, False on any network / auth failure (caller
        keeps showing the stale cached balance and tries again later).
        """
        try:
            from core.license_manager import LicenseManager, SERVER_URL
            mgr = LicenseManager()
            key = mgr.license_key
            if key in ("DEMO", "FREE-DEMO", "", None):
                return False
            url = (
                f"{SERVER_URL.rstrip('/')}"
                f"/credits/balance?license_key={key}&machine_id={mgr.get_machine_id()}"
            )
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            if not data.get("ok"):
                return False
            self._data["license_key"]   = key
            self._data["balance_paise"] = int(data.get("balance_paise", 0))
            self._save()
            return True
        except Exception:
            return False

    def can_afford(self, local_pages: int, claude_pages: int) -> bool:
        """
        Quick pre-flight check using the local cached balance. The server
        does the final gate inside /ai/proxy — this is just so the UI can
        warn "low balance" before kicking off a request.
        """
        cost = (local_pages * self.RATE_LOCAL_PAISE +
                claude_pages * self.RATE_CLAUDE_PAISE)
        return self.balance_paise >= cost

    def deduct(self, local_pages: int, claude_pages: int,
               filename: str = "") -> bool:
        """
        DEPRECATED in Phase 2b — the server deducts inside /ai/proxy now,
        based on actual tokens. This shim updates the local *cache* so the
        UI's "balance remaining" display stays roughly in sync between
        server roundtrips. Called from the bank-reco AI fallback path
        until that path is migrated to /ai/proxy.

        Returns True even if balance would go negative — the server will
        enforce the real gate.
        """
        cost = (local_pages * self.RATE_LOCAL_PAISE +
                claude_pages * self.RATE_CLAUDE_PAISE)
        self._data["balance_paise"] = max(0, self.balance_paise - cost)
        self._data.setdefault("usage_log", []).append({
            "timestamp":    datetime.now().isoformat(),
            "filename":     filename,
            "local_pages":  local_pages,
            "claude_pages": claude_pages,
            "cost_paise":   cost,
            "local_only":   True,                  # not yet reconciled with server
        })
        self._save()
        return True

    def note_server_charge(self, paise: int) -> None:
        """
        Update the local cache after a server-metered AI call. Called by
        ai/ai_client when /ai/proxy responds with x-accgenie-paise-charged
        and x-accgenie-balance-paise headers.
        """
        self._data["balance_paise"] = max(0, self.balance_paise - paise)
        self._save()

    def set_balance(self, paise: int) -> None:
        """Used by /ai/proxy response headers — server tells us the new
        authoritative balance, we cache it."""
        self._data["balance_paise"] = max(0, int(paise))
        self._save()

    def add_credits(self, paise: int):
        """Local cache bump after the server confirms a topup."""
        self._data["balance_paise"] += paise
        self._save()

    def get_usage_log(self) -> list:
        return self._data.get("usage_log", [])

    def add_demo_credits(self):
        """Add Rs.50 demo credits — local cache only.
        Real demo credits should be granted by the server via /admin/credits/{key}/topup."""
        self.add_credits(5000)
