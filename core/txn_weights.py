"""
Transaction-counter weights per transaction type.

Every code path that creates / edits / cancels a billable unit calls
`LicenseManager.record_transaction_posted(kind)`; the increment value
comes from this table, NOT from a fixed +1.

GLOBAL RULE (see memory `feedback-txn-weights-programmable`):
- Every transaction is monitored — no bypasses.
- Weight of the charge per type lives in the pricing table,
  baked into each release. The release version is the snapshot —
  no DB history, no per-voucher stamping. txn_used carries forward
  across upgrades, so past transactions stay counted at the weights
  of the version that posted them.

Today this module hardcodes the weights. The follow-up task is to
generate it from `config/pricing.xlsx` in the bake step (parallel to
how plan limits are baked into `plans.py`). When that lands, the
constants below become the auto-generated output, NOT the source of
truth.

Defaults rationale (v0.1.x):
- single_voucher / multi_party / bank_reco / ledger_reco / ai_voucher
  = 1 each. Every business transaction counts the same as a single
  manually-entered voucher until the user tunes the pricing table.
- edit = 0 — editing a posted voucher doesn't recharge the customer.
- cancel = 0 — "you used the slot when you posted" policy. No refund.
  (To refund cancellations, set this to -1 in pricing.xlsx; the
  counter logic supports negative deltas.)
"""
from __future__ import annotations


# Default weight applied to any kind not explicitly listed. Set to 1
# so that adding a new entry-point without updating this table errs
# on the side of "count it" rather than silently dropping it on the
# floor — matches the "every transaction is monitored" rule.
DEFAULT_WEIGHT = 1


# Canonical kinds. Keep the keys stable — call sites pass them by
# string and a typo here would silently fall back to DEFAULT_WEIGHT.
TXN_WEIGHTS: dict[str, int] = {
    "single_voucher": 1,   # Sales / Purchase / Journal / Contra / DN / CN
    "multi_party":    1,   # Multi-party Payment / Receipt dialog
    "bank_reco":      1,   # Bank-reconciliation auto-posted vouchers
    "ledger_reco":    1,   # Ledger-reconciliation auto-posted vouchers
    "ai_voucher":     1,   # AI doc-reader extracted vouchers (source=AI_DOC)
    "edit":           0,   # Editing an existing voucher (no recharge)
    "cancel":         0,   # Cancellation (no refund — see module docstring)
}


# All supported kinds — exported so call sites can use the constant
# instead of a bare string. Lets a typo at the call site fail fast in
# linters / type checks instead of silently using DEFAULT_WEIGHT.
class Kind:
    SINGLE_VOUCHER = "single_voucher"
    MULTI_PARTY    = "multi_party"
    BANK_RECO      = "bank_reco"
    LEDGER_RECO    = "ledger_reco"
    AI_VOUCHER     = "ai_voucher"
    EDIT           = "edit"
    CANCEL         = "cancel"


def weight_for(kind: str) -> int:
    """Return the per-type weight for a transaction kind.

    Unknown kinds fall back to DEFAULT_WEIGHT (currently 1) — see the
    rationale in the module docstring. Pass an empty / None kind and
    you also get DEFAULT_WEIGHT — a misconfigured call site is
    treated as a single-transaction post, not a free post.
    """
    if not kind:
        return DEFAULT_WEIGHT
    return TXN_WEIGHTS.get(kind, DEFAULT_WEIGHT)
