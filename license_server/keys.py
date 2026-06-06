"""License key generation and format validation.

The key prefix is product-specific so a customer's key visibly matches
what they bought (RWAH- for RWA HQ, etc.) instead of always reading
"ACCG" (the old AccGenie brand). Legacy ACCG- keys stay valid forever —
the validator accepts every known prefix.
"""
import re
import secrets

# Alphabet excludes I, O, 0, 1 to avoid visual confusion.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# Internal product code → 4-char key prefix. ACCG is legacy AccGenie and
# the default; new products get their own.
_PREFIX = {
    "accgenie": "ACCG",
    "rwagenie": "RWAH",
    "tradehq":  "TRHQ",
}

# Accept any known prefix — existing ACCG- keys keep validating, new
# product-specific keys are accepted too.
KEY_RE = re.compile(r"^(ACCG|RWAH|TRHQ)-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")


def generate_key(product: str = "accgenie") -> str:
    """Returns a fresh PREFIX-XXXX-XXXX-XXXX key for the product. Caller
    must check uniqueness."""
    prefix = _PREFIX.get((product or "accgenie").lower(), "ACCG")
    parts = [
        "".join(secrets.choice(ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return f"{prefix}-{parts[0]}-{parts[1]}-{parts[2]}"


def is_valid_format(key: str) -> bool:
    return bool(KEY_RE.match(key or ""))
