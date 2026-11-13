"""Enkripsi secret agent at-rest (HMAC key harus bisa dibaca server).

Disimpan terenkripsi Fernet dengan key turunan HKDF dari RANI_INGEST_PEPPER —
bukan plaintext, tapi tetap reversible supaya verifikasi HMAC bisa dihitung.
"""
from base64 import urlsafe_b64encode
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


@lru_cache
def _fernet(pepper: str) -> Fernet:
    key = urlsafe_b64encode(HKDF(algorithm=hashes.SHA256(), length=32,
                                 salt=b"rani-agent-secret", info=b"v1").derive(
        pepper.encode()))
    return Fernet(key)


def encrypt_secret(plain: str, pepper: str) -> str:
    return _fernet(pepper).encrypt(plain.encode()).decode()


def decrypt_secret(token: str, pepper: str) -> str:
    try:
        return _fernet(pepper).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("secret agent tidak bisa didekripsi (pepper berubah?)") from exc