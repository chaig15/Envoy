#!/usr/bin/env python3
"""Verify that stored tokens can be decrypted with the current encryption key."""

import asyncio
import sys
from pathlib import Path

# Add the project root to the path
sys.path.insert(0, str(Path(__file__).parent))

from envoy.config import get_settings
from envoy.db import Database
from envoy.encryption import decrypt_token
from cryptography.fernet import InvalidToken


async def verify_tokens():
    """Check all stored tokens in the database."""
    settings = get_settings()

    print("=" * 60)
    print("Token Verification Script")
    print("=" * 60)
    print(f"\nEncryption Key: {settings.encryption_key[:20]}...")
    print(
        f"Database URL: {settings.database_url.split('@')[-1] if '@' in settings.database_url else 'hidden'}"
    )
    print("\nConnecting to database...")

    try:
        await Database.connect()
        print("✓ Database connected\n")
    except Exception as e:
        print(f"✗ Failed to connect to database: {e}")
        return

    # Query all users with encrypted tokens
    rows = await Database.fetch(
        """
        SELECT telegram_id, resy_token_encrypted, updated_at
        FROM users
        WHERE resy_token_encrypted IS NOT NULL
        ORDER BY updated_at DESC
        """
    )

    if not rows:
        print("No users with encrypted tokens found in database.")
        await Database.disconnect()
        return

    print(f"Found {len(rows)} user(s) with encrypted tokens:\n")

    success_count = 0
    fail_count = 0

    for row in rows:
        telegram_id = row["telegram_id"]
        encrypted_token = row["resy_token_encrypted"]
        updated_at = row["updated_at"]

        print(f"User: {telegram_id}")
        print(f"  Updated: {updated_at}")
        print(f"  Encrypted token length: {len(encrypted_token)}")
        print(f"  Token preview: {encrypted_token[:30]}...")

        try:
            # Try to decrypt
            decrypted = decrypt_token(encrypted_token)
            print("  ✓ Decryption SUCCESS")
            print(f"  Decrypted token length: {len(decrypted)}")
            print(f"  Decrypted preview: {decrypted[:20]}...")
            success_count += 1
        except InvalidToken as e:
            print("  ✗ Decryption FAILED: InvalidToken")
            print(f"    Error: {e}")
            fail_count += 1
        except Exception as e:
            print(f"  ✗ Decryption FAILED: {type(e).__name__}")
            print(f"    Error: {e}")
            fail_count += 1

        print()

    print("=" * 60)
    print(f"Summary: {success_count} success, {fail_count} failed")
    print("=" * 60)

    await Database.disconnect()


if __name__ == "__main__":
    asyncio.run(verify_tokens())
