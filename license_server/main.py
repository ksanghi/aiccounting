"""
AccGenie license server.

Endpoints:
  POST /api/v1/license/validate    public — desktop client calls this
  POST /api/v1/license/deactivate  public — desktop releases this machine's seat
  POST /api/v1/install/heartbeat   public — anonymous install heartbeat
  GET  /api/v1/credits/balance     public — current AI credit balance for a key
  POST /api/v1/ai/proxy            public — Anthropic proxy with metering
  GET  /api/v1/health              public health check

  POST /admin/keys                 admin — mint a new key
  GET  /admin/keys                 admin — list keys
  GET  /admin/keys/{key}           admin — show one key + machines + recent logs
  POST /admin/keys/{key}/revoke    admin — revoke
  POST /admin/keys/{key}/extend    admin — extend expiry
  POST /admin/keys/{key}/seats     admin — change per-license seat cap
  POST /admin/credits/{key}/topup  admin — add AI credits

Admin endpoints require header:  Authorization: Bearer <ADMIN_TOKEN>
"""
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import json
import urllib.error
import urllib.request

from license_server.config import settings
from license_server.db import init_db, get_db
from license_server.models import (
    License, MachineBinding, ValidationLog, Install,
    Credit, CreditTopup, AIUsageLog, Order,
)
from license_server.plans import (
    PLANS, PLAN_LIMITS, PLAN_USER_LIMITS, PLAN_FEATURES, PLAN_SEATS,
)
from license_server.keys import is_valid_format
from license_server.services import razorpay_client, email_service
from license_server.services.license_mint import (
    mint_license, default_expiry_for_plan, MintError,
)
from license_server.services.pricing_lookup import resolve_price, PricingError


# ── App lifecycle ─────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AccGenie License Server",
    version=settings.server_version,
    lifespan=lifespan,
)


# ── Schemas ───────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    license_key: str
    machine_id:  str
    app_version: str = ""


class ValidateResponse(BaseModel):
    valid:           bool
    plan:            Optional[str]  = None
    features:        Optional[list] = None
    txn_limit:       Optional[int]  = None
    txn_used:        Optional[int]  = None
    user_limit:      Optional[int]  = None
    seats_allowed:   Optional[int]  = None
    seats_used:      Optional[int]  = None
    seats_remaining: Optional[int]  = None
    expires_at:      Optional[str]  = None
    company_name:    Optional[str]  = None
    error:           Optional[str]  = None


class MintRequest(BaseModel):
    plan:           str = Field(..., pattern="^(FREE|STANDARD|PRO|PREMIUM)$")
    customer_email: str = ""
    company_name:   str = ""
    expires_at:     date
    notes:          str = ""
    txn_limit:      Optional[int] = None  # override plan default
    user_limit:     Optional[int] = None  # override plan default
    seats_allowed:  Optional[int] = None  # override plan default


class KeyOut(BaseModel):
    license_key:    str
    plan:           str
    customer_email: str
    company_name:   str
    expires_at:     date
    txn_limit:      int
    user_limit:     int
    seats_allowed:  int
    revoked:        bool
    notes:          str
    created_at:     datetime
    machine_count:  int

    model_config = {"from_attributes": True}


class DeactivateRequest(BaseModel):
    license_key: str
    machine_id:  str


class DeactivateResponse(BaseModel):
    ok:    bool
    error: Optional[str] = None


class SeatsRequest(BaseModel):
    seats_allowed: int = Field(..., ge=1)


# ── AI proxy + credits (Phase 2b) ────────────────────────────────────────────

class BalanceResponse(BaseModel):
    ok:            bool
    balance_paise: int               = 0
    license_key:   str               = ""
    error:         Optional[str]     = None


class TopupRequest(BaseModel):
    amount_paise: int     = Field(..., gt=0)
    ref:          str     = ""
    source:       str     = "admin"


class TopupResponse(BaseModel):
    ok:            bool
    balance_paise: int             = 0
    topup_id:      Optional[int]   = None
    error:         Optional[str]   = None


class ExtendRequest(BaseModel):
    new_expires_at: date


class HeartbeatRequest(BaseModel):
    install_id:  str
    machine_id:  str
    app_version: str = ""
    plan:        str = "FREE"
    license_key: str = ""
    os_name:     str = ""


class HeartbeatResponse(BaseModel):
    ok: bool


# ── Checkout / Razorpay schemas ──────────────────────────────────────────────

class CheckoutCreateRequest(BaseModel):
    plan:           str    = Field(..., min_length=2, max_length=16)
    country_code:   str    = Field(default="IN", min_length=2, max_length=4)
    customer_email: str    = Field(..., min_length=3, max_length=256)
    customer_name:  str    = Field(default="", max_length=256)
    customer_phone: str    = Field(default="", max_length=32)
    company_name:   str    = Field(default="", max_length=256)


class CheckoutCreateResponse(BaseModel):
    ok:               bool
    order_id:         Optional[str] = None  # razorpay_order_id
    amount_paise:     Optional[int] = None
    amount_display:   Optional[str] = None  # "Rs. 4,999.00" for UI
    currency:         Optional[str] = None
    razorpay_key_id:  Optional[str] = None  # public; safe to expose to frontend
    plan:             Optional[str] = None
    plan_name:        Optional[str] = None
    error:            Optional[str] = None


class InstallStats(BaseModel):
    total_installs: int
    by_plan:        dict[str, int]
    new_last_7d:    int
    new_last_30d:   int
    active_last_7d: int


# ── Helpers ───────────────────────────────────────────────────────────────

def require_admin(authorization: str = Header(default="")) -> None:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if token != settings.admin_token:
        raise HTTPException(status_code=403, detail="Bad admin token")


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _log_validation(
    db: Session, license_id: int | None, license_key: str,
    machine_id: str, app_version: str, ip: str,
    success: bool, error: str = "",
) -> None:
    db.add(ValidationLog(
        license_id=license_id,
        license_key=license_key,
        machine_id=machine_id,
        app_version=app_version,
        ip=ip,
        success=success,
        error=error,
    ))


# ── Public endpoints ──────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8>"
        "<title>AccGenie License Server</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:560px;"
        "margin:80px auto;padding:0 20px;color:#222;line-height:1.5}"
        "a{color:#0a66c2}</style>"
        "<h1>AccGenie License Server</h1>"
        "<p>This is the API endpoint for the AccGenie desktop app. "
        "It has no browsable home page.</p>"
        "<ul>"
        "<li><a href=\"/api/v1/health\">/api/v1/health</a> — health check</li>"
        "<li><a href=\"/docs\">/docs</a> — interactive API documentation</li>"
        "</ul>"
        "<p style=\"color:#666;font-size:13px\">"
        "Need a license key? Visit "
        "<a href=\"https://accgenie.in\">accgenie.in</a>.</p>"
    )


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "version": settings.server_version}


@app.post("/api/v1/install/heartbeat", response_model=HeartbeatResponse)
def install_heartbeat(body: HeartbeatRequest, db: Session = Depends(get_db)):
    """
    Anonymous install heartbeat. Upsert by install_id. Updates plan/version
    on each call so we see migrations from FREE -> paid in place.
    """
    install_id = (body.install_id or "").strip()
    machine_id = (body.machine_id or "").strip()
    if not install_id or not machine_id:
        # Silent no-op for malformed clients.
        return HeartbeatResponse(ok=False)

    row = db.scalar(select(Install).where(Install.install_id == install_id))
    if row is None:
        db.add(Install(
            install_id=install_id,
            machine_id=machine_id,
            app_version=body.app_version,
            plan=body.plan,
            license_key=body.license_key,
            os_name=body.os_name,
        ))
    else:
        row.machine_id      = machine_id
        row.app_version     = body.app_version
        row.plan            = body.plan
        row.license_key     = body.license_key
        row.os_name         = body.os_name
        row.last_seen_at    = datetime.utcnow()
        row.heartbeat_count = (row.heartbeat_count or 0) + 1
    db.commit()
    return HeartbeatResponse(ok=True)


@app.get("/admin/installs/stats", response_model=InstallStats,
         dependencies=[Depends(require_admin)])
def install_stats(db: Session = Depends(get_db)):
    from datetime import timedelta
    now = datetime.utcnow()
    cutoff_7  = now - timedelta(days=7)
    cutoff_30 = now - timedelta(days=30)

    total = db.scalar(select(func.count()).select_from(Install)) or 0

    by_plan_rows = db.execute(
        select(Install.plan, func.count()).group_by(Install.plan)
    ).all()
    by_plan = {plan: count for plan, count in by_plan_rows}

    new_7  = db.scalar(
        select(func.count()).select_from(Install)
        .where(Install.first_seen_at >= cutoff_7)
    ) or 0
    new_30 = db.scalar(
        select(func.count()).select_from(Install)
        .where(Install.first_seen_at >= cutoff_30)
    ) or 0
    active_7 = db.scalar(
        select(func.count()).select_from(Install)
        .where(Install.last_seen_at >= cutoff_7)
    ) or 0

    return InstallStats(
        total_installs=total,
        by_plan=by_plan,
        new_last_7d=new_7,
        new_last_30d=new_30,
        active_last_7d=active_7,
    )


@app.post("/api/v1/license/validate", response_model=ValidateResponse)
def validate(
    body: ValidateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    key = (body.license_key or "").strip().upper()
    machine_id = (body.machine_id or "").strip()

    def _fail(error: str, license_id: int | None = None) -> ValidateResponse:
        _log_validation(
            db, license_id, key, machine_id, body.app_version, ip,
            success=False, error=error,
        )
        db.commit()
        return ValidateResponse(valid=False, error=error)

    if not is_valid_format(key):
        return _fail("Invalid key format. Expected ACCG-XXXX-XXXX-XXXX.")
    if not machine_id:
        return _fail("Missing machine_id.")

    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return _fail("License key not found.")
    if lic.revoked:
        return _fail("License has been revoked.", license_id=lic.id)
    if lic.expires_at < date.today():
        return _fail("License has expired.", license_id=lic.id)

    # Machine binding: bind on first seen, reject if over per-license seat cap.
    # seats_allowed is per-License (replaces the old global config knob).
    seats_cap = lic.seats_allowed or settings.max_machines_per_key
    binding = db.scalar(
        select(MachineBinding).where(
            MachineBinding.license_id == lic.id,
            MachineBinding.machine_id == machine_id,
        )
    )
    if binding is None:
        existing = db.scalar(
            select(func.count()).select_from(MachineBinding)
            .where(MachineBinding.license_id == lic.id)
        ) or 0
        if existing >= seats_cap:
            return _fail(
                f"This license has {existing} of {seats_cap} machine seats in use. "
                f"Release a seat from another machine, or contact support.",
                license_id=lic.id,
            )
        db.add(MachineBinding(license_id=lic.id, machine_id=machine_id))
    else:
        binding.last_seen_at = datetime.utcnow()

    _log_validation(
        db, lic.id, key, machine_id, body.app_version, ip,
        success=True,
    )
    db.commit()

    seats_used = db.scalar(
        select(func.count()).select_from(MachineBinding)
        .where(MachineBinding.license_id == lic.id)
    ) or 0

    return ValidateResponse(
        valid=True,
        plan=lic.plan,
        features=PLAN_FEATURES.get(lic.plan, []),
        txn_limit=lic.txn_limit,
        txn_used=0,  # v1: not tracked server-side; client tracks locally
        user_limit=lic.user_limit,
        seats_allowed=seats_cap,
        seats_used=seats_used,
        seats_remaining=max(0, seats_cap - seats_used),
        expires_at=lic.expires_at.isoformat(),
        company_name=lic.company_name,
    )


@app.post("/api/v1/license/deactivate", response_model=DeactivateResponse)
def deactivate(
    body: DeactivateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Release this machine's seat from a license. Public endpoint — the device
    proves ownership by knowing its own machine_id (which the server hashed
    from hostname+arch on first activation; no other device has it).

    Use cases:
      - User clicks 'Release this machine's seat' before reinstalling.
      - User is migrating to a new PC and wants to free up a seat.

    Idempotent: if the binding doesn't exist, returns ok=True silently.
    """
    ip = _client_ip(request)
    key = (body.license_key or "").strip().upper()
    machine_id = (body.machine_id or "").strip()

    if not is_valid_format(key):
        return DeactivateResponse(ok=False, error="Invalid key format.")
    if not machine_id:
        return DeactivateResponse(ok=False, error="Missing machine_id.")

    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        # Don't leak existence — succeed silently.
        return DeactivateResponse(ok=True)

    binding = db.scalar(
        select(MachineBinding).where(
            MachineBinding.license_id == lic.id,
            MachineBinding.machine_id == machine_id,
        )
    )
    if binding is not None:
        db.delete(binding)
        _log_validation(
            db, lic.id, key, machine_id, "", ip,
            success=True, error="seat_released",
        )
        db.commit()
    return DeactivateResponse(ok=True)


# ── Admin endpoints ───────────────────────────────────────────────────────

def _to_keyout(lic: License, db: Session) -> KeyOut:
    machine_count = db.scalar(
        select(func.count()).select_from(MachineBinding)
        .where(MachineBinding.license_id == lic.id)
    ) or 0
    return KeyOut(
        license_key=lic.license_key,
        plan=lic.plan,
        customer_email=lic.customer_email,
        company_name=lic.company_name,
        expires_at=lic.expires_at,
        txn_limit=lic.txn_limit,
        user_limit=lic.user_limit,
        seats_allowed=lic.seats_allowed or settings.max_machines_per_key,
        revoked=lic.revoked,
        notes=lic.notes,
        created_at=lic.created_at,
        machine_count=machine_count,
    )


@app.post("/admin/keys", response_model=KeyOut, status_code=201,
          dependencies=[Depends(require_admin)])
def mint_key(body: MintRequest, db: Session = Depends(get_db)):
    from license_server.keys import generate_key

    if body.plan not in PLANS:
        raise HTTPException(400, f"Unknown plan: {body.plan}")

    # Generate, retry on (extremely unlikely) collision.
    for _ in range(10):
        key = generate_key()
        if not db.scalar(select(License).where(License.license_key == key)):
            break
    else:
        raise HTTPException(500, "Could not generate unique key")

    lic = License(
        license_key=key,
        plan=body.plan,
        customer_email=body.customer_email,
        company_name=body.company_name,
        expires_at=body.expires_at,
        txn_limit=body.txn_limit or PLAN_LIMITS[body.plan],
        user_limit=body.user_limit or PLAN_USER_LIMITS[body.plan],
        seats_allowed=body.seats_allowed or PLAN_SEATS.get(
            body.plan, settings.max_machines_per_key
        ),
        notes=body.notes,
    )
    db.add(lic)
    db.commit()
    db.refresh(lic)
    return _to_keyout(lic, db)


@app.get("/admin/keys", response_model=list[KeyOut],
         dependencies=[Depends(require_admin)])
def list_keys(
    plan: Optional[str] = None,
    revoked: Optional[bool] = None,
    db: Session = Depends(get_db),
):
    stmt = select(License).order_by(License.created_at.desc())
    if plan:
        stmt = stmt.where(License.plan == plan)
    if revoked is not None:
        stmt = stmt.where(License.revoked == revoked)
    return [_to_keyout(lic, db) for lic in db.scalars(stmt)]


@app.get("/admin/keys/{key}", response_model=KeyOut,
         dependencies=[Depends(require_admin)])
def show_key(key: str, db: Session = Depends(get_db)):
    lic = db.scalar(select(License).where(License.license_key == key.upper()))
    if not lic:
        raise HTTPException(404, "Not found")
    return _to_keyout(lic, db)


@app.post("/admin/keys/{key}/revoke", response_model=KeyOut,
          dependencies=[Depends(require_admin)])
def revoke_key(key: str, db: Session = Depends(get_db)):
    lic = db.scalar(select(License).where(License.license_key == key.upper()))
    if not lic:
        raise HTTPException(404, "Not found")
    lic.revoked = True
    db.commit()
    db.refresh(lic)
    return _to_keyout(lic, db)


@app.post("/admin/keys/{key}/extend", response_model=KeyOut,
          dependencies=[Depends(require_admin)])
def extend_key(key: str, body: ExtendRequest, db: Session = Depends(get_db)):
    lic = db.scalar(select(License).where(License.license_key == key.upper()))
    if not lic:
        raise HTTPException(404, "Not found")
    if body.new_expires_at < date.today():
        raise HTTPException(400, "New expiry is in the past")
    lic.expires_at = body.new_expires_at
    db.commit()
    db.refresh(lic)
    return _to_keyout(lic, db)


@app.post("/admin/keys/{key}/seats", response_model=KeyOut,
          dependencies=[Depends(require_admin)])
def set_seats(key: str, body: SeatsRequest, db: Session = Depends(get_db)):
    """
    Change a license's seat count. If we shrink below the number of active
    bindings, evict the longest-idle bindings (oldest last_seen_at first)
    until we fit. The customer's most recently used machines are preserved.
    """
    lic = db.scalar(select(License).where(License.license_key == key.upper()))
    if not lic:
        raise HTTPException(404, "Not found")
    lic.seats_allowed = body.seats_allowed

    bindings = list(db.scalars(
        select(MachineBinding)
        .where(MachineBinding.license_id == lic.id)
        .order_by(MachineBinding.last_seen_at.desc())
    ))
    for excess in bindings[body.seats_allowed:]:
        db.delete(excess)
    db.commit()
    db.refresh(lic)
    return _to_keyout(lic, db)


# ── AI proxy + credits (Phase 2b) ────────────────────────────────────────────

def _get_or_create_credit_row(db: Session, license_id: int) -> Credit:
    """Lazy-create a Credit row for a license. New customers start at 0."""
    row = db.scalar(select(Credit).where(Credit.license_id == license_id))
    if row is None:
        row = Credit(license_id=license_id, balance_paise=0)
        db.add(row)
        db.flush()
    return row


def _calc_paise(tokens_in: int, tokens_out: int) -> int:
    """Convert Anthropic usage to paise per server-config rates."""
    cost_in  = tokens_in  * settings.ai_input_paise_per_1k  / 1000.0
    cost_out = tokens_out * settings.ai_output_paise_per_1k / 1000.0
    # Round up so we never under-charge.
    import math
    return max(1, math.ceil(cost_in + cost_out))


@app.get("/api/v1/credits/balance", response_model=BalanceResponse)
def credits_balance(
    license_key: str,
    machine_id: str = "",
    db: Session = Depends(get_db),
):
    """Read-only balance check. Public — client polls this to display
    current paise balance on the License page / AI screens."""
    key = (license_key or "").strip().upper()
    if not is_valid_format(key):
        return BalanceResponse(ok=False, error="Invalid key format.")
    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return BalanceResponse(ok=False, error="License key not found.")
    if lic.revoked or lic.expires_at < date.today():
        return BalanceResponse(ok=False, error="License is revoked or expired.")
    row = _get_or_create_credit_row(db, lic.id)
    db.commit()
    return BalanceResponse(
        ok=True,
        balance_paise=row.balance_paise,
        license_key=key,
    )


@app.post("/admin/credits/{key}/topup", response_model=TopupResponse,
          dependencies=[Depends(require_admin)])
def credit_topup(key: str, body: TopupRequest, db: Session = Depends(get_db)):
    """Admin grant / payment webhook credit add. Source can be 'admin',
    'razorpay', 'demo' etc. — the audit row records it."""
    lic = db.scalar(select(License).where(License.license_key == key.upper()))
    if not lic:
        raise HTTPException(404, "Not found")
    row = _get_or_create_credit_row(db, lic.id)
    row.balance_paise += body.amount_paise
    row.updated_at = datetime.utcnow()
    topup = CreditTopup(
        license_id=lic.id,
        amount_paise=body.amount_paise,
        ref=body.ref,
        source=body.source or "admin",
    )
    db.add(topup)
    db.commit()
    db.refresh(row)
    db.refresh(topup)
    return TopupResponse(
        ok=True, balance_paise=row.balance_paise, topup_id=topup.id,
    )


def _forward_to_anthropic(body: bytes) -> tuple[int, dict | None, str]:
    """
    Blocking forward to Anthropic. Returns (status_code, json_or_None, error_text).
    Run inside `asyncio.to_thread` from the async route so we don't block
    the event loop while waiting up to 120 s for the model.
    """
    req = urllib.request.Request(
        settings.anthropic_url,
        data=body,
        headers={
            "Content-Type":      "application/json",
            "x-api-key":         settings.anthropic_api_key,
            "anthropic-version": settings.anthropic_version,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return resp.status, json.loads(resp.read()), ""
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        return e.code, None, err_body
    except urllib.error.URLError as e:
        return 502, None, f"network: {e.reason}"


@app.post("/api/v1/ai/proxy")
async def ai_proxy(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Authenticated proxy to Anthropic /v1/messages. Validates the caller's
    license + machine binding, checks balance, forwards the request with
    OUR Anthropic key, meters the response by tokens, deducts paise, and
    logs the call to ai_usage_logs.

    Headers from client:
      x-license-key  : ACCG-XXXX-XXXX-XXXX
      x-machine-id   : machine fingerprint (must already be bound)
      x-feature      : 'document_reader' / 'bank_reconciliation' / 'verbal_entry'

    Body: Anthropic-shaped messages request (model, max_tokens, messages …).
    """
    import asyncio

    if not settings.anthropic_api_key:
        raise HTTPException(503, "AI proxy is not configured on this server.")

    key        = (request.headers.get("x-license-key") or "").strip().upper()
    machine_id = (request.headers.get("x-machine-id")  or "").strip()
    feature    = (request.headers.get("x-feature")     or "unknown").strip()

    if not is_valid_format(key):
        raise HTTPException(401, "Invalid license key format.")
    if not machine_id:
        raise HTTPException(401, "Missing machine_id.")

    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None or lic.revoked or lic.expires_at < date.today():
        raise HTTPException(401, "License not valid.")

    # Must be a currently-bound machine — prevents stolen-key abuse.
    binding = db.scalar(
        select(MachineBinding).where(
            MachineBinding.license_id == lic.id,
            MachineBinding.machine_id == machine_id,
        )
    )
    if binding is None:
        raise HTTPException(401, "Machine not bound to this license.")

    # Balance gate
    credit = _get_or_create_credit_row(db, lic.id)
    if credit.balance_paise < settings.ai_min_balance_paise:
        raise HTTPException(402, (
            f"Low credit balance ({credit.balance_paise / 100:.2f} INR). "
            f"Top up to continue."
        ))

    raw_body = await request.body()

    status_code, resp_json, err_text = await asyncio.to_thread(
        _forward_to_anthropic, raw_body,
    )

    if resp_json is None:
        db.add(AIUsageLog(
            license_id=lic.id, machine_id=machine_id, feature=feature,
            tokens_in=0, tokens_out=0, paise_charged=0,
            success=False, error=f"upstream {status_code}: {err_text[:200]}",
        ))
        db.commit()
        # Never relay Anthropic's raw status code. Any failure forwarding to
        # Anthropic — bad model name, rate limit, network, 4xx, 5xx — is an
        # *upstream* error from the client's point of view, so it always
        # comes back as 502. Relaying a raw 404 here previously made the
        # desktop client think the /ai/proxy route itself was missing.
        # The original upstream status is preserved in the detail for logs.
        raise HTTPException(
            502,
            f"AI upstream error (Anthropic returned {status_code}): "
            f"{err_text[:300]}",
        )

    # Meter the response
    usage = resp_json.get("usage", {}) or {}
    tokens_in  = int(usage.get("input_tokens", 0))
    tokens_out = int(usage.get("output_tokens", 0))
    paise = _calc_paise(tokens_in, tokens_out)
    model = resp_json.get("model", "") or ""

    credit.balance_paise = max(0, credit.balance_paise - paise)
    credit.updated_at = datetime.utcnow()
    db.add(AIUsageLog(
        license_id=lic.id, machine_id=machine_id, feature=feature,
        model=model, tokens_in=tokens_in, tokens_out=tokens_out,
        paise_charged=paise, success=True,
    ))
    db.commit()

    # Surface the new balance via response headers so the client can
    # refresh its cached display without a separate /balance call.
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content=resp_json,
        headers={
            "x-accgenie-paise-charged": str(paise),
            "x-accgenie-balance-paise": str(credit.balance_paise),
        },
    )


# ── Checkout (Razorpay) ──────────────────────────────────────────────────────

@app.post("/api/v1/checkout/create-order", response_model=CheckoutCreateResponse)
def checkout_create_order(
    body: CheckoutCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Create a Razorpay order for a plan purchase. The caller is the
    marketing/checkout site (CORS-safe — no auth headers; price is
    looked up server-side).

    Flow:
      1. Resolve price from baked pricing.xlsx for (plan, country_code).
      2. Create a Razorpay order via the SDK.
      3. Persist an Order row (status='created').
      4. Return { order_id, amount, currency, razorpay_key_id } so the
         frontend can hand them to Razorpay Checkout JS.

    The actual fulfillment (mint license + email key) happens later in
    /webhooks/razorpay when Razorpay confirms the payment.
    """
    if not razorpay_client.is_enabled():
        raise HTTPException(503, "Payments are not configured on this server.")

    plan = (body.plan or "").upper()
    country = (body.country_code or "IN").upper()
    email = (body.customer_email or "").strip()
    if not email or "@" not in email:
        return CheckoutCreateResponse(ok=False, error="Valid email required")

    try:
        price = resolve_price(plan, country)
    except PricingError as e:
        return CheckoutCreateResponse(ok=False, error=str(e))

    # Create the Razorpay order. The 'notes' field gets stored alongside
    # the order and echoed back in the webhook payload — useful for
    # cross-checking which Order row to update.
    try:
        rp_order = razorpay_client.create_order(
            amount_paise=price["amount_paise"],
            currency=price["currency"],
            receipt_id=f"accg-{plan[:4]}-{int(datetime.utcnow().timestamp())}",
            notes={
                "plan":           price["plan_code"],
                "country_code":   price["country_code"],
                "customer_email": email,
                "customer_name":  body.customer_name or "",
                "company_name":   body.company_name or "",
            },
        )
    except razorpay_client.RazorpayError as e:
        return CheckoutCreateResponse(ok=False, error=f"Razorpay: {e}")

    # Persist the order so the webhook can find it.
    order = Order(
        razorpay_order_id=rp_order["id"],
        plan=price["plan_code"],
        amount_paise=price["amount_paise"],
        currency=price["currency"],
        country_code=price["country_code"],
        customer_email=email,
        customer_name=body.customer_name or "",
        customer_phone=body.customer_phone or "",
        company_name=body.company_name or "",
        status="created",
        notes=f"[create] receipt={rp_order.get('receipt','')}",
    )
    db.add(order)
    db.commit()

    return CheckoutCreateResponse(
        ok=True,
        order_id=rp_order["id"],
        amount_paise=price["amount_paise"],
        amount_display=price["amount_display"],
        currency=price["currency"],
        razorpay_key_id=settings.razorpay_key_id,
        plan=price["plan_code"],
        plan_name=price["plan_name"],
    )


@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Razorpay webhook receiver. Razorpay calls this after a payment is
    captured (or failed). We verify the HMAC-SHA256 signature against
    RAZORPAY_WEBHOOK_SECRET, then act on the event.

    On `payment.captured`:
      - Look up the Order row by razorpay_order_id.
      - If status is already 'paid', return 200 (idempotent — Razorpay
        retries delivery on 5xx).
      - Mint a License row via license_mint.mint_license().
      - Update the Order: status='paid', license_id=..., notes appended.
      - Email the key to the customer (best-effort; failure does NOT
        roll back the mint).

    Returns 200 on success OR on duplicate delivery, so Razorpay stops
    retrying. Returns 4xx only when the signature is bad or the body
    is malformed.
    """
    if not razorpay_client.webhook_enabled():
        raise HTTPException(503, "Webhook secret not configured.")

    raw_body  = await request.body()
    signature = request.headers.get("x-razorpay-signature", "")
    if not razorpay_client.verify_webhook_signature(raw_body, signature):
        raise HTTPException(401, "Bad signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "Malformed JSON")

    event = payload.get("event") or ""
    if event not in ("payment.captured", "payment.failed", "order.paid"):
        # Acknowledge but ignore — refunds/disputes/etc. will be handled
        # via admin endpoints for now.
        return {"ok": True, "ignored": event}

    # Both "payment.captured" and "order.paid" reach us when a successful
    # payment lands. Razorpay sends both; we treat them the same and rely
    # on the order.status guard for idempotency.
    payment   = (payload.get("payload") or {}).get("payment", {})
    pay_entity= (payment.get("entity") or {})
    rp_order_id   = pay_entity.get("order_id") or ""
    rp_payment_id = pay_entity.get("id") or ""

    if not rp_order_id:
        # Could be order.paid event without payment.entity — fall back
        # to the order payload.
        order_entity = ((payload.get("payload") or {}).get("order") or {}).get("entity", {})
        rp_order_id = rp_order_id or order_entity.get("id") or ""

    if not rp_order_id:
        raise HTTPException(400, "Event missing order_id")

    order = db.scalar(select(Order).where(Order.razorpay_order_id == rp_order_id))
    if order is None:
        # Order we didn't create — log and 200 so Razorpay stops retrying.
        return {"ok": True, "warning": f"Unknown order_id {rp_order_id}"}

    if event == "payment.failed":
        order.status = "failed"
        order.notes  = (order.notes or "") + f"\n[failed] {rp_payment_id}"
        db.commit()
        return {"ok": True, "status": "failed"}

    # Success path. Idempotency: if already paid, just acknowledge.
    if order.status == "paid" and order.license_id:
        return {"ok": True, "status": "already_paid",
                "license_id": order.license_id}

    # Mint the license.
    try:
        lic = mint_license(
            db=db,
            plan=order.plan,
            customer_email=order.customer_email,
            company_name=order.company_name,
            expires_at=default_expiry_for_plan(order.plan),
            notes=f"razorpay order {order.razorpay_order_id} "
                  f"payment {rp_payment_id}",
        )
    except MintError as e:
        # Mint failure is rare (DB or plan-name issue). Surface as 500
        # so Razorpay retries — gives ops a chance to fix and replay.
        raise HTTPException(500, f"Mint failed: {e}")

    order.status              = "paid"
    order.razorpay_payment_id = rp_payment_id
    order.license_id          = lic.id
    order.notes               = (order.notes or "") + (
        f"\n[paid] license={lic.license_key} payment={rp_payment_id}"
    )
    db.commit()

    # Email the key. Best-effort — never let SMTP failures roll back the
    # mint. The order row records the email address; ops can resend
    # manually if needed.
    try:
        email_service.send_license_email(
            to_email=order.customer_email,
            license_key=lic.license_key,
            plan=lic.plan,
            expires_at=lic.expires_at.isoformat(),
            customer_name=order.customer_name,
            amount_paid_str=f"{order.currency} {order.amount_paise/100:,.2f}",
        )
    except Exception:
        # Already logged inside email_service; swallow here.
        pass

    return {"ok": True, "status": "paid", "license_id": lic.id}
