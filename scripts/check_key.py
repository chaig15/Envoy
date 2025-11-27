#!/usr/bin/env python3
"""Check if encryption key is valid and test encryption/decryption."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from envoy.config import get_settings
from envoy.encryption import encrypt_token, decrypt_token
from cryptography.fernet import Fernet

settings = get_settings()
key = settings.encryption_key

print("=" * 60)
print("Encryption Key Verification")
print("=" * 60)
print(f"\nKey from .env: {key}")
print(f"Key length: {len(key)}")

# Check if key is valid Fernet key
try:
    fernet = Fernet(key.encode())
    print("✓ Key is valid Fernet format")
except Exception as e:
    print(f"✗ Key is INVALID: {e}")
    sys.exit(1)

# Test encryption/decryption
test_token = "test_token_12345"
print(f"\nTesting with token: {test_token}")

try:
    encrypted = encrypt_token(test_token)
    print("✓ Encryption successful")
    print(f"  Encrypted: {encrypted[:50]}...")

    decrypted = decrypt_token(encrypted)
    print("✓ Decryption successful")
    print(f"  Decrypted: {decrypted}")

    if decrypted == test_token:
        print("✓ Round-trip test PASSED")
    else:
        print(f"✗ Round-trip test FAILED: {decrypted} != {test_token}")
except Exception as e:
    print(f"✗ Test failed: {e}")
    import traceback

    traceback.print_exc()

print("\n" + "=" * 60)
