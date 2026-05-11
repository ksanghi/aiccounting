"""License key generation and format validation."""
import re
import secrets

# Alphabet excludes I, O, 0, 1 to avoid visual confusion.
ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

KEY_RE = re.compile(r"^ACCG-[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")


def generate_key() -> str:
    """Returns a fresh ACCG-XXXX-XXXX-XXXX key. Caller must check uniqueness."""
    parts = [
        "".join(secrets.choice(ALPHABET) for _ in range(4))
        for _ in range(3)
    ]
    return f"ACCG-{parts[0]}-{parts[1]}-{parts[2]}"


def is_valid_format(key: str) -> bool:
    return bool(KEY_RE.match(key or ""))
