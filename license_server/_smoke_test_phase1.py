"""
End-to-end smoke test for Phase 1 (License: seats + deactivate).
Run as: python -m license_server._smoke_test_phase1

Uses a throwaway sqlite file in $TMP — does NOT touch the real licenses.db.
"""
import os
import sys
import tempfile

fd, tmp = tempfile.mkstemp(suffix=".db")
os.close(fd)
os.remove(tmp)
os.environ["DATABASE_URL"] = f"sqlite:///{tmp}"
os.environ["ADMIN_TOKEN"]  = "test-token"

# Import AFTER setting env so Settings picks them up.
from fastapi.testclient import TestClient  # noqa: E402
from license_server.main import app        # noqa: E402
from license_server.db import init_db      # noqa: E402

# TestClient skips the FastAPI lifespan unless used as a context manager —
# call init_db() directly so tables exist before we hit the API.
init_db()
client = TestClient(app)
H = {"Authorization": "Bearer test-token"}


def _check(label, ok):
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if not ok:
        sys.exit(1)


# 1. Mint a key with seats=2
r = client.post("/admin/keys", headers=H, json={
    "plan": "STANDARD", "customer_email": "t@x.com",
    "expires_at": "2027-01-01", "seats_allowed": 2,
})
_check("mint returns 201", r.status_code == 201)
out = r.json()
key = out["license_key"]
_check("mint set seats_allowed=2", out["seats_allowed"] == 2)
_check("mint set machine_count=0", out["machine_count"] == 0)
print(f"  key={key}")

# 2-3. Activate A and B
for mid, expected_used in (("machine-A", 1), ("machine-B", 2)):
    r = client.post("/api/v1/license/validate", json={
        "license_key": key, "machine_id": mid, "app_version": "1.0",
    })
    j = r.json()
    _check(f"validate {mid}: valid",          j.get("valid") is True)
    _check(f"validate {mid}: seats_used={expected_used}",
           j.get("seats_used") == expected_used)
    _check(f"validate {mid}: seats_allowed=2", j.get("seats_allowed") == 2)
    _check(f"validate {mid}: seats_remaining={2-expected_used}",
           j.get("seats_remaining") == 2 - expected_used)

# 4. C rejected (over cap)
r = client.post("/api/v1/license/validate", json={
    "license_key": key, "machine_id": "machine-C", "app_version": "1.0",
})
j = r.json()
_check("validate C: rejected",   j.get("valid") is False)
_check("validate C: error msg",  "seats in use" in (j.get("error") or "").lower())

# 5. A releases
r = client.post("/api/v1/license/deactivate", json={
    "license_key": key, "machine_id": "machine-A",
})
_check("deactivate A: 200",   r.status_code == 200)
_check("deactivate A: ok",    r.json().get("ok") is True)

# 6. C now succeeds
r = client.post("/api/v1/license/validate", json={
    "license_key": key, "machine_id": "machine-C", "app_version": "1.0",
})
j = r.json()
_check("validate C after release: valid",   j.get("valid") is True)
_check("validate C: seats_used=2",          j.get("seats_used") == 2)

# 7. Shrink to 1 — should evict longest-idle (B, since C just validated)
r = client.post(f"/admin/keys/{key}/seats", headers=H,
                json={"seats_allowed": 1})
j = r.json()
_check("shrink to 1: 200",            r.status_code == 200)
_check("shrink to 1: seats_allowed=1", j.get("seats_allowed") == 1)
_check("shrink to 1: machine_count=1", j.get("machine_count") == 1)

# 8. KeyOut shows seats
r = client.get(f"/admin/keys/{key}", headers=H)
_check("show key: seats_allowed=1", r.json().get("seats_allowed") == 1)

# 9. Idempotent deactivate on non-existent key
r = client.post("/api/v1/license/deactivate", json={
    "license_key": "ACCG-XXXX-XXXX-XXXX", "machine_id": "anything",
})
_check("bogus deactivate: still 200", r.status_code == 200)
_check("bogus deactivate: ok=True",   r.json().get("ok") is True)

# 10. Bad key format on validate
r = client.post("/api/v1/license/validate", json={
    "license_key": "garbage", "machine_id": "m", "app_version": "1.0",
})
j = r.json()
_check("bad key format: valid=False", j.get("valid") is False)
_check("bad key format: helpful error",
       "format" in (j.get("error") or "").lower())

print()
print("All Phase 1 server smoke-test cases passed.")
print(f"(used throwaway DB: {tmp})")
