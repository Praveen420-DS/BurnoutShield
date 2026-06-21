"""
auth_utils.py — shared password helpers (no external dependencies needed)
"""
import hashlib
import secrets
import string

_ALPHABET = (string.ascii_letters + string.digits)
for _bad in "lIO0":
    _ALPHABET = _ALPHABET.replace(_bad, "")


def generate_password(length: int = 10) -> str:
    """Cryptographically random, human-typeable password (no ambiguous chars)."""
    return "".join(secrets.choice(_ALPHABET) for _ in range(length))


def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    """Return (salt_hex, hash_hex). Generates a new salt if none is given."""
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac(
        "sha256", password.encode(), bytes.fromhex(salt), 100_000
    ).hex()
    return salt, pwd_hash


def verify_password(password: str, salt: str, expected_hash: str) -> bool:
    _, computed = hash_password(password, salt)
    return secrets.compare_digest(computed, expected_hash)
