# Books HQ — cloud (web) app · STATUS

A US, multi-tenant, browser SaaS skin over the shared Aiccounting accounting
engine. Built 2026-06-13. **Lives inside the Aiccounting repo as `web/`** so it
imports the real engine (`core.*`) directly — one engine, two front-ends
(Qt desktop for India, this web app for the US). Nothing about the desktop app
changed.

- **Staging:** https://bookshq-web-staging.fly.dev  (Fly app `bookshq-web-staging`, region `sin`, volume `bookshq_web_data` at `/data`)
- **Stack:** FastAPI + Jinja2 + Tailwind(CDN) + HTMX(CDN); SQLAlchemy app DB (auth/tenancy); engine per-company SQLite on the volume.
- **Auth:** email + password (pbkdf2, stdlib); signed session cookie (itsdangerous), Secure + HttpOnly.
- **Country:** `country.set_active("US")` at startup → US sales tax, Schedule C, Form 1099 (no GST/TDS). Calendar-year FY (`fy_start=01-01`).
- **Tenancy:** app DB holds `users`, `accounts` (= tenant/licence), `company_refs` (slug → engine books file). Each company is its own SQLite at `/data/companies/<slug>.db`, exactly like the desktop's per-company model.

## Done (works end-to-end, smoke-tested + live-verified)
- Signup / login / logout.
- Company picker: create (seeds 25 ledgers + a default company user), list, enter.
- Dashboard: ledger count, YTD voucher count, YTD net profit, recent vouchers.
- Ledgers: list with live balances, add ledger, per-ledger statement.
- Post vouchers — all 8 types: Payment, Receipt, Contra, Sales, Purchase,
  Journal (multi-line), Debit Note, Credit Note. (Sales/Purchase honour a sales-tax %.)
- Day Book with date filter.
- Reports: Trial Balance, P&L, Balance Sheet, A/R aging, A/P aging,
  **Schedule C (US)**, **Form 1099 (US)**.

## Run locally
    python -m web._smoketest            # full end-to-end self-test (uses a temp dir)
    uvicorn web.main:app --reload       # dev server at http://127.0.0.1:8000

## Deploy (staging)
The repo-root `.dockerignore` excludes `core/` (for the license server), so this
app deploys from an ephemeral context that includes the engine:
    rm -rf _bookshq_build && mkdir _bookshq_build
    cp -r core web _bookshq_build/ ; cp web/Dockerfile web/requirements.txt web/fly.toml _bookshq_build/
    (cd _bookshq_build && fly deploy --remote-only --ha=false)
`SECRET_KEY` is already set as a Fly secret.

## Pending (parity + productionisation — NOT yet built)
- **Edit / cancel voucher** UI (engine supports it: `update_voucher`, `cancel_voucher`).
- **Bill-wise allocation** on receipts/payments (engine supports `draft.allocations`).
- **Bank reconciliation** (engine has the tables + `bank_book`/reconcile logic).
- **Document upload → Cloudflare R2** + the AI document inbox/reader (the BYOK/wallet AI model).
- **Cash-flow forecast** screen (engine has `cashflow_forecast`).
- **Receipts & Payments / Cash & Bank books** screens (engine methods exist).
- **Company settings / edit**, delete company, switch-company chip target.
- **Multi-user / roles** per account (engine `users.role` exists; app is owner-only today).
- **Billing / checkout** wiring (Razorpay International — gated on Razorpay enabling intl cards).
- **Password reset + email verification.**
- **Export** (CSV / Excel / PDF) — engine reports return data; no export buttons yet.
- **HTMX partials / search** — currently full-page form posts (HTMX is loaded, unused).

## Notes / decisions baked in
- Per-tenant SQLite on a Fly volume (mirrors desktop's per-company model) — not Postgres.
- One default "web" user seeded per company so `vouchers.created_by` (FK) resolves.
- Staging only; not wired to a domain, billing, or production data.
