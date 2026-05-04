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
import platform
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime, date, timedelta

BASE_DIR     = Path(__file__).parent.parent
LICENSE_FILE = BASE_DIR / "data" / "license.json"
SERVER_URL   = "https://license.aiccounting.in/api/v1"

PLANS = ["FREE", "STANDARD", "PRO", "PREMIUM"]

PLAN_LIMITS = {
    "FREE":     5_000,
    "STANDARD": 20_000,
    "PRO":      50_000,
    "PREMIUM":  100_000,
}

OVERAGE_RATES = {
    "FREE":     0.0,
    "STANDARD": 0.30,
    "PRO":      0.30,
    "PREMIUM":  0.20,
}

PLAN_FEATURES = {
    "FREE": [
        "vouchers",
        "daybook",
        "ledger_balances",
    ],
    "STANDARD": [
        "vouchers",
        "daybook",
        "ledger_balances",
        "reports",
        "export_excel",
        "export_pdf",
        "bank_reconciliation",
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
    "bank_reconciliation": "STANDARD",
    "backup":              "STANDARD",
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
        """Default FREE license for new installs."""
        return {
            "license_key":   "FREE-DEMO",
            "plan":          "FREE",
            "features":      PLAN_FEATURES["FREE"],
            "txn_limit":     PLAN_LIMITS["FREE"],
            "txn_used":      0,
            "user_limit":    1,
            "expires_at":    "2099-12-31",
            "company_name":  "",
            "validated_at":  datetime.now().isoformat(),
            "offline_until": (datetime.now() + timedelta(days=7)).isoformat(),
            "overage_count": 0,
        }

    def _save_local(self):
        LICENSE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LICENSE_FILE, "w") as f:
            json.dump(self._data, f, indent=2)

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
        try:
            payload = json.dumps({
                "license_key": license_key,
                "machine_id":  self.get_machine_id(),
                "app_version": "1.0.0",
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
            self._data.update({
                "license_key":   license_key,
                "plan":          plan,
                "features":      data.get("features", PLAN_FEATURES["FREE"]),
                "txn_limit":     data.get("txn_limit", PLAN_LIMITS.get(plan, 5000)),
                "txn_used":      data.get("txn_used", 0),
                "user_limit":    data.get("user_limit", 1),
                "expires_at":    data.get("expires_at", "2026-12-31"),
                "company_name":  data.get("company_name", ""),
                "validated_at":  datetime.now().isoformat(),
                "offline_until": (datetime.now() + timedelta(days=7)).isoformat(),
                "overage_count": 0,
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
        if self.license_key in ("FREE-DEMO", "", None):
            return
        self.validate_with_server(self.license_key)

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
