"""
Phase 2b smoke test — credits ledger + /ai/proxy with a mocked Anthropic.

Patches `_forward_to_anthropic` so we don't make a real network call.
Verifies: balance lookup, topup, proxy auth, machine-binding check,
balance gate, paise deduction, AIUsageLog row insertion, error handling.

Run: python -m license_server._smoke_test_phase2b
"""
import os
import sys
import tempfile
from unittest.mock import patch

fd, tmp = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.remove(tmp)
os.environ["DATABASE_URL"]     = f"sqlite:///{tmp}"
os.environ["ADMIN_TOKEN"]      = "test-token"
os.environ["ANTHROPIC_API_KEY"] = "sk-ant-server-key"   # presence triggers proxy enable

from fastapi.testclient import TestClient                       # noqa: E402
from license_server.main import app                             # noqa: E402
from license_server.db import init_db                           # noqa: E402

init_db()
client = TestClient(app)
H_ADMIN = {"Authorization": "Bearer test-token"}


def _check(label, ok):
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if not ok:
        sys.exit(1)


# ── Setup: mint key, bind a machine ─────────────────────────────────────────
r = client.post("/admin/keys", headers=H_ADMIN, json={
    "plan": "PRO", "customer_email": "ai@x.com",
    "expires_at": "2027-01-01", "seats_allowed": 1,
})
_check("mint PRO key", r.status_code == 201)
key = r.json()["license_key"]

r = client.post("/api/v1/license/validate", json={
    "license_key": key, "machine_id": "machine-A", "app_version": "1.0",
})
_check("bind machine-A via validate", r.json().get("valid") is True)

# ── Credits: starts at 0 ────────────────────────────────────────────────────
r = client.get(f"/api/v1/credits/balance?license_key={key}&machine_id=machine-A")
_check("balance: ok",          r.json().get("ok") is True)
_check("balance: starts at 0", r.json().get("balance_paise") == 0)

# ── Topup: admin adds Rs 50 (5000 paise) ────────────────────────────────────
r = client.post(f"/admin/credits/{key}/topup", headers=H_ADMIN, json={
    "amount_paise": 5000, "ref": "demo-grant", "source": "admin",
})
_check("topup: 201/200",          r.status_code == 200)
_check("topup: balance=5000",     r.json().get("balance_paise") == 5000)

# ── /ai/proxy: low-balance gate ─────────────────────────────────────────────
# Drain to 50 paise (below min_balance_paise=100) via direct DB write.
# Topup is correctly positive-only so admins can't accidentally credit-bomb.
from license_server.db import SessionLocal               # noqa: E402
from license_server.models import Credit, License        # noqa: E402
from sqlalchemy import select                            # noqa: E402
with SessionLocal() as _s:
    _lic = _s.scalar(select(License).where(License.license_key == key))
    _c   = _s.scalar(select(Credit).where(Credit.license_id == _lic.id))
    _c.balance_paise = 50
    _s.commit()
_check("drained to 50 paise", True)

mock_response = {
    "id": "msg_test",
    "model": "claude-sonnet-4-20250514",
    "usage": {"input_tokens": 100, "output_tokens": 50},
    "content": [{"type": "text", "text": "hello"}],
}

with patch("license_server.main._forward_to_anthropic",
           return_value=(200, mock_response, "")):
    r = client.post("/api/v1/ai/proxy",
                    headers={
                        "x-license-key": key,
                        "x-machine-id":  "machine-A",
                        "x-feature":     "document_reader",
                        "Content-Type":  "application/json",
                    },
                    content=b'{"model":"claude-sonnet-4-20250514","max_tokens":100,"messages":[]}')
_check("low-balance gate: 402", r.status_code == 402)

# Top back up
r = client.post(f"/admin/credits/{key}/topup", headers=H_ADMIN, json={
    "amount_paise": 5000, "ref": "refill",
})
_check("refilled to 5050", r.json().get("balance_paise") == 5050)
balance_before_proxy = 5050

# ── /ai/proxy: happy path ───────────────────────────────────────────────────
with patch("license_server.main._forward_to_anthropic",
           return_value=(200, mock_response, "")):
    r = client.post("/api/v1/ai/proxy",
                    headers={
                        "x-license-key": key,
                        "x-machine-id":  "machine-A",
                        "x-feature":     "document_reader",
                        "Content-Type":  "application/json",
                    },
                    content=b'{"model":"claude-sonnet-4-20250514","max_tokens":100,"messages":[]}')
_check("proxy: 200", r.status_code == 200)
_check("proxy: response body forwarded",
       r.json().get("content", [{}])[0].get("text") == "hello")
# 100 input tokens × 76.5/1000 + 50 output × 382.5/1000 = 7.65 + 19.125 = 26.775 → ceil 27
paise_charged = int(r.headers.get("x-accgenie-paise-charged", "0"))
_check(f"proxy: paise_charged={paise_charged} (~27 expected)",
       25 <= paise_charged <= 30)
new_balance = int(r.headers.get("x-accgenie-balance-paise", "0"))
_check(f"proxy: new balance={new_balance}",
       new_balance == balance_before_proxy - paise_charged)

# ── /ai/proxy: rejects unknown machine ──────────────────────────────────────
with patch("license_server.main._forward_to_anthropic",
           return_value=(200, mock_response, "")):
    r = client.post("/api/v1/ai/proxy",
                    headers={
                        "x-license-key": key,
                        "x-machine-id":  "machine-NOT-BOUND",
                        "x-feature":     "document_reader",
                        "Content-Type":  "application/json",
                    },
                    content=b'{"model":"claude-sonnet-4-20250514","messages":[]}')
_check("proxy: rejects unbound machine (401)", r.status_code == 401)

# ── /ai/proxy: invalid key format ───────────────────────────────────────────
r = client.post("/api/v1/ai/proxy",
                headers={
                    "x-license-key": "garbage",
                    "x-machine-id":  "machine-A",
                    "x-feature":     "document_reader",
                    "Content-Type":  "application/json",
                },
                content=b'{}')
_check("proxy: rejects bad key format (401)", r.status_code == 401)

# ── /ai/proxy: surfaces Anthropic errors ────────────────────────────────────
with patch("license_server.main._forward_to_anthropic",
           return_value=(400, None, "bad request body")):
    r = client.post("/api/v1/ai/proxy",
                    headers={
                        "x-license-key": key,
                        "x-machine-id":  "machine-A",
                        "x-feature":     "document_reader",
                        "Content-Type":  "application/json",
                    },
                    content=b'{}')
_check("proxy: forwards Anthropic 400", r.status_code == 400)

# ── Anthropic key unset → 503 ────────────────────────────────────────────────
with patch.object(__import__("license_server.config", fromlist=["settings"]).settings,
                  "anthropic_api_key", ""):
    r = client.post("/api/v1/ai/proxy",
                    headers={
                        "x-license-key": key,
                        "x-machine-id":  "machine-A",
                        "x-feature":     "document_reader",
                        "Content-Type":  "application/json",
                    },
                    content=b'{}')
_check("proxy: 503 when server key unset", r.status_code == 503)

print()
print("All Phase 2b smoke-test cases passed.")
print(f"(throwaway DB: {tmp})")
