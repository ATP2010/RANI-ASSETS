"""Primitif keamanan: bcrypt password, token sesi, HMAC verify."""
import hashlib
import hmac
import secrets

import bcrypt

# Hash dummy untuk menyamakan waktu respons saat user tidak ditemukan.
_DUMMY = bcrypt.hashpw(b"rani-timing-equalizer", bcrypt.gensalt(rounds=12))


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str | None) -> bool:
    if not hashed:
        bcrypt.checkpw(plain.encode(), _DUMMY)
        return False
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except ValueError:
        return False


def new_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def sha256_hex(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def hash_agent_secret(secret: str, pepper: str) -> str:
    return sha256_hex(f"{pepper}:{secret}")


def hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def constant_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


ROLE_RANK = {"reader": 10, "operator": 20, "admin": 30}


def role_allows(role: str, minimum: str) -> bool:
    return ROLE_RANK.get(role, 0) >= ROLE_RANK.get(minimum, 999)