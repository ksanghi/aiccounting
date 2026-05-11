# AccGenie License Server

FastAPI service for issuing and validating AccGenie license keys.

The desktop app (`core/license_manager.py`) calls `POST /api/v1/license/validate`
with `{license_key, machine_id, app_version}` and gets back the plan, features,
limits, and expiry. Keys are minted via the admin CLI (or the protected `/admin/*`
HTTP endpoints) and bound to up to N machines on first activation.

## Layout

```
license_server/
├── main.py            FastAPI app + endpoints
├── admin.py           CLI: mint/list/show/revoke/extend/unbind
├── models.py          License, MachineBinding, ValidationLog
├── plans.py           PLAN_FEATURES / PLAN_LIMITS — source of truth
├── keys.py            ACCG-XXXX-XXXX-XXXX format + generator
├── db.py              SQLAlchemy engine + session
├── config.py          Pydantic settings (env / .env)
├── requirements.txt
├── Procfile           Heroku/Railway/Render
├── Dockerfile         Fly.io / any container host
├── fly.toml           Fly.io launch config
├── render.yaml        Render.com Blueprint
└── .env.example
```

## Run locally

```powershell
cd license_server
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# edit .env — set ADMIN_TOKEN to a long random string

# from the repo root (one dir up):
cd ..
uvicorn license_server.main:app --reload --port 8000
```

Health check: <http://127.0.0.1:8000/api/v1/health>
OpenAPI docs: <http://127.0.0.1:8000/docs>

## Mint a key (admin CLI, talks to the DB directly)

```powershell
# from the repo root
python -m license_server.admin mint `
    --plan PRO `
    --email customer@example.com `
    --company "Foo Industries" `
    --expires 2027-05-10
```

Output prints the new `ACCG-XXXX-XXXX-XXXX` key — email it to the customer.

Other commands:

```powershell
python -m license_server.admin list                          # all keys
python -m license_server.admin list --plan PRO               # filter
python -m license_server.admin show ACCG-AAAA-BBBB-CCCC      # detail + machines + recent validations
python -m license_server.admin revoke ACCG-AAAA-BBBB-CCCC
python -m license_server.admin extend ACCG-AAAA-BBBB-CCCC --to 2028-05-10
python -m license_server.admin unbind ACCG-AAAA-BBBB-CCCC    # all machines (re-bind on next validate)
python -m license_server.admin unbind ACCG-AAAA-BBBB-CCCC --machine 1a2b3c4d5e6f
```

## Test against the desktop app locally

The client's `SERVER_URL` is hardcoded to `https://license.accgenie.in/api/v1`.
For local testing, set the environment variable before launching the desktop app:

```powershell
$env:ACCGENIE_LICENSE_SERVER = "http://127.0.0.1:8000/api/v1"
python main.py
```

> The desktop client doesn't currently read this env var — flip
> `core/license_manager.py:SERVER_URL` to the local URL temporarily, or add a
> small `os.environ.get("ACCGENIE_LICENSE_SERVER", SERVER_URL)` override.

Then in the License page, paste the minted key and click Activate.

## Deploy

### Fly.io (recommended for India users — Mumbai region)

```bash
fly launch --copy-config --no-deploy
fly secrets set ADMIN_TOKEN=$(python -c "import secrets;print(secrets.token_urlsafe(32))")
fly volumes create license_data --size 1 --region bom
fly deploy
fly certs add license.accgenie.in
# add the CNAME to license.accgenie.in pointing at <app>.fly.dev
```

### Render.com

Push the repo, click "New Blueprint" pointing at `license_server/render.yaml`.
Render auto-generates `ADMIN_TOKEN`; copy it from the dashboard. Add the custom
domain `license.accgenie.in` in Render → Settings → Custom Domains and follow
the CNAME instructions.

### Railway

Railway picks up `Procfile` automatically. Set `ADMIN_TOKEN` and
`MAX_MACHINES_PER_KEY` as env vars in the dashboard. Mount a volume at `/data`
and set `DATABASE_URL=sqlite:////data/licenses.db`. Add the custom domain
`license.accgenie.in`.

## DNS

Once the host gives you a CNAME target, in your DNS provider:

```
license.accgenie.in.   CNAME   <provider-target>.fly.dev    (or render / railway)
```

TLS is auto-provisioned by all three platforms via Let's Encrypt.

## API contract

### `POST /api/v1/license/validate`  (public)

Request:
```json
{
  "license_key": "ACCG-AAAA-BBBB-CCCC",
  "machine_id":  "9f1a2b3c4d5e6f70",
  "app_version": "1.0.0"
}
```

Response (success):
```json
{
  "valid": true,
  "plan": "PRO",
  "features": ["vouchers", "daybook", "..."],
  "txn_limit": 50000,
  "txn_used": 0,
  "user_limit": 5,
  "expires_at": "2027-05-10",
  "company_name": "Foo Industries"
}
```

Response (failure):
```json
{ "valid": false, "error": "License has expired." }
```

### Admin endpoints

All `/admin/*` routes require `Authorization: Bearer <ADMIN_TOKEN>`.

- `POST /admin/keys` — mint
- `GET  /admin/keys` — list (filter by `?plan=PRO&revoked=false`)
- `GET  /admin/keys/{key}` — detail
- `POST /admin/keys/{key}/revoke`
- `POST /admin/keys/{key}/extend` — body `{"new_expires_at": "..."}`

Browse interactively at `/docs`.

## Anonymous install heartbeat

Every desktop launch fires `POST /api/v1/install/heartbeat` on a background
thread (fire-and-forget, 3s timeout, never blocks UI). Payload:

```json
{
  "install_id":  "<uuid generated on first launch, persisted locally>",
  "machine_id":  "<hash of hostname+arch>",
  "app_version": "1.0.0",
  "plan":        "FREE",
  "license_key": "ACCG-XXXX-XXXX-XXXX",
  "os_name":     "windows"
}
```

No PII (no email, no IP stored, no hostname in the clear). Lets you count
total installs across all tiers — including FREE users who never activate.

Stats:

```bash
curl -H "Authorization: Bearer $ADMIN_TOKEN" \
     https://license.accgenie.in/admin/installs/stats
# {"total_installs": 247, "by_plan": {"FREE": 220, "PRO": 22, "PREMIUM": 5},
#  "new_last_7d": 18, "new_last_30d": 64, "active_last_7d": 142}
```

## What's NOT in v1

- **Payment integration.** No Razorpay webhook → auto-mint. Mint manually after
  payment confirmation.
- **Email delivery.** The CLI prints the key; you email it yourself.
- **Usage sync.** `txn_used` and number-of-companies are tracked client-side
  only. Add a `/api/v1/usage/report` endpoint when you want per-customer
  engagement data.
- **Postgres.** SQLite is fine for thousands of keys. Swap by changing
  `DATABASE_URL` — schema is portable.
- **Rate limiting.** Add nginx/Cloudflare in front for production.
