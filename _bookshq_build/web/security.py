"""Password hashing (stdlib pbkdf2) + signed session tokens (itsdangerous)."""
from __future__ import annotations

import hashlib
import hmac
import os

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from web.config import settings

_serializer = URLSafeTimedSerializer(settings.secret_key, salt="bookshq-session")

_PBKDF2_ITERS = 200_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _PBKDF2_ITERS)
    return f"pbkdf2${_PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _algo, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def make_session_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id})


def read_session_token(token: str):
    if not token:
        return None
    try:
        return _serializer.loads(
            token, max_age=settings.session_max_age_days * 86400)
    except (BadSignature, SignatureExpired):
        return None
