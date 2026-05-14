"""
License Manager
- Validates license key against server
- Caches license locally (7 day offline grace)
- Feature gate checks
- Transaction counter with overage logic
- Upgrade nudge calculations
"""
import json
import hashlib
import os
import platform
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, date, timedelta

from core.paths import license_file as _license_file_path

BASE_DIR     = Path(__file__).parent.parent
LICENSE_FILE = _license_file_path()
SERVER_URL   = os.environ.get(
    "ACCGENIE_LICENSE_SERVER",
    "https://license.accgenie.in/api/v1",
)

DEV_KEY = "ACCG-DEV-FULL"

PLANS = ["DEMO", "FREE", "STANDARD", "PRO", "PREMIUM"]

DEMO_TXN_LIMIT = 10  # full-feature trial cap

PLAN_LIMITS = {
    "DEMO":     DEMO_TXN_LIMIT,
    "FREE":     5_000,
    "STANDARD": 20_000,
    "PRO":      50_000,
    "PREMIUM":  100_000,
}

OVERAGE_RATES = {
    "DEMO":     0.0,
    "FREE":     0.0,
    "STANDARD": 0.30,
    "PRO":      0.30,
    "PREMIUM":  0.20,
}

PLAN_FEATURES = {
    # DEMO mirrors PREMIUM (everything unlocked) but is capped at
    # DEMO_TXN_LIMIT vouchers — see can_post_voucher().
    "DEMO": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_unlimited",
        "gst",
        "tds",
        "ai_document_reader",
        "verbal_entry",
        "auto_billing",
        "whatsapp",
        "audit_export",
        "api_access",
        "verticals",
    ],
    "FREE": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "backup",
    ],
    "STANDARD": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_2",
    ],
    "PRO": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_5",
        "gst",
        "tds",
        "ai_document_reader",
        "verbal_entry",
        "auto_billing",
    ],
    "PREMIUM": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
        "ledger_reconciliation",
        "book_migration",
        "backup",
        "multi_user_unlimited",
        "gst",
        "tds",
        "ai_document_reader",
        "verbal_entry",
        "auto_billing",
        "whatsapp",
        "audit_export",
        "api_access",
        "verticals",
    ],
}

FEATURE_UPGRADE_MAP = {
    "reports":             "STANDARD",
    "export_excel":        "STANDARD",
    "export_pdf":          "STANDARD",
    "bank_reconciliation":   "STANDARD",
    "ledger_reconciliation": "STANDARD",
    "book_migration":        "STANDARD",
    "gst":                 "PRO",
    "tds":                 "PRO",
    "ai_document_reader":  "PRO",
    "verbal_entry":        "PRO",
    "auto_billing":        "PRO",
    "whatsapp":            "PREMIUM",
    "audit_export":        "PREMIUM",
    "api_access":          "PREMIUM",
    "verticals":           "PREMIUM",
}

PLAN_PRICES = {
    "DEMO":     0,
    "FREE":     0,
    "STANDARD": 1999,
    "PRO":      4999,
    "PREMIUM":  9999,
}


class FeatureNotAvailable(Exception):
    def __init__(self, feature: str, current_plan: str, required_plan: str):
        self.feature      = feature
        self.current_plan = current_plan
        self.required_plan = required_plan
        super().__init__(f"{feature} requires {required_plan} plan")


class LicenseManager:

    def reload(self) -> None:
        """Re-read license.json from disk, discarding the in-memory copy.
        The License page calls this before refreshing its display because
        voucher_form increments txn_used through a *separate* LicenseManager
        instance — without a reload the page would show a stale count."""
        self._data = self._load_local()

    def __init__(self):
        self._data = self._load_local()

    # ── Machine ID ────────────────────────────────────────────────────────────

    @staticmethod
    def get_machine_id() -> str:
        raw = platform.node() + platform.machine()
        return hashlib.md5(raw.encode()).hexdigest()[:16]

    # ── Local cache ───────────────────────────────────────────────────────────

    def _load_local(self) -> dict:
        try:
            if LICENSE_FILE.exists():
                with open(LICENSE_FILE) as f:
                    return json.load(f)
        except Exception:
            pass
        return self._demo_license()

    def _demo_license(self) -> dict:
        """Default DEMO license for new installs — all features, 10 vouchers."""
        return {
            "license_key":     "DEMO",
            "plan":            "DEMO",
            "features":        PLAN_FEATURES["DEMO"],
            "txn_limit":       PLAN_LIMITS["DEMO"],
            "txn_used":        0,
            "user_limit":      1,
            "seats_allowed":   0,   # DEMO doesn't consume server-side seats
            "seats_used":      0,
            "expires_at":      "2099-12-31",
            "company_name":    "",
            "validated_at":    datetime.now().isoformat(),
            "offline_until":   (datetime.now() + timedelta(days=7)).isoformat(),
            "overage_count":   0,
        }

    def _drop_to_demo(self) -> None:
        """
        Reset the cached license to DEMO while preserving local voucher counts.
        Used when the server reports our seat was released elsewhere, or after
        the user clicks 'Release this machine's seat'.
        """
        self._sync_local_counters()
        kept_txn_used      = self._data.get("txn_used", 0)
        kept_overage_count = self._data.get("overage_count", 0)
        self._data = self._demo_license()
        self._data["txn_used"]      = kept_txn_used
        self._data["overage_count"] = kept_overage_count
        self._save_local()

    def _save_local(self):
        LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LICENSE_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

    def _sync_local_counters(self) -> None:
        """Pull the latest txn_used / overage_count from disk into _data.

        These are LOCAL tallies that other LicenseManager instances mutate
        independently — voucher_form increments txn_used through its own
        instance on every post. Any code path that rewrites the whole
        license.json blob (validate, startup re-validate, drop-to-demo)
        must sync these first, or it clobbers a fresh count with its own
        stale in-memory value. That bug silently reset the count whenever
        the License page re-validated against the server."""
        disk = self._load_local()
        self._data["txn_used"] = disk.get(
            "txn_used", self._data.get("txn_used", 0)
        )
        self._data["overage_count"] = disk.get(
            "overage_count", self._data.get("overage_count", 0)
        )

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def plan(self) -> str:
        return self._data.get("plan", "FREE")

    @property
    def license_key(self) -> str:
        return self._data.get("license_key", "")

    @property
    def txn_used(self) -> int:
        return self._data.get("txn_used", 0)

    @property
    def txn_limit(self) -> int:
        return self._data.get("txn_limit", PLAN_LIMITS.get(self.plan, 5000))

    @property
    def overage_count(self) -> int:
        return self._data.get("overage_count", 0)

    @property
    def expires_at(self) -> str:
        return self._data.get("expires_at", "2099-12-31")

    @property
    def is_expired(self) -> bool:
        try:
            return date.today() > date.fromisoformat(self.expires_at)
        except Exception:
            return False

    @property
    def days_to_expiry(self) -> int:
        try:
            return (date.fromisoformat(self.expires_at) - date.today()).days
        except Exception:
            return 999

    @property
    def user_limit(self) -> int:
        if self.plan == "PREMIUM":
            return 999
        return self._data.get("user_limit", 1)

    @property
    def seats_allowed(self) -> int:
        return int(self._data.get("seats_allowed") or 0)

    @property
    def seats_used(self) -> int:
        return int(self._data.get("seats_used") or 0)

    @property
    def seats_remaining(self) -> int:
        return max(0, self.seats_allowed - self.seats_used)

    @property
    def company_name(self) -> str:
        return self._data.get("company_name", "")

    @property
    def txn_percent(self) -> float:
        if self.txn_limit == 0:
            return 0.0
        return min(100.0, self.txn_used / self.txn_limit * 100)

    @property
    def is_in_grace(self) -> bool:
        """Is this a cached license within the 7-day offline grace period?"""
        try:
            until = datetime.fromisoformat(self._data.get("offline_until", ""))
            return datetime.now() < until
        except Exception:
            return False

    # ── Feature checks ────────────────────────────────────────────────────────

    def has_feature(self, feature: str) -> bool:
        if self.is_expired:
            read_features = [
                "daybook", "ledger_balances",
                "reports", "export_excel", "export_pdf",
            ]
            return feature in read_features
        features = self._data.get("features", PLAN_FEATURES.get(self.plan, []))
        return feature in features

    def require_feature(self, feature: str):
        if not self.has_feature(feature):
            required = FEATURE_UPGRADE_MAP.get(feature, "PREMIUM")
            raise FeatureNotAvailable(feature, self.plan, required)

    def upgrade_required_for(self, feature: str) -> str | None:
        if self.has_feature(feature):
            return None
        return FEATURE_UPGRADE_MAP.get(feature, "PREMIUM")

    # ── Transaction management ────────────────────────────────────────────────

    def can_post_voucher(self) -> tuple[bool, str, float]:
        """
        Returns (allowed, message, overage_cost).
        FREE plan: hard block at limit.
        Paid plans: always allow, track overage.
        """
        if self.is_expired:
            return False, "License expired. Renew to post new vouchers.", 0.0

        used  = self.txn_used
        limit = self.txn_limit

        if self.plan == "DEMO":
            if used >= limit:
                return (
                    False,
                    f"Demo limit of {limit} transactions reached. "
                    f"Activate a paid plan to continue.",
                    0.0,
                )
            return True, "", 0.0

        if self.plan == "FREE":
            if used >= limit:
                return (
                    False,
                    f"Free plan limit of {limit:,} transactions reached. "
                    f"Upgrade to continue.",
                    0.0,
                )
            return True, "", 0.0

        # Paid plans — always allow
        if used < limit:
            return True, "", 0.0

        # Overage
        overage = used - limit + 1
        rate    = OVERAGE_RATES.get(self.plan, 0.30)
        cost    = round(overage * rate, 2)
        return (
            True,
            f"Over plan limit by {overage:,} txn. Overage: Rs.{cost:.2f}",
            cost,
        )

    def record_voucher_posted(self):
        """Call after every successful voucher post."""
        # Sync first so concurrent increments from other instances aren't lost.
        self._sync_local_counters()
        self._data["txn_used"] = self._data.get("txn_used", 0) + 1
        if self.txn_used > self.txn_limit:
            self._data["overage_count"] = self._data.get("overage_count", 0) + 1
        self._save_local()

    def upgrade_savings(self) -> dict | None:
        """Calculate if upgrading would save money. Returns suggestion dict or None."""
        if self.plan == "PREMIUM":
            return None
        overage = self.overage_count
        if overage < 100:
            return None

        rate         = OVERAGE_RATES.get(self.plan, 0.30)
        overage_cost = round(overage * rate, 2)
        next_plan    = PLANS[PLANS.index(self.plan) + 1]
        upgrade_cost = PLAN_PRICES[next_plan] - PLAN_PRICES[self.plan]

        if overage_cost > upgrade_cost * 0.5:
            return {
                "current_plan": self.plan,
                "next_plan":    next_plan,
                "overage_txn":  overage,
                "overage_cost": overage_cost,
                "upgrade_cost": upgrade_cost,
                "would_save":   round(overage_cost - upgrade_cost, 2),
            }
        return None

    # ── Server validation ─────────────────────────────────────────────────────

    def validate_with_server(self, license_key: str) -> tuple[bool, str]:
        """Validates key with license server. Returns (success, message)."""
        if license_key == DEV_KEY:
            # Re-sync local counters from disk before rewriting the blob.
            self._sync_local_counters()
            self._data.update({
                "license_key":   DEV_KEY,
                "plan":          "PREMIUM",
                "features":      PLAN_FEATURES["PREMIUM"],
                "txn_limit":     PLAN_LIMITS["PREMIUM"],
                "txn_used":      self._data.get("txn_used", 0),
                "user_limit":    999,
                "seats_allowed": 0,   # DEV bypasses seat counting
                "seats_used":    0,
                "expires_at":    "2099-12-31",
                "company_name":  "Developer",
                "validated_at":  datetime.now().isoformat(),
                "offline_until": (datetime.now() + timedelta(days=3650)).isoformat(),
                "overage_count": 0,
            })
            self._save_local()
            return True, "Developer key activated — all features unlocked."

        try:
            payload = json.dumps({
                "license_key": license_key,
                "machine_id":  self.get_machine_id(),
                "app_version": "1.0.4",
            }).encode()

            req = urllib.request.Request(
                f"{SERVER_URL}/license/validate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

            if not data.get("valid"):
                return False, data.get("error", "Invalid license key")

            plan = data.get("plan", "FREE")
            # Re-sync local counters from disk before rewriting the blob —
            # voucher_form may have incremented txn_used since this instance
            # last loaded.
            self._sync_local_counters()
            self._data.update({
                "license_key":   license_key,
                "plan":          plan,
                "features":      data.get("features", PLAN_FEATURES["FREE"]),
                "txn_limit":     data.get("txn_limit", PLAN_LIMITS.get(plan, 5000)),
                # txn_used is tracked locally — the server does NOT track it
                # yet and always returns 0. Overwriting with the server value
                # silently reset the customer's count on every License-page
                # refresh. Preserve whatever's already on disk.
                "txn_used":      self._data.get("txn_used", 0),
                "user_limit":    data.get("user_limit", 1),
                "seats_allowed": data.get("seats_allowed") or 0,
                "seats_used":    data.get("seats_used") or 0,
                "expires_at":    data.get("expires_at", "2026-12-31"),
                "company_name":  data.get("company_name", ""),
                "validated_at":  datetime.now().isoformat(),
                "offline_until": (datetime.now() + timedelta(days=7)).isoformat(),
                # overage_count is also a local tally — don't reset it.
                "overage_count": self._data.get("overage_count", 0),
            })
            self._save_local()
            return True, "License activated!"

        except urllib.error.URLError:
            if license_key == self.license_key and self.is_in_grace:
                return True, "Server unreachable — using cached license."
            return False, "Cannot reach license server. Check internet connection."
        except Exception as e:
            return False, str(e)

    def refresh_from_server(self):
        """Silent background refresh."""
        if self.license_key in ("DEMO", "FREE-DEMO", DEV_KEY, "", None):
            return
        self.validate_with_server(self.license_key)

    def validate_on_startup(self, timeout: float = 3.0) -> None:
        """
        Silent re-validation at app startup. Falls back to the cached license
        on any network error so a slow / offline boot doesn't block the UI.
        Caller should run this on a worker thread to avoid blocking the splash.
        """
        if self.license_key in ("DEMO", "FREE-DEMO", DEV_KEY, "", None):
            return
        try:
            payload = json.dumps({
                "license_key": self.license_key,
                "machine_id":  self.get_machine_id(),
                "app_version": "1.0.4",
            }).encode()
            req = urllib.request.Request(
                f"{SERVER_URL}/license/validate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
            if not data.get("valid"):
                return  # Don't crash startup if server says revoked — UI surfaces it later.
            # Sync local counters before the whole-blob save so a voucher
            # posted during startup isn't clobbered.
            self._sync_local_counters()
            self._data["seats_allowed"] = data.get("seats_allowed") or 0
            self._data["seats_used"]    = data.get("seats_used") or 0
            self._save_local()
        except Exception:
            # Offline / DNS / timeout — keep the cached license, the 7-day
            # grace handles posting.
            return

    def release_this_machine_seat(self) -> tuple[bool, str]:
        """
        Tell the server to free this machine's seat for this license key, then
        drop the local cache to DEMO (preserving the local voucher count).
        Returns (success, message) — success means the seat was released
        cleanly OR was already absent server-side. Network failure returns
        False; caller should keep retrying instead of force-dropping.
        """
        key = self.license_key
        if key in ("DEMO", "FREE-DEMO", DEV_KEY, "", None):
            return False, "No paid license is active on this machine."
        try:
            payload = json.dumps({
                "license_key": key,
                "machine_id":  self.get_machine_id(),
            }).encode()
            req = urllib.request.Request(
                f"{SERVER_URL}/license/deactivate",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
            if not data.get("ok"):
                return False, data.get("error") or "Server refused to release the seat."
            self._drop_to_demo()
            return True, (
                "This machine's seat has been released. "
                "You can activate the same key on a different machine now."
            )
        except urllib.error.URLError:
            return False, "Cannot reach license server. Check internet connection."
        except Exception as e:
            return False, str(e)

    # ── Display helpers ───────────────────────────────────────────────────────

    def status_summary(self) -> dict:
        used    = self.txn_used
        limit   = self.txn_limit
        overage = max(0, used - limit)
        rate    = OVERAGE_RATES.get(self.plan, 0.30)
        return {
            "plan":           self.plan,
            "license_key":    self.license_key,
            "txn_used":       used,
            "txn_limit":      limit,
            "txn_pct":        self.txn_percent,
            "overage_count":  overage,
            "overage_cost":   round(overage * rate, 2),
            "expires_at":     self.expires_at,
            "days_to_expiry": self.days_to_expiry,
            "is_expired":     self.is_expired,
        }
