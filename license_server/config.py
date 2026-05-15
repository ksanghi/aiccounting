"""Settings — read from environment / .env file."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    database_url: str = "sqlite:///./licenses.db"
    admin_token: str = "change-me"
    max_machines_per_key: int = 3
    server_version: str = "1.0.0"

    # ── AI proxy (Phase 2b) ───────────────────────────────────────────────────
    # Server-held Anthropic key. Required to enable the /api/v1/ai/proxy
    # endpoint. If unset, the endpoint returns 503 and clients fall back to
    # BYOK gracefully.
    anthropic_api_key: str = ""
    anthropic_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"

    # Per-token paise rates AFTER our markup (default ~3× over Anthropic
    # raw, in INR, at ~85 INR/USD). Adjustable via .env without code change.
    #   Claude Sonnet 4: $3/M input  → 25500 paise/M raw → 76500 paise/M w/3x
    #   Claude Sonnet 4: $15/M out   → 127500 paise/M raw → 382500 paise/M w/3x
    # Stored as paise per 1k tokens so the math in the proxy is integer-safe.
    ai_input_paise_per_1k:  float = 76.5     # ≈ ₹0.0765 per input token
    ai_output_paise_per_1k: float = 382.5    # ≈ ₹0.3825 per output token

    # Minimum balance required to start a call (in paise). Prevents users
    # from starting a request they can't finish — fail fast before
    # forwarding to Anthropic.
    ai_min_balance_paise: int = 100   # ₹1.00

    # ── Razorpay (payment gateway) ───────────────────────────────────────────
    # Leave blank to disable. /api/v1/checkout/create-order returns 503 when
    # razorpay_key_id is unset; /webhooks/razorpay returns 503 when
    # razorpay_webhook_secret is unset. Same pattern as anthropic_api_key.
    #
    # Get these from https://dashboard.razorpay.com/app/keys (use Test mode
    # keys for dev; switch to Live mode for production). The webhook secret
    # is set when you register the webhook in the dashboard (Settings →
    # Webhooks).
    razorpay_key_id:         str = ""
    razorpay_key_secret:     str = ""
    razorpay_webhook_secret: str = ""

    # If true, the create-order endpoint trusts the price the client sends
    # (only useful for early local testing). Production should ALWAYS leave
    # this false — server looks up the price from the baked pricing.xlsx.
    razorpay_trust_client_price: bool = False

    # ── Email delivery (license key + receipt) ───────────────────────────────
    # smtplib-based. Tested with Gmail App Passwords and SendGrid SMTP. Leave
    # blank to disable — paid orders will still mint a key but won't notify
    # the customer; you'd have to look it up in the orders table by email.
    smtp_host:     str = ""              # smtp.gmail.com or smtp.sendgrid.net
    smtp_port:     int = 587             # 587 (STARTTLS) or 465 (SSL)
    smtp_user:     str = ""
    smtp_password: str = ""
    smtp_from:     str = "noreply@accgenie.in"
    smtp_from_name: str = "AccGenie"
    smtp_use_tls:  bool = True


settings = Settings()
