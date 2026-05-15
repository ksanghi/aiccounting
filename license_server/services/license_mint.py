"""
Shared license-key minting service.

Used by:
  - admin CLI (license_server.admin) — when a human creates a key
  - Razorpay webhook handler — when an automated payment is captured

The mint logic was originally inlined in admin.py; extracting it here so
both callers share the same uniqueness-retry loop, plan defaults, and
audit-log behavior.

Both callers commit their own DB sessions; this function just adds the
License row and (optionally) the Credit row to the session — caller
commits.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from license_server.keys import generate_key
from license_server.models import License, Credit
from license_server.plans import (
    PLANS, PLAN_LIMITS, PLAN_USER_LIMITS, PLAN_SEATS, VALID_PRODUCTS,
)


class MintError(Exception):
    pass


def mint_license(
    db:            Session,
    plan:          str,
    customer_email: str,
    expires_at:    date,
    product:       str = "accgenie",
    company_name:  str = "",
    txn_limit:     Optional[int] = None,
    user_limit:    Optional[int] = None,
    seats_allowed: Optional[int] = None,
    notes:         str = "",
    initial_credits_paise: int = 0,
) -> License:
    """
    Mints a new license. Returns the License row (already added to the
    session, not yet committed).

    Raises MintError on bad inputs. Caller commits.

    `product`: 'accgenie' (default for back-compat) or 'rwagenie'.
    Validates against the server's VALID_PRODUCTS set. The product
    decides which feature bundle the desktop client gets on validate
    (see plans.features_for()).

    `initial_credits_paise`: optional starting wallet balance. If >0, a
    Credit row is created alongside the license (typical use: Razorpay
    pays "PRO + ₹500 AI credits" → license is PRO, balance is 50000 paise).
    """
    plan = (plan or "").upper()
    product = (product or "accgenie").lower()
    if plan not in PLANS:
        raise MintError(f"Unknown plan: {plan}")
    if product not in VALID_PRODUCTS:
        raise MintError(f"Unknown product: {product}")
    if expires_at < date.today():
        raise MintError("Expiry is in the past")
    if not customer_email:
        raise MintError("customer_email required")

    # Uniqueness retry — generate_key uses 32-char alphabet × 12 chars so
    # collisions are astronomically rare, but be defensive.
    key = None
    for _ in range(10):
        candidate = generate_key()
        if not db.scalar(select(License).where(License.license_key == candidate)):
            key = candidate
            break
    if key is None:
        raise MintError("Could not generate a unique license key after 10 tries")

    lic = License(
        license_key   = key,
        product       = product,
        plan          = plan,
        customer_email= customer_email,
        company_name  = company_name or "",
        expires_at    = expires_at,
        txn_limit     = txn_limit     if txn_limit     is not None else PLAN_LIMITS[plan],
        user_limit    = user_limit    if user_limit    is not None else PLAN_USER_LIMITS[plan],
        seats_allowed = seats_allowed if seats_allowed is not None else PLAN_SEATS.get(plan, 1),
        notes         = notes or "",
    )
    db.add(lic)
    db.flush()  # populate lic.id for the Credit foreign key

    if initial_credits_paise > 0:
        credit = Credit(license_id=lic.id, balance_paise=int(initial_credits_paise))
        db.add(credit)

    return lic


def default_expiry_for_plan(plan: str) -> date:
    """One-year-from-today expiry. DEMO is shorter (30 days). Adjust here
    if billing periods change."""
    if (plan or "").upper() == "DEMO":
        return date.today() + timedelta(days=30)
    return date.today() + timedelta(days=365)
