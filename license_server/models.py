"""DB models — License, MachineBinding, ValidationLog."""
from datetime import datetime, date
from sqlalchemy import (
    String, Integer, Date, DateTime, ForeignKey, Boolean, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from license_server.db import Base


class License(Base):
    __tablename__ = "licenses"

    id:             Mapped[int]      = mapped_column(primary_key=True)
    license_key:    Mapped[str]      = mapped_column(String(32), unique=True, index=True)
    plan:           Mapped[str]      = mapped_column(String(16))
    customer_email: Mapped[str]      = mapped_column(String(256), default="")
    company_name:   Mapped[str]      = mapped_column(String(256), default="")
    expires_at:     Mapped[date]     = mapped_column(Date)
    txn_limit:      Mapped[int]      = mapped_column(Integer)
    user_limit:     Mapped[int]      = mapped_column(Integer)
    # Per-license seat cap. Replaces the global settings.max_machines_per_key.
    # Backfilled to 3 on existing rows via db.init_db()'s additive migration.
    seats_allowed:  Mapped[int]      = mapped_column(Integer, default=3, server_default="3")
    revoked:        Mapped[bool]     = mapped_column(Boolean, default=False)
    notes:          Mapped[str]      = mapped_column(String(512), default="")
    created_at:     Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    machines:    Mapped[list["MachineBinding"]] = relationship(back_populates="license", cascade="all, delete-orphan")
    validations: Mapped[list["ValidationLog"]]  = relationship(back_populates="license", cascade="all, delete-orphan")


class MachineBinding(Base):
    __tablename__ = "machine_bindings"

    id:             Mapped[int]      = mapped_column(primary_key=True)
    license_id:     Mapped[int]      = mapped_column(ForeignKey("licenses.id"), index=True)
    machine_id:     Mapped[str]      = mapped_column(String(64), index=True)
    first_seen_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    license: Mapped["License"] = relationship(back_populates="machines")


class Install(Base):
    """
    Anonymous install tracking. One row per (install_id) — generated locally
    by the desktop client on first launch and persisted in user_data_dir.

    No PII: install_id is a client-generated UUID, machine_id is a hash of
    hostname+arch. We do NOT store IP here (it's logged by the platform if
    needed for abuse, but not in our DB).
    """
    __tablename__ = "installs"

    id:              Mapped[int]      = mapped_column(primary_key=True)
    install_id:      Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    machine_id:      Mapped[str]      = mapped_column(String(64), index=True)
    app_version:     Mapped[str]      = mapped_column(String(32), default="")
    plan:            Mapped[str]      = mapped_column(String(16), default="FREE")
    license_key:     Mapped[str]      = mapped_column(String(32), default="")
    os_name:         Mapped[str]      = mapped_column(String(32), default="")
    first_seen_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at:    Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    heartbeat_count: Mapped[int]      = mapped_column(Integer, default=1)


class ValidationLog(Base):
    __tablename__ = "validation_logs"

    id:           Mapped[int]      = mapped_column(primary_key=True)
    license_id:   Mapped[int | None] = mapped_column(ForeignKey("licenses.id"), index=True, nullable=True)
    license_key:  Mapped[str]      = mapped_column(String(32), index=True)
    machine_id:   Mapped[str]      = mapped_column(String(64))
    app_version:  Mapped[str]      = mapped_column(String(32), default="")
    ip:           Mapped[str]      = mapped_column(String(64), default="")
    success:      Mapped[bool]     = mapped_column(Boolean)
    error:        Mapped[str]      = mapped_column(String(256), default="")
    created_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    license: Mapped["License | None"] = relationship(back_populates="validations")


# ── AI credits ledger (Phase 2b) ─────────────────────────────────────────────

class Credit(Base):
    """One row per License: current balance in paise. Source of truth."""
    __tablename__ = "credits"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    license_id:    Mapped[int]      = mapped_column(ForeignKey("licenses.id"),
                                                    unique=True, index=True)
    balance_paise: Mapped[int]      = mapped_column(Integer, default=0)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CreditTopup(Base):
    """Audit row for every credit-add operation (payment, admin grant, refund)."""
    __tablename__ = "credit_topups"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    license_id:    Mapped[int]      = mapped_column(ForeignKey("licenses.id"), index=True)
    amount_paise:  Mapped[int]      = mapped_column(Integer)        # positive=add, negative=refund
    ref:           Mapped[str]      = mapped_column(String(128), default="")  # razorpay payment id, admin user, etc.
    source:        Mapped[str]      = mapped_column(String(32), default="admin")  # 'admin' | 'razorpay' | 'demo'
    created_at:    Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIUsageLog(Base):
    """Per-call audit of every /ai/proxy hit. Used for billing review + abuse detection."""
    __tablename__ = "ai_usage_logs"

    id:             Mapped[int]      = mapped_column(primary_key=True)
    license_id:     Mapped[int]      = mapped_column(ForeignKey("licenses.id"), index=True)
    machine_id:     Mapped[str]      = mapped_column(String(64), index=True)
    feature:        Mapped[str]      = mapped_column(String(32))
    model:          Mapped[str]      = mapped_column(String(64), default="")
    tokens_in:      Mapped[int]      = mapped_column(Integer, default=0)
    tokens_out:     Mapped[int]      = mapped_column(Integer, default=0)
    paise_charged:  Mapped[int]      = mapped_column(Integer, default=0)
    success:        Mapped[bool]     = mapped_column(Boolean, default=True)
    error:          Mapped[str]      = mapped_column(String(256), default="")
    created_at:     Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
