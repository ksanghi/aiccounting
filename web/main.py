"""Books HQ — cloud (web) front-end on the shared Aiccounting engine.

A US, multi-tenant, browser SaaS skin over the same accounting engine the
desktop app uses. Server-rendered (Jinja + HTMX + Tailwind), email+password
auth, per-company SQLite books on a Fly volume.
"""
from __future__ import annotations

import os
import os.path

# The engine resolves writable data (per-company books) under this dir.
# Fly sets it to the mounted volume (/data); dev falls back to ./data.
os.environ.setdefault("ACCGENIE_DATA_DIR", os.path.abspath("./data"))

# Books HQ is the US product — activate the US country profile (sales tax,
# Schedule C, Form 1099; no GST/TDS). Must happen before any voucher posts.
from core import country  # noqa: E402
country.set_active("US")

from fastapi import FastAPI  # noqa: E402
from fastapi.responses import PlainTextResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

from web.db import init_schema  # noqa: E402
from web.routes import auth, companies, dashboard, ledgers, vouchers, reports  # noqa: E402

app = FastAPI(title="Books HQ", version="0.1.0", docs_url=None, redoc_url=None)

for module in (auth, companies, dashboard, ledgers, vouchers, reports):
    app.include_router(module.router)

if os.path.isdir("web/static"):
    app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.on_event("startup")
def _startup() -> None:
    init_schema()


@app.get("/healthz", response_class=PlainTextResponse)
def healthz() -> str:
    return "ok"
