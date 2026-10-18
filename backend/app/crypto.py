"""Encryption for secrets stored in the database (a user's own AI key). Key: FIELD_ENCRYPTION_KEY (Fernet, 32
url-safe base64 bytes; generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`).
Encrypted values are never returned by the API or logged."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class CryptoUnavailable(RuntimeError):
    pass


def _fernet() -> Fernet:
    from app.config import get_settings

    key = get_settings().field_encryption_key
    if not key:
        raise CryptoUnavailable("FIELD_ENCRYPTION_KEY is not set: storing your own key is disabled on this server.")
    return Fernet(key.encode())


def encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise CryptoUnavailable("stored key cannot be decrypted (FIELD_ENCRYPTION_KEY changed?)") from None
