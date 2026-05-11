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
