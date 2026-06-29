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
    # Which product this licence is for: 'accgenie' (accounting only) or
    # 'rwagenie' (RWA front + bundled accounting). New rows must set this
    # explicitly; existing rows are backfilled to 'accgenie' via the
    # additive migration in db.py.
    product:        Mapped[str]      = mapped_column(String(16),
                                                     default="accgenie",
                                                     server_default="accgenie",
                                                     index=True)
    plan:           Mapped[str]      = mapped_column(String(16))
    # 'annual' | 'monthly' — the term this license was sold on. Drives expiry
    # length + the upgrade balance math. Backfilled to 'annual' on existing
    # rows via db._apply_additive_columns().
    billing_period: Mapped[str]      = mapped_column(String(12), default="annual",
                                                     server_default="annual")
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


class EmailSuppression(Base):
    """Unsubscribe / suppression list. An email here is NEVER sent a blast."""
    __tablename__ = "email_suppressions"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    email:      Mapped[str]      = mapped_column(String(256), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class CaPartnerLead(Base):
    """A CA / bookkeeping firm that submitted the Founding-Partner interest
    form on ca-partners.html — a captured lead, not a licence holder."""
    __tablename__ = "ca_partner_leads"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    name:       Mapped[str]      = mapped_column(String(160), default="")
    firm:       Mapped[str]      = mapped_column(String(200), default="")
    email:      Mapped[str]      = mapped_column(String(256), index=True)
    phone:      Mapped[str]      = mapped_column(String(40), default="")
    city:       Mapped[str]      = mapped_column(String(120), default="")
    about:      Mapped[str]      = mapped_column(String(2000), default="")
    consent:    Mapped[bool]     = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class RwaPartnerLead(Base):
    """A prospective RWA HQ Media Network Partner who submitted the
    Founding-Partner form on rwahq/partners.html — a captured lead."""
    __tablename__ = "rwa_partner_leads"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    name:          Mapped[str]      = mapped_column(String(160), default="")
    company:       Mapped[str]      = mapped_column(String(200), default="")
    email:         Mapped[str]      = mapped_column(String(256), index=True)
    mobile:        Mapped[str]      = mapped_column(String(40), default="")
    city:          Mapped[str]      = mapped_column(String(120), default="")
    societies:     Mapped[int]      = mapped_column(Integer, default=0)
    relationships: Mapped[str]      = mapped_column(String(2000), default="")
    comments:      Mapped[str]      = mapped_column(String(2000), default="")
    consent:       Mapped[bool]     = mapped_column(Boolean, default=False)
    created_at:    Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmailBlast(Base):
    """One sent announcement — kept as a record of what went out."""
    __tablename__ = "email_blasts"

    id:           Mapped[int]      = mapped_column(primary_key=True)
    subject:      Mapped[str]      = mapped_column(String(256), default="")
    filters:      Mapped[str]      = mapped_column(String(256), default="")
    sent_count:   Mapped[int]      = mapped_column(Integer, default=0)
    failed_count: Mapped[int]      = mapped_column(Integer, default=0)
    created_at:   Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class EmailSend(Base):
    """One row per recipient of a blast — the actual sent list, auditable."""
    __tablename__ = "email_sends"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    blast_id:   Mapped[int]      = mapped_column(ForeignKey("email_blasts.id"), index=True)
    email:      Mapped[str]      = mapped_column(String(256), index=True)
    ok:         Mapped[bool]     = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Feedback(Base):
    """A bug report / feature request submitted from the desktop app's Feedback
    screen, POSTed to /api/v1/feedback so reports reach us directly instead of
    via a manual relay. `status` lets us triage (new → seen → done)."""
    __tablename__ = "feedback"

    id:          Mapped[int]      = mapped_column(primary_key=True)
    kind:        Mapped[str]      = mapped_column(String(40), default="Bug Report", index=True)
    subject:     Mapped[str]      = mapped_column(String(300), default="")
    description: Mapped[str]      = mapped_column(String(8000), default="")
    steps:       Mapped[str]      = mapped_column(String(4000), default="")
    product:     Mapped[str]      = mapped_column(String(40), default="", index=True)
    app_version: Mapped[str]      = mapped_column(String(40), default="")
    plan:        Mapped[str]      = mapped_column(String(40), default="")
    license_key: Mapped[str]      = mapped_column(String(80), default="")
    os:          Mapped[str]      = mapped_column(String(120), default="")
    status:      Mapped[str]      = mapped_column(String(20), default="new", index=True)
    created_at:  Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


class PageView(Base):
    """One row per marketing-page hit — our own lightweight analytics, so we
    can see traffic (and where it comes from) without a third-party tracker."""
    __tablename__ = "page_views"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    path:       Mapped[str]      = mapped_column(String(256), index=True)
    referrer:   Mapped[str]      = mapped_column(String(512), default="")
    ua:         Mapped[str]      = mapped_column(String(256), default="")
    host:       Mapped[str]      = mapped_column(String(128), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)


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
    # 'accgenie' / 'rwagenie' — distinguishes installs of each product so
    # the install_stats endpoint can break out per-product activity.
    product:         Mapped[str]      = mapped_column(String(16),
                                                      default="accgenie",
                                                      server_default="accgenie",
                                                      index=True)
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


# ── SMS Wallet (per-license pre-paid balance for OTP + broadcast SMS) ───────

class SMSWallet(Base):
    """
    RETIRED 2026-06-04 (RWAHQ_ARCHITECTURE.md §3 — ONE wallet). This separate
    balance is no longer read or written: there is a SINGLE prepaid wallet per
    license = the `credits` row, and ALL charges (AI usage, SMS, visitor-pass
    WA, decision WA) debit it. Table kept dormant to avoid a destructive drop;
    do NOT reintroduce it as a balance. `SMSWalletTxn` survives as the
    per-message audit ledger only.

    (Historical) Per-license pre-paid SMS balance in paise.

    Pricing model (decided 2026-05-17): cloud + web + mobile are free; the
    society monetises by paying ₹0.50 per SMS (OTP for resident login, or
    broadcast message). Society admins top up the wallet via Razorpay
    using the existing checkout flow. Desktop + rwagenie-web both call
    /api/v1/wallet/debit before sending an SMS — atomic deduct-and-record.

    One row per License (the natural account identifier — the desktop
    install carries its license_key, rwagenie-web stores license_key on
    its Society row).
    """
    __tablename__ = "sms_wallets"

    id:            Mapped[int]      = mapped_column(primary_key=True)
    license_id:    Mapped[int]      = mapped_column(ForeignKey("licenses.id"),
                                                    unique=True, index=True)
    balance_paise: Mapped[int]      = mapped_column(Integer, default=0)
    updated_at:    Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SMSWalletTxn(Base):
    """Audit row for every wallet movement — top-up, debit, refund, admin grant.

    `amount_paise` is signed: positive = credit (top-up / refund / grant),
    negative = debit (an SMS was sent).  `balance_after_paise` is the
    post-transaction snapshot so audits don't need to re-sum the ledger."""
    __tablename__ = "sms_wallet_txns"

    id:                  Mapped[int]      = mapped_column(primary_key=True)
    license_id:          Mapped[int]      = mapped_column(ForeignKey("licenses.id"), index=True)
    amount_paise:        Mapped[int]      = mapped_column(Integer)
    # 'topup' | 'sms_otp' | 'sms_broadcast' | 'refund' | 'admin_grant'
    kind:                Mapped[str]      = mapped_column(String(32), default="sms_broadcast")
    ref:                 Mapped[str]      = mapped_column(String(128), default="")  # rzp_pay_id, admin user, broadcast_id, etc.
    recipient_phone:     Mapped[str]      = mapped_column(String(32), default="")   # denormalised for SMS debits
    balance_after_paise: Mapped[int]      = mapped_column(Integer, default=0)
    machine_id:          Mapped[str]      = mapped_column(String(64), default="")   # caller fingerprint
    created_at:          Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ── Payment orders (Razorpay) ────────────────────────────────────────────────

class Order(Base):
    """
    One row per Razorpay order. Created when a customer initiates checkout
    on the marketing site, transitions to 'paid' when Razorpay's webhook
    confirms the payment.

    On 'paid', the webhook handler mints a License row and links it via
    license_id. Holding the order pre-mint (rather than minting on /create-
    order) prevents key proliferation when customers abandon checkout.
    """
    __tablename__ = "orders"

    id:                  Mapped[int]      = mapped_column(primary_key=True)
    razorpay_order_id:   Mapped[str]      = mapped_column(String(64), unique=True, index=True)
    razorpay_payment_id: Mapped[str]      = mapped_column(String(64), default="", index=True)

    # What this order is for: 'tier_purchase' = new license / renewal
    # (the original use-case, mints a License row on 'paid'), or
    # 'wallet_topup' = adds SMS-wallet balance to an existing license
    # (no mint; just credit + audit). The webhook handler branches on
    # this column. Defaults to 'tier_purchase' on legacy rows.
    kind:                Mapped[str]      = mapped_column(String(32),
                                                          default="tier_purchase",
                                                          server_default="tier_purchase",
                                                          index=True)
    # For wallet top-ups, links to the existing License that gets credited.
    # NULL for tier purchases (the License is minted post-payment).
    wallet_license_id:   Mapped[int | None] = mapped_column(
        ForeignKey("licenses.id"), nullable=True, index=True,
    )

    # Product the customer is buying: 'accgenie' or 'rwagenie'. The
    # webhook handler mints a License row with the same product.
    product:             Mapped[str]      = mapped_column(String(16),
                                                          default="accgenie",
                                                          server_default="accgenie",
                                                          index=True)
    plan:                Mapped[str]      = mapped_column(String(16))
    billing_period:      Mapped[str]      = mapped_column(String(12), default="annual",
                                                          server_default="annual")
    amount_paise:        Mapped[int]      = mapped_column(Integer)
    currency:            Mapped[str]      = mapped_column(String(8), default="INR")
    country_code:        Mapped[str]      = mapped_column(String(4), default="IN")

    customer_email:      Mapped[str]      = mapped_column(String(256), index=True)
    customer_name:       Mapped[str]      = mapped_column(String(256), default="")
    customer_phone:      Mapped[str]      = mapped_column(String(32), default="")
    company_name:        Mapped[str]      = mapped_column(String(256), default="")

    # created | paid | failed | refunded
    status:              Mapped[str]      = mapped_column(String(16), default="created", index=True)

    # Set on 'paid' — the license that was minted for this order. Nullable
    # because the order exists before the license does.
    license_id:          Mapped[int | None] = mapped_column(
        ForeignKey("licenses.id"), nullable=True, index=True
    )

    # Free-form audit trail. Webhook handler appends to it on each event.
    notes:               Mapped[str]      = mapped_column(String(2048), default="")

    created_at:          Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at:          Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class ChatLearned(Base):
    """Self-improving support-bot cache. Every AI answer the website chatbot
    produces is stored here: it serves as an instant, free cache for repeat
    questions AND a review queue. An operator promotes good ones (status
    'approved') or drops junk ('discarded') via /admin/chat-review; discarded
    questions are never re-cached. Promotion into the canonical docs/kb markdown
    is a separate manual+rebake step — this table is the live runtime cache."""
    __tablename__ = "chat_learned"

    id:         Mapped[int]      = mapped_column(primary_key=True)
    # Normalised question (lowercased, collapsed whitespace, stripped punctuation)
    # used as the cache key.
    qnorm:      Mapped[str]      = mapped_column(String(400), index=True)
    question:   Mapped[str]      = mapped_column(String(1000), default="")
    answer:     Mapped[str]      = mapped_column(String(4000), default="")
    hits:       Mapped[int]      = mapped_column(Integer, default=1)
    # pending | approved | discarded
    status:     Mapped[str]      = mapped_column(String(12), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow,
                                                 onupdate=datetime.utcnow)
