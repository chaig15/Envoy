"""Encryption utilities for storing sensitive data."""

import logging

from cryptography.fernet import Fernet

from envoy.config import get_settings

logger = logging.getLogger(__name__)


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
    # Ensure we have a string and strip any whitespace
    if not isinstance(encrypted, str):
        raise ValueError(f"Expected string, got {type(encrypted)}")

    encrypted = encrypted.strip()
    if not encrypted:
        raise ValueError("Encrypted token is empty")

    f = get_fernet()
    try:
        return f.decrypt(encrypted.encode()).decode()
    except Exception:
        logger.error(
            f"Decryption failed. Token length: {len(encrypted)}, starts with: {encrypted[:20] if len(encrypted) > 20 else encrypted}"
        )
        raise
