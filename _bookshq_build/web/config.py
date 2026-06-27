"""Runtime settings for the Books HQ cloud (web) app.

This is a *front-end* on the shared Aiccounting engine — it owns only the
multi-tenant auth/registry DB (users, accounts, company refs). The actual
books live in per-company SQLite files written by the engine into
ACCGENIE_DATA_DIR/companies/<slug>.db (a Fly volume in production).
"""
from __future__ import annotations

import os


class Settings:
    def __init__(self) -> None:
        # Signing key for session cookies. MUST be set in production
        # (`fly secrets set SECRET_KEY=...`). Dev gets a stable insecure default.
        self.secret_key = os.environ.get("SECRET_KEY", "dev-insecure-key-change-me")

        # App (tenancy/auth) DB — separate from the per-company books.
        self.app_db_url = os.environ.get(
            "APP_DATABASE_URL", "sqlite:///./bookshq_app.db")

        self.session_cookie = "bookshq_sid"
        self.session_max_age_days = 30

        # Books HQ is the US product → the engine runs the US country profile.
        self.country = os.environ.get("BOOKSHQ_COUNTRY", "US")

        # US businesses default to a calendar-year fiscal year.
        self.fy_start = "01-01"


settings = Settings()
