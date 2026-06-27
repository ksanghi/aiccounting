"""Tenancy + auth models. One User owns one or more Accounts (tenants);
each Account holds one or more CompanyRefs, each pointing at an engine
SQLite books file (by slug) and the companies.id row inside it.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import String, Integer, DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from web.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Account(Base):
    """A tenant — the billable business account (= a licence). All of a
    user's companies hang off their account."""
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    plan: Mapped[str] = mapped_column(String(40), default="FREE")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CompanyRef(Base):
    """Maps an account to one engine books file. `slug` is the SQLite
    filename (globally unique); `company_id` is the companies.id row inside
    that file."""
    __tablename__ = "company_refs"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    company_id: Mapped[int] = mapped_column(Integer)
    display_name: Mapped[str] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
