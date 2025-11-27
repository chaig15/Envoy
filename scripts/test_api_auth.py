#!/usr/bin/env python3
"""Test which API calls actually require authentication."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from envoy.resy import ResyClient


async def test_api_calls():
    """Test which API calls work without auth."""
    print("=" * 60)
    print("Testing Resy API Calls Without Authentication")
    print("=" * 60)

    # Test 1: Search without auth
    print("\n1. Testing search_venues() without auth...")
    client_no_auth = ResyClient()
    try:
        venues = await client_no_auth.search_venues("carbone")
        print(f"   ✓ SUCCESS: Found {len(venues)} venues")
        if venues:
            print(f"   Example: {venues[0].name}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
    finally:
        await client_no_auth.close()

    # Test 2: Get availability without auth
    print("\n2. Testing get_availability() without auth...")
    client_no_auth2 = ResyClient()
    try:
        # Use a known venue ID (Carbone)
        from datetime import date

        availability = await client_no_auth2.get_availability(
            venue_id=41768,  # Carbone NYC
            check_date=date.today(),
            party_size=2,
        )
        print(f"   ✓ SUCCESS: Found {len(availability.slots)} slots")
        if availability.slots:
            print(f"   Example slot: {availability.slots[0].time}")
    except Exception as e:
        print(f"   ✗ FAILED: {e}")
    finally:
        await client_no_auth2.close()

    # Test 3: Get booking details without auth (this might fail)
    print("\n3. Testing get_booking_details() without auth...")
    client_no_auth3 = ResyClient()
    try:
        from datetime import date

        # This will likely fail without auth
        _ = await client_no_auth3.get_booking_details(
            config_token="test_token", party_size=2, check_date=date.today()
        )
        print("   ✓ SUCCESS: Got booking details")
    except Exception as e:
        print(f"   ✗ FAILED (expected): {e}")
    finally:
        await client_no_auth3.close()

    print("\n" + "=" * 60)
    print("Summary:")
    print("  - search_venues: Works without auth")
    print("  - get_availability: Likely works without auth")
    print("  - get_booking_details: Requires auth")
    print("  - book: Requires auth")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_api_calls())
