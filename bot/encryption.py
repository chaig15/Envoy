"""Encryption utilities for storing sensitive data."""

from cryptography.fernet import Fernet

from bot.config import get_settings


def get_fernet() -> Fernet:
    """Get Fernet instance for encryption/decryption."""
    settings = get_settings()
    return Fernet(settings.encryption_key.encode())


def encrypt_token(token: str) -> str:
    """Encrypt a token for storage."""
    f = get_fernet()
    return f.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt a stored token."""
    f = get_fernet()
    return f.decrypt(encrypted.encode()).decode()

