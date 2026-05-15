#!/usr/bin/env bash
#
# One-shot Fly.io deploy for the AccGenie license server.
# Sets every required secret then runs `fly deploy`.
#
# Usage:
#   1. Edit the values below (or export them in your shell first).
#   2. Run:  bash license_server/deploy_with_secrets.sh
#
# Secrets are kept on the Fly machine (encrypted at rest) — they never
# get baked into the deployed image and don't show up in `fly logs`.
#
# Safe to re-run: `fly secrets set` is idempotent for unchanged values
# and triggers a rolling restart only when a secret actually changes.
#
# Required secrets:
#   ADMIN_TOKEN              — bearer token guarding admin endpoints
#   ANTHROPIC_API_KEY        — for the AI proxy (optional; leave blank
#                              to disable that feature)
#   RAZORPAY_KEY_ID          — from Razorpay dashboard, Settings → API Keys
#   RAZORPAY_KEY_SECRET      — same dashboard
#   RAZORPAY_WEBHOOK_SECRET  — set when you register the webhook in
#                              Razorpay dashboard, Settings → Webhooks
#   SMTP_HOST / PORT / USER / PASSWORD — for emailing licence keys
#                              after payment. Gmail App Password is the
#                              easiest path (smtp.gmail.com, port 587).
#

set -euo pipefail

APP_NAME="${APP_NAME:-accgenie-license-in}"

# ── Fill these in ────────────────────────────────────────────────────────────
# Pull from env if set, else use the placeholders. Replace placeholders
# (or `export FOO=bar` before running) — the script refuses to deploy
# while any placeholder is unset.

ADMIN_TOKEN="${ADMIN_TOKEN:-CHANGE_ME_ADMIN_BEARER_TOKEN}"

ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"          # optional

# Razorpay (test mode keys to start with — switch to live once you're
# selling). Generate at https://dashboard.razorpay.com → Settings → API Keys.
RAZORPAY_KEY_ID="${RAZORPAY_KEY_ID:-CHANGE_ME_rzp_test_xxxxxxxx}"
RAZORPAY_KEY_SECRET="${RAZORPAY_KEY_SECRET:-CHANGE_ME_razorpay_secret}"

# Register webhook at https://dashboard.razorpay.com → Settings → Webhooks
#   URL    = https://license.accgenie.in/webhooks/razorpay
#   Events = payment.captured, payment.failed, order.paid
#   Secret = any string you choose; paste it here AND into the dashboard.
RAZORPAY_WEBHOOK_SECRET="${RAZORPAY_WEBHOOK_SECRET:-CHANGE_ME_webhook_secret}"

# SMTP: Gmail App Password path (recommended for first cut).
# https://myaccount.google.com/apppasswords → generate one named e.g.
# "AccGenie license server" → 16 chars, paste here.
SMTP_HOST="${SMTP_HOST:-smtp.gmail.com}"
SMTP_PORT="${SMTP_PORT:-587}"
SMTP_USER="${SMTP_USER:-info@ai-consultants.in}"
SMTP_PASSWORD="${SMTP_PASSWORD:-CHANGE_ME_gmail_app_password}"
SMTP_FROM="${SMTP_FROM:-info@ai-consultants.in}"
SMTP_FROM_NAME="${SMTP_FROM_NAME:-AccGenie}"
SMTP_USE_TLS="${SMTP_USE_TLS:-true}"

# ── Sanity ──────────────────────────────────────────────────────────────────

placeholder_unset=0
for var in ADMIN_TOKEN RAZORPAY_KEY_ID RAZORPAY_KEY_SECRET \
           RAZORPAY_WEBHOOK_SECRET SMTP_PASSWORD; do
  val="${!var}"
  if [[ "$val" == CHANGE_ME_* ]]; then
    echo "ERROR: $var still has its placeholder value." >&2
    placeholder_unset=1
  fi
done
if (( placeholder_unset )); then
  cat >&2 <<EOF

Edit the placeholders at the top of this script, or export the env
vars and re-run. Aborting before any 'fly' command runs so we don't
ship a broken deploy.
EOF
  exit 2
fi

# Require the fly CLI
if ! command -v fly >/dev/null 2>&1; then
  echo "ERROR: 'fly' CLI not found. Install from https://fly.io/docs/flyctl/install/" >&2
  exit 3
fi

echo
echo "==> Target app: $APP_NAME"
echo "==> Setting Fly secrets (will trigger a rolling restart only if values changed)"

# `fly secrets set` accepts multiple KEY=VALUE pairs in one call.
fly secrets set \
  ADMIN_TOKEN="$ADMIN_TOKEN" \
  ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
  RAZORPAY_KEY_ID="$RAZORPAY_KEY_ID" \
  RAZORPAY_KEY_SECRET="$RAZORPAY_KEY_SECRET" \
  RAZORPAY_WEBHOOK_SECRET="$RAZORPAY_WEBHOOK_SECRET" \
  SMTP_HOST="$SMTP_HOST" \
  SMTP_PORT="$SMTP_PORT" \
  SMTP_USER="$SMTP_USER" \
  SMTP_PASSWORD="$SMTP_PASSWORD" \
  SMTP_FROM="$SMTP_FROM" \
  SMTP_FROM_NAME="$SMTP_FROM_NAME" \
  SMTP_USE_TLS="$SMTP_USE_TLS" \
  --app "$APP_NAME"

echo
echo "==> Deploying server code"
fly deploy --app "$APP_NAME"

echo
echo "==> Quick health check"
sleep 3
curl -sf "https://license.accgenie.in/api/v1/health" || {
  echo
  echo "WARN: /api/v1/health didn't respond. Tail logs with:"
  echo "      fly logs --app $APP_NAME"
}

cat <<EOF

==> All set.

Next:
  1. Open https://dashboard.razorpay.com → Settings → Webhooks → confirm
     the webhook URL is reachable. Razorpay's 'Test' button will hit
     /webhooks/razorpay with a ping event.

  2. Smoke-test the live flow with a Test-Mode card:
     - Open marketing/checkout.html (host it on accgenie.in/pricing
       or wherever Aashray drops it).
     - Pick RWAGenie PRO → fill the form → use Razorpay's test card
       4111 1111 1111 1111 / 12/30 / 123.
     - License key should arrive in $SMTP_USER's inbox within a minute.

  3. Mint a real RWAGenie key manually for QA (no payment needed):
       fly ssh console --app $APP_NAME -C \\
         "python -m license_server.admin mint --product rwagenie \\
            --plan PRO --email info@ai-consultants.in \\
            --expires \$(date -d '+1 year' +%F)"

EOF
