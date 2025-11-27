#!/usr/bin/env python3
"""Diagnose token decryption issues."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from envoy.config import get_settings
from envoy.db import Database
from cryptography.fernet import Fernet, InvalidToken


async def diagnose():
    """Diagnose the token issue."""
    settings = get_settings()

    print("=" * 60)
    print("Token Diagnosis")
    print("=" * 60)

    await Database.connect()

    # Get the stored token
    row = await Database.fetchrow(
        "SELECT telegram_id, resy_token_encrypted, updated_at FROM users WHERE resy_token_encrypted IS NOT NULL LIMIT 1"
    )

    if not row:
        print("No encrypted token found in database.")
        await Database.disconnect()
        return

    encrypted_token = row["resy_token_encrypted"].strip()
    telegram_id = row["telegram_id"]
    updated_at = row["updated_at"]

    print(f"\nUser: {telegram_id}")
    print(f"Token updated: {updated_at}")
    print(f"Current encryption key: {settings.encryption_key[:30]}...")
    print("\nStored encrypted token:")
    print(f"  Length: {len(encrypted_token)}")
    print(f"  First 50 chars: {encrypted_token[:50]}")
    print(f"  Last 50 chars: {encrypted_token[-50:]}")

    # Check if it's valid Fernet format
    if not encrypted_token.startswith("gAAAAA"):
        print("\n✗ Token doesn't start with 'gAAAAA' - not a valid Fernet token!")
    else:
        print("\n✓ Token has valid Fernet format (starts with 'gAAAAA')")

    # Try to decrypt with current key
    print("\nAttempting decryption with current key...")
    try:
        fernet = Fernet(settings.encryption_key.encode())
        decrypted = fernet.decrypt(encrypted_token.encode()).decode()
        print("✓ SUCCESS! Token decrypted.")
        print(f"  Decrypted token: {decrypted[:30]}...")
    except InvalidToken:
        print("✗ FAILED: Token was encrypted with a DIFFERENT key")
        print("\n  This means:")
        print("  - The token was encrypted with a different ENCRYPTION_KEY")
        print("  - The current key cannot decrypt it")
        print("  - Solution: Re-login with /login to get a fresh token")
    except Exception as e:
        print(f"✗ FAILED: {type(e).__name__}: {e}")

    # Check for common issues
    print("\n" + "=" * 60)
    print("Recommendations:")
    print("=" * 60)
    print("1. If decryption failed, the token was encrypted with a different key")
    print("2. Run /login in Telegram to get a fresh token encrypted with current key")
    print("3. The old token will be replaced automatically")

    await Database.disconnect()


if __name__ == "__main__":
    asyncio.run(diagnose())
