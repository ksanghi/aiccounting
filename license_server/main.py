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
  POST /admin/credits/{key}/topup  admin — add wallet/credit balance (paise)

Admin endpoints require header:  Authorization: Bearer <ADMIN_TOKEN>
"""
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, Header, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

import asyncio
import html as _html
import json
import re
import time
import urllib.error
import urllib.request

from license_server.config import settings
from license_server.db import init_db, get_db
from license_server.models import (
    License, MachineBinding, ValidationLog, Install,
    Credit, CreditTopup, AIUsageLog, Order,
    SMSWallet, SMSWalletTxn, ChatLearned,
)

# Baked support-bot knowledge base (build/bake_kb.py → license_server/_kb.py).
try:
    from license_server._kb import KB_TEXT
except Exception:
    KB_TEXT = ""
from license_server.plans import (
    PLANS, PLAN_LIMITS, PLAN_USER_LIMITS, PLAN_FEATURES, PLAN_SEATS,
    features_for, flats_limit_for, VALID_PRODUCTS,
)
from license_server.keys import is_valid_format
from license_server.services import razorpay_client, email_service
from license_server.services.license_mint import (
    mint_license, default_expiry_for_plan, expiry_for, MintError,
)
from license_server.services.pricing_lookup import (
    resolve_price, compute_upgrade, tier_rank, PricingError,
)


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

# Marketing pages (Accounts HQ landing, RWA HQ SPA, downloads) live at
# https://apps.ai-consultants.in/ . The API + webhooks stay at
# https://license.ai-consultants.in/ — so checkout.html and any other
# marketing page that POSTs to /api/v1/* hits CORS preflight. Permit the
# marketing origin (and the legacy same-origin license.* so cached pages
# keep working), plus localhost for dev. Desktop clients don't send an
# Origin header, so this doesn't affect them.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://apps.ai-consultants.in",
        "https://aic.ai-consultants.in",
        "https://license.ai-consultants.in",
        "http://localhost:8000",
        "http://localhost:5173",
    ],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    max_age=600,
)


# ── Schemas ───────────────────────────────────────────────────────────────

class ValidateRequest(BaseModel):
    license_key: str
    machine_id:  str
    # The asking app's product, e.g. 'rwagenie'. When present, a license
    # whose product differs is rejected (each product's license only works
    # in its own app). Optional for back-compat with older builds.
    product:     Optional[str] = None
    app_version: str = ""


class ValidateResponse(BaseModel):
    valid:           bool
    plan:            Optional[str]  = None
    product:         Optional[str]  = None   # 'accgenie' / 'rwagenie' / 'tradehq'
    features:        Optional[list] = None   # merged AG + RWA when product=rwagenie, THQ only for tradehq
    txn_limit:       Optional[int]  = None
    txn_used:        Optional[int]  = None
    user_limit:      Optional[int]  = None
    seats_allowed:   Optional[int]  = None
    seats_used:      Optional[int]  = None
    seats_remaining: Optional[int]  = None
    flats_limit:     Optional[int]  = None   # RWAGenie only; None = unlimited or not RWA
    expires_at:      Optional[str]  = None
    company_name:    Optional[str]  = None
    country_code:    Optional[str]  = None   # ISO-2; selects the active CountryProfile
    error:           Optional[str]  = None


class MintRequest(BaseModel):
    plan:           str = Field(..., pattern="^(FREE|STANDARD|PRO|PREMIUM)$")
    # Default for back-compat with any existing minting scripts that don't
    # pass product. New AG mints can omit; RWAGenie mints must set
    # product='rwagenie' explicitly.
    product:        str = Field(default="accgenie",
                                pattern="^(accgenie|rwagenie|tradehq)$")
    customer_email: str = ""
    company_name:   str = ""
    expires_at:     date
    notes:          str = ""
    txn_limit:      Optional[int] = None  # override plan default
    user_limit:     Optional[int] = None  # override plan default
    seats_allowed:  Optional[int] = None  # override plan default


class KeyOut(BaseModel):
    license_key:    str
    product:        str = "accgenie"
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
    product:        str    = Field(default="accgenie",
                                   pattern="^(accgenie|rwagenie|tradehq)$")
    billing_period: str    = Field(default="annual", pattern="^(annual|monthly)$")
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
    product:          Optional[str] = None  # 'accgenie' or 'rwagenie'
    error:            Optional[str] = None
    # Free-tier branch (no Razorpay round-trip): server has already minted
    # + emailed the key by the time this response is sent.
    free:             bool = False
    license_key:      Optional[str] = None


class InstallStats(BaseModel):
    total_installs: int
    by_plan:        dict[str, int]
    new_last_7d:    int
    new_last_30d:   int
    active_last_7d: int


# ── SMS Wallet schemas ──────────────────────────────────────────────────────

class WalletBalanceResponse(BaseModel):
    ok:            bool
    balance_paise: Optional[int] = None
    license_key:   Optional[str] = None
    error:         Optional[str] = None


class WalletDebitRequest(BaseModel):
    license_key:     str    = Field(..., min_length=8, max_length=32)
    machine_id:      str    = Field(default="", max_length=64)
    amount_paise:    int    = Field(..., ge=1, le=10_000_000)
    kind:            str    = Field(default="sms_broadcast",
                                    pattern="^(sms_otp|sms_broadcast|visitor_pass_wa|visitor_pass_sms|decision_wa)$")
    recipient_phone: str    = Field(default="", max_length=32)
    ref:             str    = Field(default="", max_length=128)


class WalletDebitResponse(BaseModel):
    ok:                  bool
    balance_after_paise: Optional[int] = None
    txn_id:              Optional[int] = None
    error:               Optional[str] = None     # 'insufficient_balance', 'invalid_key', etc.


class WalletTopupCreateRequest(BaseModel):
    license_key:    str = Field(..., min_length=8, max_length=32)
    amount_paise:   int = Field(..., ge=100, le=10_000_000)  # ₹1 to ₹1L per top-up
    customer_email: str = Field(default="", max_length=256)
    customer_name:  str = Field(default="", max_length=256)


class WalletTopupCreateResponse(BaseModel):
    ok:               bool
    order_id:         Optional[str] = None
    amount_paise:     Optional[int] = None
    currency:         Optional[str] = "INR"
    razorpay_key_id:  Optional[str] = None
    error:            Optional[str] = None


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


def _mask_key(key: str) -> str:
    """Show first 4 + last 4 chars; redact the middle. So a leaked
    alert email doesn't hand a working key to whoever sees it."""
    k = (key or "").strip()
    if len(k) <= 8:
        return "****"
    return f"{k[:4]}…{k[-4:]}"


def _maybe_alert_seat_release_abuse(
    db: Session, lic: "License", key: str,
    prior_machine: str, prior_time: datetime,
    new_machine: str, new_ip: str,
) -> None:
    """Send an ops email when a key trips the seat-release cooldown.
    Debounced: only one alert per key per 24h so a desktop client
    looping on deactivate-then-retry doesn't pile up inbox noise.
    Best-effort — never raises; missing SMTP or alert email just no-ops.
    """
    from datetime import timedelta as _td
    to = (settings.ops_alert_email or "").strip()
    if not to:
        return

    # Debounce: have we already alerted for THIS key in the last 24h?
    cutoff = datetime.utcnow() - _td(hours=24)
    prior_alert = db.scalar(
        select(ValidationLog).where(
            ValidationLog.license_id == lic.id,
            ValidationLog.error      == "seat_release_alert_sent",
            ValidationLog.created_at >= cutoff,
        ).limit(1)
    )
    if prior_alert is not None:
        return

    subject = f"[AccGenie] Seat-release cooldown tripped — {_mask_key(key)}"
    body = (
        "A licence key tripped the 24-hour seat-release cooldown — i.e.\n"
        "the desktop client tried to release ONE machine and then\n"
        "ROTATE the seat to a DIFFERENT machine within 24 hours. This\n"
        "is the abuse pattern the cooldown is designed to block.\n\n"
        f"  Key (masked):     {_mask_key(key)}\n"
        f"  Licence id:       {lic.id}\n"
        f"  Plan:             {getattr(lic, 'plan', '?')}\n"
        f"  Email on file:    {getattr(lic, 'email', '') or '(none)'}\n"
        f"  Prior release:    machine {prior_machine} at "
        f"{prior_time.isoformat() if prior_time else '(unknown)'} UTC\n"
        f"  New attempt:      machine {new_machine} from IP {new_ip}\n"
        f"  Server time:      {datetime.utcnow().isoformat()} UTC\n\n"
        "The deactivate request was blocked; the customer was told to\n"
        "wait or contact support. If this looks like an honest mistake\n"
        "(lost laptop, etc.), use the admin endpoint to release the\n"
        "stale binding manually:\n\n"
        "  POST /admin/keys/{key}/seats   (or DELETE on the binding)\n"
    )
    try:
        sent = email_service.send_email(to_email=to, subject=subject,
                                        body_text=body)
        if sent:
            # Stamp the debounce marker so a repeat trip in <24h is silent.
            _log_validation(
                db, lic.id, key, new_machine, "", new_ip,
                success=False, error="seat_release_alert_sent",
            )
            db.commit()
    except Exception:
        # Swallow — alerts are best-effort. Log via the email_service's
        # own logger; we don't want a flaky SMTP server to error the
        # cooldown response path.
        pass


# ── Public endpoints ──────────────────────────────────────────────────────

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
        return _fail("Invalid key format. Expected XXXX-XXXX-XXXX-XXXX.")
    if not machine_id:
        return _fail("Missing machine_id.")

    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return _fail("License key not found.")
    if lic.revoked:
        return _fail("License has been revoked.", license_id=lic.id)
    if lic.expires_at < date.today():
        return _fail("License has expired.", license_id=lic.id)

    # Product match — a license only works in its own app. Checked only
    # when the app declares its product (back-compat with older builds).
    # Done before machine binding so a wrong product never burns a seat.
    if body.product:
        _want = body.product.strip().lower()
        _have = (lic.product or "accgenie").lower()
        if _want and _want != _have:
            _names = {"accgenie": "Accounts HQ", "rwagenie": "RWA HQ",
                      "tradehq": "tradeHQ"}
            return _fail(
                f"This is a {_names.get(_have, _have)} license — it won't work "
                f"in {_names.get(_want, _want)}. Please use a "
                f"{_names.get(_want, _want)} license.",
                license_id=lic.id,
            )

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

    product = (lic.product or "accgenie").lower()
    return ValidateResponse(
        valid=True,
        plan=lic.plan,
        product=product,
        # Merged AG + RWA features when product=rwagenie, AG-only otherwise.
        features=features_for(product, lic.plan),
        txn_limit=lic.txn_limit,
        txn_used=0,  # v1: not tracked server-side; client tracks locally
        user_limit=lic.user_limit,
        seats_allowed=seats_cap,
        seats_used=seats_used,
        seats_remaining=max(0, seats_cap - seats_used),
        flats_limit=(flats_limit_for(lic.plan) if product == "rwagenie" else None),
        expires_at=lic.expires_at.isoformat(),
        company_name=lic.company_name,
        country_code=(getattr(lic, "country_code", None) or "IN").upper(),
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

    # ── Abuse cooldown ──────────────────────────────────────────────────────
    # Seat-release is a self-service endpoint with no payment loop. A
    # bad-faith actor could release on machine A → activate on machine B,
    # release on B → activate on C, treating one seat as N rotating seats.
    # Reject a release if the same key released a DIFFERENT machine in
    # the last 24 hours. Releasing the same machine_id again is treated
    # as idempotent (no cooldown — the desktop UI may retry on a flaky
    # network).
    from datetime import datetime, timedelta
    cutoff = datetime.utcnow() - timedelta(hours=24)
    recent_other = db.scalar(
        select(ValidationLog).where(
            ValidationLog.license_id  == lic.id,
            ValidationLog.error       == "seat_released",
            ValidationLog.created_at  >= cutoff,
            ValidationLog.machine_id  != machine_id,
        ).order_by(ValidationLog.created_at.desc()).limit(1)
    )
    if recent_other is not None:
        try:
            elapsed = datetime.utcnow() - recent_other.created_at
            remaining = max(timedelta(seconds=0), timedelta(hours=24) - elapsed)
            hrs = int(remaining.total_seconds() // 3600)
            mins = int((remaining.total_seconds() % 3600) // 60)
            wait_msg = f"{hrs}h {mins}m"
        except Exception:
            wait_msg = "~24h"
        _log_validation(
            db, lic.id, key, machine_id, "", ip,
            success=False, error="seat_release_blocked_cooldown",
        )
        db.commit()
        # Ops alert (best-effort, debounced to once per key per 24h so a
        # script hammering deactivate doesn't flood the inbox).
        _maybe_alert_seat_release_abuse(
            db, lic, key,
            prior_machine=recent_other.machine_id,
            prior_time=recent_other.created_at,
            new_machine=machine_id,
            new_ip=ip,
        )
        return DeactivateResponse(
            ok=False,
            error=(
                "Seat release is rate-limited to once every 24 hours per "
                f"licence. Try again in {wait_msg}. If you've genuinely "
                "lost a machine and need this released sooner, contact "
                "info@ai-consultants.in."
            ),
        )

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
        product=(lic.product or "accgenie"),
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


_MINT_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mint a license key</title>
<style>
 body{font-family:system-ui,Segoe UI,Roboto,sans-serif;max-width:640px;margin:24px auto;padding:0 16px;color:#1a1a1a}
 h1{font-size:20px;margin-bottom:2px} small{color:#666}
 label{display:block;margin:12px 0 4px;font-weight:600;font-size:13px}
 input,select{width:100%;padding:9px;border:1px solid #ccc;border-radius:8px;font-size:14px;box-sizing:border-box}
 .row{display:flex;gap:12px} .row>div{flex:1}
 button{margin-top:16px;background:#0a7a55;color:#fff;border:0;border-radius:8px;padding:12px 22px;font-size:15px;font-weight:700;cursor:pointer}
 button.sec{background:#eee;color:#333}
 #key{margin-top:16px;padding:14px;border-radius:8px;background:#e7f7ee;display:none;word-break:break-all}
 #key b{font-size:20px;letter-spacing:1px} #err{color:#c00;margin-top:12px;display:none}
 #recent{margin-top:24px;font-size:13px} table{border-collapse:collapse;width:100%} td,th{border-bottom:1px solid #eee;padding:6px;text-align:left;font-size:12px}
</style></head><body>
<h1>Mint a license key</h1>
<small>For friends &amp; beta testers. Enter your admin token once (saved in this browser only).</small>
<label>Admin token</label>
<input id="tok" type="password" placeholder="server ADMIN_TOKEN">
<div class="row">
 <div><label>Product</label><select id="product">
   <option value="accgenie">Accounts HQ</option>
   <option value="rwagenie">RWA HQ</option>
   <option value="tradehq">tradeHQ</option>
 </select></div>
 <div><label>Plan</label><select id="plan">
   <option>PREMIUM</option><option selected>PRO</option><option>STANDARD</option><option>FREE</option>
 </select></div>
</div>
<div class="row">
 <div><label>Email</label><input id="email" type="email" placeholder="friend@example.com"></div>
 <div><label>Name / company</label><input id="company" placeholder="optional"></div>
</div>
<div class="row">
 <div><label>Expires on</label><input id="expiry" type="date"></div>
 <div><label>Seats (optional)</label><input id="seats" type="number" min="0" placeholder="plan default"></div>
</div>
<label>Notes (optional)</label><input id="notes" placeholder="e.g. beta tester">
<button onclick="mint()">Mint key</button>
<button class="sec" onclick="listKeys()">Show recent keys</button>
<div id="key"></div><div id="err"></div><div id="recent"></div>
<script>
var TK='lic_admin_token';
document.getElementById('tok').value = localStorage.getItem(TK) || '';
(function(){var d=new Date(); d.setFullYear(d.getFullYear()+1); document.getElementById('expiry').value=d.toISOString().slice(0,10);})();
function tok(){var t=document.getElementById('tok').value.trim(); localStorage.setItem(TK,t); return t;}
function show(el,msg){var e=document.getElementById(el); e.style.display='block'; e.innerHTML=msg;}
function hide(el){document.getElementById(el).style.display='none';}
async function mint(){
  hide('key'); hide('err');
  var t=tok(); if(!t){show('err','Enter the admin token.');return;}
  var body={product:document.getElementById('product').value, plan:document.getElementById('plan').value,
    customer_email:document.getElementById('email').value.trim(), company_name:document.getElementById('company').value.trim(),
    expires_at:document.getElementById('expiry').value, notes:document.getElementById('notes').value.trim()};
  var s=document.getElementById('seats').value.trim(); if(s) body.seats_allowed=parseInt(s,10);
  try{
    var r=await fetch('/admin/keys',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+t},body:JSON.stringify(body)});
    var j=await r.json();
    if(r.status===201){show('key','License key (\\u2713 give this to your tester):<br><b>'+j.license_key+'</b><br><small>'+j.product+' / '+j.plan+' \\u00b7 expires '+(j.expires_at||'')+'</small>');}
    else{show('err','Error: '+(j.detail||JSON.stringify(j)));}
  }catch(e){show('err','Failed: '+e);}
}
async function listKeys(){
  hide('err'); var t=tok(); if(!t){show('err','Enter the admin token.');return;}
  try{
    var r=await fetch('/admin/keys',{headers:{'Authorization':'Bearer '+t}});
    var j=await r.json();
    if(!Array.isArray(j)){show('err','Error: '+(j.detail||JSON.stringify(j)));return;}
    var rows=j.slice(-15).reverse().map(function(k){return '<tr><td>'+k.license_key+'</td><td>'+k.product+'</td><td>'+k.plan+'</td><td>'+(k.customer_email||'')+'</td><td>'+(k.expires_at||'')+'</td></tr>';}).join('');
    document.getElementById('recent').innerHTML='<h3>Recent keys</h3><table><tr><th>Key</th><th>Product</th><th>Plan</th><th>Email</th><th>Expires</th></tr>'+rows+'</table>';
  }catch(e){show('err','Failed: '+e);}
}
</script></body></html>"""


@app.get("/admin/mint", include_in_schema=False)
def mint_page():
    """Browser minting console: a form that POSTs to /admin/keys with the
    admin token (entered once, kept in the browser). No CLI needed."""
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_MINT_HTML)


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
        product=body.product,
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


# ── GST GSTR-2B pull (Sandbox GSP proxy, wallet-metered) ─────────────────────
# REPORTS/reconcile: read the taxpayer's 2B to reconcile their books. NOT
# compliance/filing. Per-pull charge debits the credits wallet; the desktop
# never holds the GSP key. See sandbox_gst.py for the proven Sandbox contract.

import os as _os
_GST_2B_PULL_PAISE = int(_os.environ.get("GST_2B_PULL_PAISE", "1000"))   # markup; Rs 10 default


class Gst2bOtpReq(BaseModel):
    license_key: str
    machine_id:  str = ""
    gstin:       str
    username:    str


class Gst2bFetchReq(BaseModel):
    license_key: str
    machine_id:  str = ""
    gstin:       str
    username:    str
    otp:         str
    year:        str
    month:       str


def _gst_license(db: Session, key: str, machine_id: str) -> License:
    key = (key or "").strip().upper()
    if not is_valid_format(key):
        raise HTTPException(401, "Invalid license key format.")
    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None or lic.revoked or lic.expires_at < date.today():
        raise HTTPException(401, "License not valid.")
    if machine_id.strip():
        b = db.scalar(select(MachineBinding).where(
            MachineBinding.license_id == lic.id,
            MachineBinding.machine_id == machine_id.strip()))
        if b is None:
            raise HTTPException(401, "Machine not bound to this license.")
    return lic


@app.post("/api/v1/gst/2b/otp")
def gst_2b_otp(body: Gst2bOtpReq, db: Session = Depends(get_db)):
    """Trigger the GSTN OTP for a 2B pull. Gated on wallet balance so the user
    isn't sent an OTP they can't afford to spend."""
    lic = _gst_license(db, body.license_key, body.machine_id)
    credit = _get_or_create_credit_row(db, lic.id)
    db.commit()
    if credit.balance_paise < _GST_2B_PULL_PAISE:
        raise HTTPException(402, (
            f"Low balance. A GSTR-2B pull costs Rs {_GST_2B_PULL_PAISE/100:.2f}; "
            f"you have Rs {credit.balance_paise/100:.2f}. Top up to continue."))
    try:
        from license_server.sandbox_gst import generate_otp
        generate_otp(body.gstin.strip().upper(), body.username.strip())
    except Exception as e:
        raise HTTPException(502, f"GSP OTP request failed: {e}")
    return {"ok": True, "message": "OTP sent to the registered mobile.",
            "price_paise": _GST_2B_PULL_PAISE, "balance_paise": credit.balance_paise}


@app.post("/api/v1/gst/2b/fetch")
def gst_2b_fetch(body: Gst2bFetchReq, db: Session = Depends(get_db)):
    """Verify the OTP, fetch the 2B, debit the wallet ONLY on success, return
    normalised B2B invoice rows for the desktop reconciler."""
    lic = _gst_license(db, body.license_key, body.machine_id)
    credit = _get_or_create_credit_row(db, lic.id)
    if credit.balance_paise < _GST_2B_PULL_PAISE:
        raise HTTPException(402, "Low balance — top up to pull.")
    try:
        from license_server.sandbox_gst import verify_otp, fetch_2b
        gstin = body.gstin.strip().upper()
        sess = verify_otp(gstin, body.username.strip(), body.otp.strip())
        rows = fetch_2b(sess, gstin, body.year.strip(), body.month.strip())
    except Exception as e:
        raise HTTPException(502, f"GSTR-2B fetch failed (no charge): {e}")
    credit.balance_paise = max(0, credit.balance_paise - _GST_2B_PULL_PAISE)
    credit.updated_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "rows": rows, "count": len(rows),
            "charged_paise": _GST_2B_PULL_PAISE, "balance_paise": credit.balance_paise}


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


# ── Wallet = the `credits` balance (ONE wallet) ─────────────────────────────
# RWAHQ_ARCHITECTURE.md §3: there is ONE prepaid balance per license — the
# `credits` row (`_get_or_create_credit_row`). The old per-license `sms_wallets`
# balance is RETIRED: its accessor `_get_or_create_wallet` was deleted and the
# /api/v1/wallet/* endpoints + the Razorpay wallet-topup now operate on
# `credits`. `SMSWallet` (the balance table) is dormant; `SMSWalletTxn` lives on
# only as the per-message audit ledger. Do NOT reintroduce a second balance.


def _resolve_active_license(db: Session, license_key: str) -> tuple[Optional[License], str]:
    """Returns (license, err). err is empty on success.

    Same shape as the credits helpers — caller can early-return a
    ResponseModel with `ok=False, error=err`."""
    key = (license_key or "").strip().upper()
    if not is_valid_format(key):
        return None, "Invalid license key format."
    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return None, "License key not found."
    if lic.revoked:
        return None, "License is revoked."
    if lic.expires_at < date.today():
        return None, "License has expired."
    return lic, ""


@app.get("/api/v1/wallet/balance", response_model=WalletBalanceResponse)
def wallet_balance(
    license_key: str,
    db: Session = Depends(get_db),
):
    """Read-only wallet balance. Public — clients poll this to show the
    current balance in the desktop "Wallet" page and the web-app footer.

    ONE WALLET (RWAHQ_ARCHITECTURE.md §3): the wallet IS the `credits`
    balance. AI usage AND messages (SMS, visitor-pass WA, decision WA) all
    draw from it; all top-ups credit it. The old separate `sms_wallets`
    balance is retired — this endpoint and /api/v1/credits/balance return
    the SAME number now.

    Returns balance in paise (₹0.50 SMS = 50 paise)."""
    lic, err = _resolve_active_license(db, license_key)
    if lic is None:
        return WalletBalanceResponse(ok=False, error=err)
    row = _get_or_create_credit_row(db, lic.id)
    db.commit()
    return WalletBalanceResponse(
        ok=True,
        balance_paise=row.balance_paise,
        license_key=lic.license_key,
    )


@app.post("/api/v1/wallet/debit", response_model=WalletDebitResponse)
def wallet_debit(
    body: WalletDebitRequest,
    db: Session = Depends(get_db),
):
    """Atomically deduct one SMS-send's cost from the wallet and record
    the transaction. Called by desktop (`broadcast_send.py`) and by
    rwagenie-web (`sms.py`) BEFORE the actual Fast2SMS call. If the
    balance is insufficient, returns `ok=False, error='insufficient_balance'`
    and the caller must NOT send the SMS.

    Atomicity: the SELECT + UPDATE happen in a single DB session with
    commit at the end — SQLite serialises writes so concurrent debits
    can't both succeed against a balance that only covers one. (For
    Postgres later: switch the SELECT to `FOR UPDATE` to be explicit.)
    """
    lic, err = _resolve_active_license(db, body.license_key)
    if lic is None:
        return WalletDebitResponse(ok=False, error=err)

    # ONE WALLET: debit the `credits` balance (the single active wallet) —
    # not a separate sms_wallets row. `sms_wallet_txns` is kept ONLY as the
    # per-message audit ledger (recipient/kind/ref), with balance_after now
    # reflecting the credits balance.
    row = _get_or_create_credit_row(db, lic.id)
    if row.balance_paise < body.amount_paise:
        return WalletDebitResponse(
            ok=False,
            balance_after_paise=row.balance_paise,
            error="insufficient_balance",
        )

    row.balance_paise -= body.amount_paise
    row.updated_at = datetime.utcnow()
    txn = SMSWalletTxn(
        license_id=lic.id,
        amount_paise=-body.amount_paise,          # signed: debit is negative
        kind=body.kind,
        ref=body.ref or "",
        recipient_phone=body.recipient_phone or "",
        balance_after_paise=row.balance_paise,
        machine_id=body.machine_id or "",
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return WalletDebitResponse(
        ok=True,
        balance_after_paise=row.balance_paise,
        txn_id=txn.id,
    )


@app.post("/api/v1/wallet/topup/create-order",
          response_model=WalletTopupCreateResponse)
def wallet_topup_create_order(
    body: WalletTopupCreateRequest,
    db: Session = Depends(get_db),
):
    """Create a Razorpay order to top up an SMS wallet by `amount_paise`.

    On payment success, `/webhooks/razorpay` branches on
    `order.kind == 'wallet_topup'` and credits the wallet (no License
    mint — the License already exists). The `wallet_license_id` column
    on the Order row carries the target license forward to the webhook
    handler.
    """
    if not razorpay_client.is_enabled():
        return WalletTopupCreateResponse(
            ok=False, error="Payments are not configured on this server.",
        )

    lic, err = _resolve_active_license(db, body.license_key)
    if lic is None:
        return WalletTopupCreateResponse(ok=False, error=err)

    email = (body.customer_email or lic.customer_email or "").strip()
    try:
        rp_order = razorpay_client.create_order(
            amount_paise=body.amount_paise,
            currency="INR",
            receipt_id=f"wlt-{lic.license_key[:8]}-{int(datetime.utcnow().timestamp())}",
            notes={
                "kind":          "wallet_topup",
                "license_key":   lic.license_key,
                "license_id":    str(lic.id),
                "customer_email": email,
            },
        )
    except razorpay_client.RazorpayError as e:
        return WalletTopupCreateResponse(ok=False, error=f"Razorpay: {e}")

    order = Order(
        razorpay_order_id=rp_order["id"],
        kind="wallet_topup",
        wallet_license_id=lic.id,
        product=lic.product or "rwagenie",
        plan=lic.plan,
        amount_paise=body.amount_paise,
        currency="INR",
        country_code="IN",
        customer_email=email,
        customer_name=body.customer_name or "",
        company_name=lic.company_name or "",
        status="created",
        notes=f"[create wallet-topup] license={lic.license_key} "
              f"receipt={rp_order.get('receipt','')}",
    )
    db.add(order)
    db.commit()

    return WalletTopupCreateResponse(
        ok=True,
        order_id=rp_order["id"],
        amount_paise=body.amount_paise,
        currency="INR",
        razorpay_key_id=settings.razorpay_key_id,
    )


@app.get("/wallet/pay", response_class=HTMLResponse)
def wallet_pay_page(order_id: str = "", key: str = "", amount: int = 0,
                    name: str = "", email: str = ""):
    """Minimal Razorpay checkout page for a wallet top-up order. The desktop
    app opens this in the browser after creating the order; on success the
    `/webhooks/razorpay` handler credits the wallet (order.kind=wallet_topup),
    so this page only has to run the Razorpay modal."""
    opts = {
        "key": key,
        "order_id": order_id,
        "amount": int(amount or 0),
        "currency": "INR",
        "name": "AI Consultants",
        "description": "Accounts HQ — AI wallet top-up",
        "prefill": {"name": name or "", "email": email or ""},
        "theme": {"color": "#0a7a55"},
    }
    opts_json = json.dumps(opts)
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        "<title>AI Wallet top-up</title>"
        "<style>body{font-family:-apple-system,Segoe UI,Arial,sans-serif;"
        "background:#0b1220;color:#eef2ff;display:flex;align-items:center;"
        "justify-content:center;height:100vh;margin:0;text-align:center}"
        ".box{max-width:440px;padding:28px}h2{margin:0 0 8px}"
        "p{color:#9fb0d6}button{margin-top:14px;background:#0a7a55;color:#fff;"
        "border:0;border-radius:8px;padding:12px 22px;font-size:15px;"
        "font-weight:700;cursor:pointer}</style>"
        "<script src='https://checkout.razorpay.com/v1/checkout.js'></script>"
        "</head><body><div class='box'>"
        "<h2>AI Wallet top-up</h2>"
        "<p id='msg'>Opening secure Razorpay checkout…</p>"
        "<button id='retry' style='display:none' onclick='openRzp()'>Open payment</button>"
        "</div><script>"
        f"var OPTS={opts_json};"
        "OPTS.handler=function(r){document.getElementById('msg').innerHTML="
        "'\\u2713 Payment received. Your credits will appear in Accounts HQ "
        "shortly \\u2014 you can close this tab and click Refresh in the app.';"
        "document.getElementById('retry').style.display='none';};"
        "OPTS.modal={ondismiss:function(){document.getElementById('msg')"
        ".innerHTML='Payment was not completed.';"
        "document.getElementById('retry').style.display='inline-block';}};"
        "function openRzp(){if(!OPTS.key||!OPTS.order_id){"
        "document.getElementById('msg').innerHTML='Missing order details.';return;}"
        "var rzp=new Razorpay(OPTS);rzp.open();}"
        "openRzp();"
        "</script></body></html>"
    )
    return HTMLResponse(page)


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
    /webhooks/razorpay when Razorpay confirms the payment — EXCEPT for
    the FREE tier, which short-circuits below: no Razorpay order is
    created, the license is minted and emailed inline, and the caller
    gets `free=true` in the response so it can skip the Razorpay modal.
    """
    plan = (body.plan or "").upper()
    product = (body.product or "accgenie").lower()
    country = (body.country_code or "IN").upper()
    period = (body.billing_period or "annual").lower()
    email = (body.customer_email or "").strip()
    if not email or "@" not in email:
        return CheckoutCreateResponse(ok=False, error="Valid email required")

    if product not in VALID_PRODUCTS:
        return CheckoutCreateResponse(ok=False, error=f"Unknown product: {product}")

    # ── FREE-tier short-circuit ──────────────────────────────────────
    # No payment, so we don't need Razorpay to be enabled on this
    # server. Mint the key, persist an Order row for audit, email the
    # key, and return early.
    if plan == "FREE":
        try:
            lic = mint_license(
                db=db,
                product=product,
                plan="FREE",
                customer_email=email,
                company_name=body.company_name or "",
                expires_at=default_expiry_for_plan("FREE"),
                notes="free-tier self-serve checkout",
            )
        except MintError as e:
            return CheckoutCreateResponse(ok=False, error=f"Mint failed: {e}")

        # Audit row — same shape as a paid Order but amount=0,
        # razorpay_order_id synthesised so the unique-index doesn't clash.
        order = Order(
            razorpay_order_id=f"free-{int(datetime.utcnow().timestamp())}-{lic.id}",
            product=product, plan="FREE", amount_paise=0, currency="INR",
            country_code=country, customer_email=email,
            customer_name=body.customer_name or "",
            customer_phone=body.customer_phone or "",
            company_name=body.company_name or "",
            status="paid", license_id=lic.id,
            notes=f"[free] license={lic.license_key}",
        )
        db.add(order)
        db.commit()

        # Email the key (best-effort — same pattern as the webhook).
        try:
            email_service.send_license_email(
                to_email=email,
                license_key=lic.license_key,
                plan="FREE",
                expires_at=lic.expires_at.isoformat(),
                customer_name=body.customer_name or "",
                amount_paid_str="Free",
                product=product,
            )
        except Exception:
            pass

        return CheckoutCreateResponse(
            ok=True, free=True,
            plan="FREE", plan_name="Free",
            product=product,
            amount_paise=0, amount_display="Free", currency="INR",
            license_key=lic.license_key,
        )

    # Paid tiers from here on need Razorpay configured.
    if not razorpay_client.is_enabled():
        raise HTTPException(503, "Payments are not configured on this server.")

    # ── Pricing ──
    # AG uses the baked pricing.xlsx via resolve_price().
    # RWAGenie + tradeHQ use the inline price_for() tables in plans.py
    # (no sister xlsx files yet). All three branches produce the same
    # {amount_paise, currency, plan_code, ...} dict so the rest of this
    # handler stays product-agnostic.
    from license_server.plans import price_paise_for
    paise = price_paise_for(product, plan, country, period)
    if not paise:
        product_label = {"rwagenie": "RWA HQ", "tradehq": "tradeHQ"}.get(
            product, "Accounts HQ")
        extra = " (monthly)" if period == "monthly" else ""
        return CheckoutCreateResponse(
            ok=False,
            error=(f"{product_label} {plan}{extra} is not priced for sale "
                   f"in {country} yet."),
        )
    if product in ("rwagenie", "tradehq"):
        price = {
            "plan_code":      plan,
            "plan_name":      plan.title(),
            "currency":       "INR",
            "amount_paise":   paise,
            "amount_display": f"Rs. {paise/100:,.2f}",
            "country_code":   country,
        }
    else:
        # accgenie — name/currency/symbol from resolve_price (multi-country),
        # amount from the period-aware price_paise_for (annual or 11% monthly).
        try:
            base = resolve_price(plan, country)
        except PricingError as e:
            return CheckoutCreateResponse(ok=False, error=str(e))
        sym = base.get("currency_symbol", "")
        price = {
            "plan_code":      base["plan_code"],
            "plan_name":      base["plan_name"],
            "currency":       base["currency"],
            "amount_paise":   paise,
            "amount_display": f"{sym} {paise/100:,.2f}".strip(),
            "country_code":   base["country_code"],
        }

    # Create the Razorpay order. The 'notes' field gets stored alongside
    # the order and echoed back in the webhook payload — useful for
    # cross-checking which Order row to update.
    receipt_prefix = {
        "rwagenie": "rwag",
        "tradehq":  "thq",
    }.get(product, "accg")
    try:
        rp_order = razorpay_client.create_order(
            amount_paise=price["amount_paise"],
            currency=price["currency"],
            receipt_id=f"{receipt_prefix}-{plan[:4]}-{int(datetime.utcnow().timestamp())}",
            notes={
                "product":        product,
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
        product=product,
        plan=price["plan_code"],
        billing_period=period,
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


# ── License upgrade (in-place; new full price − balance of existing key) ──────

class UpgradeQuoteRequest(BaseModel):
    license_key: str = Field(..., min_length=4, max_length=32)


class UpgradeOption(BaseModel):
    target_plan:      str
    new_full_display: str
    balance_display:  str
    upgrade_display:  str
    upgrade_paise:    int
    new_expiry:       str


class UpgradeQuoteResponse(BaseModel):
    ok:              bool
    error:           Optional[str] = None
    product:         Optional[str] = None
    current_plan:    Optional[str] = None
    billing_period:  Optional[str] = None
    expires_at:      Optional[str] = None
    days_left:       Optional[int] = None
    razorpay_key_id: Optional[str] = None
    options:         list[UpgradeOption] = []


class UpgradeOrderRequest(BaseModel):
    license_key: str = Field(..., min_length=4, max_length=32)
    target_plan: str = Field(..., min_length=2, max_length=16)


_UPGRADE_TIERS = ("STANDARD", "PRO", "PREMIUM")


@app.post("/api/v1/checkout/upgrade-quote", response_model=UpgradeQuoteResponse)
def upgrade_quote(body: UpgradeQuoteRequest, db: Session = Depends(get_db)):
    """Given an existing key, return the upgrade price to each higher tier:
    new full (period) price − the balance value of the current key."""
    key = (body.license_key or "").strip().upper()
    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return UpgradeQuoteResponse(ok=False, error="License key not found.")
    if lic.revoked:
        return UpgradeQuoteResponse(ok=False, error="This license is revoked.")
    period = (lic.billing_period or "annual").lower()
    options: list[UpgradeOption] = []
    for tgt in _UPGRADE_TIERS:
        if tier_rank(tgt) <= tier_rank(lic.plan):
            continue
        try:
            q = compute_upgrade(lic.product, lic.plan, lic.expires_at, tgt,
                                "IN", period)
        except PricingError:
            continue
        options.append(UpgradeOption(
            target_plan=tgt,
            new_full_display=q["new_full_display"],
            balance_display=q["balance_display"],
            upgrade_display=q["upgrade_display"],
            upgrade_paise=q["upgrade_paise"],
            new_expiry=q["new_expiry"],
        ))
    return UpgradeQuoteResponse(
        ok=True, product=lic.product, current_plan=lic.plan,
        billing_period=period, expires_at=lic.expires_at.isoformat(),
        days_left=max(0, (lic.expires_at - date.today()).days),
        razorpay_key_id=settings.razorpay_key_id, options=options,
    )


@app.post("/api/v1/checkout/create-upgrade-order",
          response_model=CheckoutCreateResponse)
def create_upgrade_order(body: UpgradeOrderRequest, db: Session = Depends(get_db)):
    """Razorpay order for an in-place tier upgrade. Price recomputed server-side
    (never trust the client). On payment the webhook upgrades the EXISTING key
    (plan + fresh full term) — no new key is minted."""
    if not razorpay_client.is_enabled():
        raise HTTPException(503, "Payments are not configured on this server.")
    key = (body.license_key or "").strip().upper()
    tgt = (body.target_plan or "").strip().upper()
    lic = db.scalar(select(License).where(License.license_key == key))
    if lic is None:
        return CheckoutCreateResponse(ok=False, error="License key not found.")
    if lic.revoked:
        return CheckoutCreateResponse(ok=False, error="This license is revoked.")
    period = (lic.billing_period or "annual").lower()
    try:
        q = compute_upgrade(lic.product, lic.plan, lic.expires_at, tgt, "IN", period)
    except PricingError as e:
        return CheckoutCreateResponse(ok=False, error=str(e))
    if q["upgrade_paise"] <= 0:
        return CheckoutCreateResponse(
            ok=False,
            error="No upgrade charge is due — contact support to switch tiers.")
    try:
        rp_order = razorpay_client.create_order(
            amount_paise=q["upgrade_paise"], currency="INR",
            receipt_id=f"upg-{tgt[:4]}-{int(datetime.utcnow().timestamp())}",
            notes={"kind": "tier_upgrade", "license_key": key,
                   "target_plan": tgt, "product": lic.product, "period": period},
        )
    except razorpay_client.RazorpayError as e:
        return CheckoutCreateResponse(ok=False, error=f"Razorpay: {e}")
    order = Order(
        razorpay_order_id=rp_order["id"], kind="tier_upgrade",
        product=lic.product, plan=tgt, billing_period=period,
        amount_paise=q["upgrade_paise"], currency="INR", country_code="IN",
        customer_email=lic.customer_email, company_name=lic.company_name or "",
        wallet_license_id=lic.id, status="created",
        notes=f"[upgrade-create] {lic.plan}->{tgt} key={key}",
    )
    db.add(order)
    db.commit()
    return CheckoutCreateResponse(
        ok=True, order_id=rp_order["id"], amount_paise=q["upgrade_paise"],
        amount_display=q["upgrade_display"], currency="INR",
        razorpay_key_id=settings.razorpay_key_id,
        plan=tgt, plan_name=tgt.title(), product=lic.product,
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
    if order.status == "paid":
        return {"ok": True, "status": "already_paid",
                "license_id": order.license_id,
                "wallet_license_id": order.wallet_license_id}

    # ── Wallet top-up branch ──
    # Wallet top-ups don't mint a License — they credit an existing one.
    # The Order row carries `wallet_license_id` set at create-order time.
    if (order.kind or "tier_purchase") == "wallet_topup":
        target_id = order.wallet_license_id
        if not target_id:
            raise HTTPException(500, "Wallet top-up order missing wallet_license_id")
        lic = db.get(License, target_id)
        if lic is None:
            raise HTTPException(500, f"Wallet top-up target license {target_id} not found")

        # ONE WALLET: a wallet top-up credits the `credits` balance (the
        # single active wallet), not a separate sms_wallets row.
        row = _get_or_create_credit_row(db, lic.id)
        row.balance_paise += order.amount_paise
        row.updated_at = datetime.utcnow()
        db.add(SMSWalletTxn(
            license_id=lic.id,
            amount_paise=order.amount_paise,
            kind="topup",
            ref=rp_payment_id,
            balance_after_paise=row.balance_paise,
        ))
        order.status              = "paid"
        order.razorpay_payment_id = rp_payment_id
        order.notes               = (order.notes or "") + (
            f"\n[paid wallet-topup] license={lic.license_key} "
            f"+{order.amount_paise} paise payment={rp_payment_id}"
        )
        db.commit()
        return {"ok": True, "status": "wallet_credited",
                "wallet_license_id": lic.id,
                "balance_paise": row.balance_paise}

    # ── Tier-upgrade branch ──
    # Upgrade the EXISTING license in place (no new key): new plan + fresh full
    # term + new-tier limits. The order carries the existing license id and the
    # target plan/period.
    if (order.kind or "tier_purchase") == "tier_upgrade":
        target_id = order.wallet_license_id
        lic = db.get(License, target_id) if target_id else None
        if lic is None:
            raise HTTPException(500, "Upgrade order: target license not found")
        from license_server.plans import (
            PLAN_LIMITS, PLAN_USER_LIMITS, PLAN_SEATS,
        )
        old_plan = lic.plan
        lic.plan           = order.plan
        lic.billing_period = order.billing_period or "annual"
        lic.expires_at     = expiry_for(order.plan, lic.billing_period)
        try:
            lic.txn_limit     = PLAN_LIMITS.get(order.plan, lic.txn_limit)
            lic.user_limit    = PLAN_USER_LIMITS.get(order.plan, lic.user_limit)
            lic.seats_allowed = PLAN_SEATS.get(order.plan, lic.seats_allowed)
        except Exception:
            pass
        order.status              = "paid"
        order.razorpay_payment_id = rp_payment_id
        order.license_id          = lic.id
        order.notes               = (order.notes or "") + (
            f"\n[paid upgrade] {old_plan}->{lic.plan} key={lic.license_key} "
            f"payment={rp_payment_id}"
        )
        db.commit()
        try:
            email_service.send_license_email(
                to_email=lic.customer_email,
                license_key=lic.license_key,
                plan=lic.plan,
                expires_at=lic.expires_at.isoformat(),
                customer_name=order.customer_name or "",
                amount_paid_str=f"INR {order.amount_paise/100:,.2f}",
                product=lic.product or "accgenie",
            )
        except Exception:
            pass
        return {"ok": True, "status": "upgraded",
                "license_id": lic.id, "plan": lic.plan}

    # ── Tier-purchase branch (the original flow) ──
    # Mint the license. Carry the product (accgenie/rwagenie) forward
    # from the order so RWAGenie purchases produce RWAGenie licenses.
    try:
        lic = mint_license(
            db=db,
            product=(order.product or "accgenie"),
            plan=order.plan,
            customer_email=order.customer_email,
            company_name=order.company_name,
            expires_at=expiry_for(order.plan, order.billing_period or "annual"),
            billing_period=order.billing_period or "annual",
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
            product=order.product or "accgenie",
        )
    except Exception:
        # Already logged inside email_service; swallow here.
        pass

    return {"ok": True, "status": "paid", "license_id": lic.id}


# ── Marketing site (static files) ────────────────────────────────────────
# Serves the public website (index.html, pricing.html, privacy.html, etc.)
# from the marketing/ folder. Mount happens AFTER all API routes so
# /api/v1/*, /admin/*, /webhooks/* and FastAPI's own /docs, /openapi.json
# still match their route handlers first; only unmatched paths fall
# through to StaticFiles.
#
# Razorpay activation needs a public website at the registered KYC
# business name. Hosting the static pages from the same Fly app avoids
# spinning up a separate host. See project-marketing-site memory.
#
# Multi-tenant marketing — two parallel brands on the same Fly app:
#   apps.ai-consultants.in        → marketing/      (Aashray Sanghi)
#   aic.ai-consultants.in         → marketing-aic/  (AI Consultants /
#                                                    Analysis and Ideas
#                                                    Consultants, prop.
#                                                    Monika Sanghi)
# ── Support chatbot (public, KB-grounded) ─────────────────────────────────
# The canned/keyword layer runs in the browser (chat-widget.js) and answers
# common questions for free. Anything it can't match POSTs to /api/chat, which:
#   1) serves a prior AI answer from chat_learned if we've seen the question
#      (instant + free — the self-improving cache),
#   2) otherwise asks Claude Haiku grounded ONLY in the baked KB, stores the
#      Q&A as 'pending' for review, and returns it.
# Cost is bounded by a per-IP hourly limit + a global daily cap; cache hits and
# the browser's canned answers don't count toward either.

CHAT_MODEL          = "claude-haiku-4-5"
CHAT_MAX_TOKENS     = 500
CHAT_DAILY_CAP      = 500      # global AI calls/day
CHAT_PER_IP_HOUR    = 20       # AI calls per visitor IP per hour
CHAT_FALLBACK_EMAIL = ("I'm not sure about that one — please email "
                       "info@ai-consultants.in and we'll help you directly.")
CHAT_FALLBACK_BUSY  = ("I'm getting a lot of questions right now. Please email "
                       "info@ai-consultants.in and we'll get back to you.")

CHAT_SYSTEM = (
    "You are the friendly help assistant for Accounts HQ (by AI Consultants) on the "
    "company website. Answer the user's question using ONLY the knowledge base "
    "between <kb> and </kb>. If the answer is not in the knowledge base, say you're "
    "not sure and suggest emailing info@ai-consultants.in — never guess or make up "
    "steps, prices, or tax figures. Keep answers concise and friendly: 2-5 sentences "
    "or a few short steps, plain text (no markdown headings). Accounts HQ records "
    "transactions and computes GST/TDS from the rates set on each ledger; it is NOT a "
    "tax-filing or compliance engine and you must not give tax or legal advice — for "
    "'should I' tax questions, tell the user to confirm with their CA. Only discuss "
    "Accounts HQ and AI Consultants; politely decline anything unrelated.\n\n"
    "<kb>\n" + KB_TEXT + "\n</kb>"
)

_chat_day = {"date": "", "count": 0}             # global daily counter (in-memory)
_chat_ip: dict[str, list[float]] = {}            # ip -> recent call timestamps


def _norm_q(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()[:400]


def _chat_ip_ok(ip: str) -> bool:
    now = time.time()
    hits = [t for t in _chat_ip.get(ip, []) if now - t < 3600]
    if len(hits) >= CHAT_PER_IP_HOUR:
        _chat_ip[ip] = hits
        return False
    hits.append(now)
    _chat_ip[ip] = hits
    return True


def _chat_day_ok() -> bool:
    today = date.today().isoformat()
    if _chat_day["date"] != today:
        _chat_day.update(date=today, count=0)
    return _chat_day["count"] < CHAT_DAILY_CAP


def _chat_call_ai(question: str, history: list) -> tuple[str, bool]:
    """Blocking Haiku call grounded in the KB. Run via asyncio.to_thread."""
    msgs = []
    for h in (history or [])[-6:]:
        if not isinstance(h, dict):
            continue
        role = "assistant" if h.get("role") == "bot" else "user"
        content = str(h.get("content", ""))[:800]
        if content:
            msgs.append({"role": role, "content": content})
    msgs.append({"role": "user", "content": question})
    req = {
        "model": CHAT_MODEL,
        "max_tokens": CHAT_MAX_TOKENS,
        "system": [{"type": "text", "text": CHAT_SYSTEM,
                    "cache_control": {"type": "ephemeral"}}],
        "messages": msgs,
    }
    status_code, data, _err = _forward_to_anthropic(json.dumps(req).encode("utf-8"))
    if status_code == 200 and data:
        txt = "".join(b.get("text", "") for b in data.get("content", [])
                      if b.get("type") == "text").strip()
        if txt:
            return txt, True
    return "", False


class ChatIn(BaseModel):
    message: str = ""
    history: list = Field(default_factory=list)


@app.post("/api/chat")
async def chat(body: ChatIn, request: Request, db: Session = Depends(get_db)):
    msg = (body.message or "").strip()[:600]
    if not msg:
        return {"answer": "Ask me about Accounts HQ — pricing, GST, bank reconciliation, "
                          "migrating from Tally, and so on."}

    if not _chat_ip_ok(_client_ip(request)):
        return {"answer": CHAT_FALLBACK_BUSY, "limited": True}

    qn = _norm_q(msg)
    row = db.scalar(select(ChatLearned).where(ChatLearned.qnorm == qn))
    if row is not None and row.status != "discarded":
        row.hits += 1
        db.commit()
        return {"answer": row.answer, "cached": True}

    if not settings.anthropic_api_key or not _chat_day_ok():
        return {"answer": CHAT_FALLBACK_BUSY, "limited": True}

    answer, ok = await asyncio.to_thread(_chat_call_ai, msg, body.history)
    if not ok or not answer:
        return {"answer": CHAT_FALLBACK_EMAIL}

    _chat_day["count"] += 1
    if row is None:                  # don't re-learn a previously-discarded question
        db.add(ChatLearned(qnorm=qn, question=msg, answer=answer,
                           hits=1, status="pending"))
        db.commit()
    return {"answer": answer}


# ── Admin: review the bot's learned answers ───────────────────────────────

class ChatReviewAction(BaseModel):
    action: str                       # approve | discard | save
    answer: Optional[str] = None


@app.post("/admin/chat-review/{row_id}", dependencies=[Depends(require_admin)])
def chat_review_action(row_id: int, body: ChatReviewAction,
                       db: Session = Depends(get_db)):
    row = db.get(ChatLearned, row_id)
    if row is None:
        raise HTTPException(status_code=404, detail="not found")
    if body.action == "approve":
        row.status = "approved"
    elif body.action == "discard":
        row.status = "discarded"
    elif body.action == "save":
        if body.answer is not None:
            row.answer = body.answer.strip()[:4000]
    else:
        raise HTTPException(status_code=400, detail="bad action")
    db.commit()
    return {"ok": True, "id": row.id, "status": row.status}


@app.get("/admin/chat-review", response_class=HTMLResponse)
def chat_review_page(token: str = "", db: Session = Depends(get_db)):
    if token != settings.admin_token:
        return HTMLResponse(
            "<h2>Chat review</h2><p>Append <code>?token=YOUR_ADMIN_TOKEN</code> to the URL.</p>",
            status_code=403)
    rows = db.scalars(select(ChatLearned).order_by(ChatLearned.hits.desc())).all()
    rank = {"pending": 0, "approved": 1, "discarded": 2}
    rows = sorted(rows, key=lambda r: (rank.get(r.status, 3), -r.hits))
    esc = _html.escape
    cards = []
    for r in rows:
        cards.append(f"""
      <div class="card s-{esc(r.status)}" id="row-{r.id}">
        <div class="meta"><b>#{r.id}</b> &middot; <span class="st">{esc(r.status)}</span> &middot; {r.hits} ask(s)</div>
        <div class="q">{esc(r.question)}</div>
        <textarea id="a-{r.id}">{esc(r.answer)}</textarea>
        <div class="btns">
          <button onclick="act({r.id},'save')">Save edit</button>
          <button class="ok" onclick="act({r.id},'approve')">Approve</button>
          <button class="no" onclick="act({r.id},'discard')">Discard</button>
        </div>
      </div>""")
    body_html = "\n".join(cards) or "<p>No learned answers yet — the bot hasn't been asked anything new.</p>"
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Chat review</title>
<style>
 body{{font-family:system-ui,Arial,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#0f172a}}
 h2{{margin:0 0 4px}} .sub{{color:#64748b;margin-bottom:18px;font-size:14px}}
 .card{{border:1px solid #e2e8f0;border-radius:12px;padding:14px 16px;margin-bottom:14px}}
 .card.s-pending{{border-left:4px solid #f59e0b}} .card.s-approved{{border-left:4px solid #16a34a}}
 .card.s-discarded{{border-left:4px solid #cbd5e1;opacity:.55}}
 .meta{{font-size:12.5px;color:#64748b;margin-bottom:6px}} .st{{text-transform:uppercase;font-weight:700}}
 .q{{font-weight:700;margin-bottom:8px}}
 textarea{{width:100%;min-height:78px;border:1px solid #cbd5e1;border-radius:8px;padding:8px;font:inherit}}
 .btns{{margin-top:8px;display:flex;gap:8px}}
 button{{border:1px solid #cbd5e1;background:#fff;border-radius:8px;padding:7px 12px;cursor:pointer;font-weight:600}}
 button.ok{{background:#16a34a;color:#fff;border-color:#16a34a}}
 button.no{{background:#fff;color:#b91c1c;border-color:#fca5a5}}
</style></head><body>
<h2>Support bot — learned answers</h2>
<div class="sub">Pending first, then most-asked. <b>Approve</b> keeps serving it; edit the text then <b>Save edit</b> to fix it; <b>Discard</b> stops serving it and never re-learns it. (Folding into the canonical KB docs is a separate rebake.)</div>
{body_html}
<script>
const TOKEN={json.dumps(token)};
async function act(id, action){{
  const ans = document.getElementById('a-'+id).value;
  const r = await fetch('/admin/chat-review/'+id, {{
    method:'POST',
    headers:{{'Content-Type':'application/json','Authorization':'Bearer '+TOKEN}},
    body: JSON.stringify({{action: action, answer: ans}})
  }});
  if(r.ok){{ const d = await r.json(); const card = document.getElementById('row-'+id);
    card.className = 'card s-'+d.status; card.querySelector('.st').textContent = d.status; }}
  else {{ alert('Failed: '+r.status); }}
}}
</script></body></html>"""
    return HTMLResponse(page)


# A small middleware checks the Host header and (for AIC) rewrites the
# request path to a private prefix that's served from the AIC folder.
# The user-visible URL stays clean; only the internal routing path
# changes.

_marketing_dir     = Path(__file__).resolve().parent.parent / "marketing"
_marketing_aic_dir = Path(__file__).resolve().parent.parent / "marketing-aic"

_AIC_INTERNAL_PREFIX = "/_aic-static"
_AIC_HOSTNAME        = "aic.ai-consultants.in"


@app.middleware("http")
async def _aic_host_rewrite(request, call_next):
    """For requests on the AIC hostname, internally re-route to the
    AIC static mount. User-visible URL is unchanged. Requests on any
    other hostname (apps.*, license.*, raw fly.dev, etc.) pass through
    untouched and serve the existing marketing/ folder."""
    host = (request.headers.get("host") or "").split(":", 1)[0].lower()
    if host == _AIC_HOSTNAME:
        # Don't double-prefix if for some reason the path is already
        # under the internal prefix (shouldn't happen via the public
        # hostname, but defensive). Also leave real API/admin routes alone —
        # otherwise the chat widget's /api/chat (and /admin/*) on the AIC host
        # would get rewritten into the static mount and 404.
        path = request.scope["path"]
        if (not path.startswith(_AIC_INTERNAL_PREFIX)
                and not path.startswith("/api/")
                and not path.startswith("/admin/")):
            request.scope["path"] = _AIC_INTERNAL_PREFIX + path
            request.scope["raw_path"] = request.scope["path"].encode("utf-8")
    return await call_next(request)


# Mount AIC FIRST so /_aic-static routes match before the catch-all /
# mount below it.
if _marketing_aic_dir.is_dir():
    app.mount(_AIC_INTERNAL_PREFIX,
              StaticFiles(directory=str(_marketing_aic_dir), html=True),
              name="marketing-aic")

if _marketing_dir.is_dir():
    app.mount("/", StaticFiles(directory=str(_marketing_dir), html=True),
              name="marketing")
