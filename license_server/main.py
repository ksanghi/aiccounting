"""
AccGenie license server.

Endpoints:
  POST /api/v1/license/validate   public — desktop client calls this
  GET  /api/v1/health             public health check

  POST /admin/keys                admin — mint a new key
  GET  /admin/keys                admin — list keys
  GET  /admin/keys/{key}          admin — show one key + machines + recent logs
  POST /admin/keys/{key}/revoke   admin — revoke
  POST /admin/keys/{key}/extend   admin — extend expiry

Admin endpoints require header:  Authorization: Bearer <ADMIN_TOKEN>
"""
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional

from fastapi import FastAPI, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from license_server.config import settings
from license_server.db import init_db, get_db
from license_server.models import License, MachineBinding, ValidationLog, Install
from license_server.plans import (
    PLANS, PLAN_LIMITS, PLAN_USER_LIMITS, PLAN_FEATURES,
)
from license_server.keys import is_valid_format


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
    valid:         bool
    plan:          Optional[str]  = None
    features:      Optional[list] = None
    txn_limit:     Optional[int]  = None
    txn_used:      Optional[int]  = None
    user_limit:    Optional[int]  = None
    expires_at:    Optional[str]  = None
    company_name:  Optional[str]  = None
    error:         Optional[str]  = None


class MintRequest(BaseModel):
    plan:           str = Field(..., pattern="^(FREE|STANDARD|PRO|PREMIUM)$")
    customer_email: str = ""
    company_name:   str = ""
    expires_at:     date
    notes:          str = ""
    txn_limit:      Optional[int] = None  # override plan default
    user_limit:     Optional[int] = None  # override plan default


class KeyOut(BaseModel):
    license_key:    str
    plan:           str
    customer_email: str
    company_name:   str
    expires_at:     date
    txn_limit:      int
    user_limit:     int
    revoked:        bool
    notes:          str
    created_at:     datetime
    machine_count:  int

    model_config = {"from_attributes": True}


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

    # Machine binding: bind on first seen, reject if over limit.
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
        if existing >= settings.max_machines_per_key:
            return _fail(
                f"License already activated on {existing} machines "
                f"(limit {settings.max_machines_per_key}). "
                f"Contact support to re-bind.",
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

    return ValidateResponse(
        valid=True,
        plan=lic.plan,
        features=PLAN_FEATURES.get(lic.plan, []),
        txn_limit=lic.txn_limit,
        txn_used=0,  # v1: not tracked server-side; client tracks locally
        user_limit=lic.user_limit,
        expires_at=lic.expires_at.isoformat(),
        company_name=lic.company_name,
    )


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
