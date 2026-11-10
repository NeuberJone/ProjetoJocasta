"""Versioned local DEV password hashes; production identity hashes are unrelated."""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets

ITERATIONS = 600_000
_MIN_ITERATIONS = 100_000
_MAX_ITERATIONS = 2_000_000
_LEGACY = re.compile(r"[a-fA-F0-9]{40}\Z")
_ENCODED = re.compile(r"pbkdf2_sha256\$([0-9]{1,7})\$([a-fA-F0-9]{32})\$([a-fA-F0-9]{64})\Z")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS, dklen=32)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def is_legacy_hash(encoded: str) -> bool:
    return isinstance(encoded, str) and _LEGACY.fullmatch(encoded) is not None


def verify_password(encoded: str, password: str) -> bool:
    if not isinstance(encoded, str) or not isinstance(password, str):
        return False
    if is_legacy_hash(encoded):
        actual = hashlib.sha1(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(actual, encoded.lower())
    match = _ENCODED.fullmatch(encoded)
    if not match:
        return False
    iterations = int(match[1])
    if not _MIN_ITERATIONS <= iterations <= _MAX_ITERATIONS:
        return False
    salt = bytes.fromhex(match[2])
    expected = bytes.fromhex(match[3])
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)
    return hmac.compare_digest(actual, expected)
