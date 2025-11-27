#!/usr/bin/env python3
"""
CLI tool for testing snipe execution without waiting for release time.

This script bypasses the scheduler and directly executes snipe logic,
optionally using a mock Resy client to avoid real API calls.

Usage:
    # Test an existing snipe with mock client (no real booking)
    python scripts/test_snipe.py --snipe-id 123

    # Test with specific mock slots
    python scripts/test_snipe.py --snipe-id 123 --mock-slots "19:00,19:30,20:00"

    # Test with no availability (timeout scenario)
    python scripts/test_snipe.py --snipe-id 123 --mock-slots ""

    # Test with real API (dangerous - will actually book!)
    python scripts/test_snipe.py --snipe-id 123 --live

    # List pending snipes
    python scripts/test_snipe.py --list
"""

import argparse
import asyncio
import logging
import sys
from datetime import datetime, time
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from envoy.db.connection import Database
from envoy.db.models import Snipe
from envoy.db.queries import SnipeQueries
from envoy.resy.mock_client import MockResyClient, create_mock_slots
from envoy.resy.models import TimeSlot


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_snipe")


class MockBot:
    """Mock Telegram bot that logs instead of sending messages."""

    async def send_message(self, chat_id: int, text: str, **kwargs):
        logger.info(f"[TELEGRAM → {chat_id}]\n{text}\n")


class TestableSniper:
    """
    Sniper with injectable dependencies for testing.

    Runs the same logic as the real Sniper but allows:
    - Mock Resy client injection
    - Immediate execution (no waiting for release time)
    - Shorter timeouts for faster testing
    """

    def __init__(
        self,
        mock_client: Optional[MockResyClient] = None,
        skip_wait: bool = True,
        timeout_seconds: float = 5.0,
    ):
        self.mock_client = mock_client
        self.skip_wait = skip_wait
        self.timeout_seconds = timeout_seconds
        self.bot = MockBot()

    async def execute_snipe(self, snipe: Snipe) -> dict:
        """
        Execute a snipe and return results.

        Returns:
            dict with keys: success, message, slots_found, booked_slot
        """
        from envoy.encryption import decrypt_token
        from envoy.resy import ResyClient
        from envoy.resy.client import ResyError

        result = {
            "success": False,
            "message": "",
            "slots_found": 0,
            "slots_checked": 0,
            "booked_slot": None,
        }

        logger.info(f"Starting test snipe for {snipe.venue_name}")
        logger.info(f"  Target date: {snipe.target_date}")
        logger.info(f"  Party size: {snipe.party_size}")
        logger.info(f"  Table type: {snipe.table_type or 'any'}")
        logger.info(
            f"  Time preference: {snipe.time_earliest or 'any'} - {snipe.time_latest or 'any'}"
        )

        # Use mock client or real client
        if self.mock_client:
            client = self.mock_client
            logger.info("Using MOCK Resy client")
        else:
            logger.warning("Using LIVE Resy client - real API calls!")
            client = ResyClient()

        start_time = asyncio.get_event_loop().time()
        request_count = 0

        try:
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time
                if elapsed > self.timeout_seconds:
                    result["message"] = f"Timeout after {elapsed:.1f}s"
                    logger.warning(result["message"])
                    break

                request_count += 1
                logger.debug(f"Request #{request_count} (elapsed: {elapsed:.1f}s)")

                try:
                    availability = await client.get_availability(
                        venue_id=snipe.venue_id,
                        check_date=snipe.target_date,
                        party_size=snipe.party_size,
                    )

                    result["slots_checked"] = request_count

                    if availability.slots:
                        result["slots_found"] = len(availability.slots)
                        logger.info(f"Found {len(availability.slots)} slots!")

                        # Filter by table type
                        matching_slots = availability.slots
                        if snipe.table_type:
                            matching_slots = self._filter_by_table_type(
                                availability.slots, snipe.table_type
                            )
                            logger.info(
                                f"  {len(matching_slots)} match table type '{snipe.table_type}'"
                            )

                        if matching_slots:
                            # Select best slot
                            best_slot = self._select_best_slot(
                                matching_slots,
                                snipe.time_earliest,
                                snipe.time_latest,
                            )

                            if best_slot:
                                logger.info(
                                    f"Selected slot: {best_slot.time} ({best_slot.type})"
                                )
                                result["booked_slot"] = {
                                    "time": best_slot.time,
                                    "type": best_slot.type,
                                    "config_token": best_slot.config_token,
                                }

                                # Attempt booking
                                if self.mock_client:
                                    book_result = await self.mock_client.quick_book(
                                        config_token=best_slot.config_token,
                                        party_size=snipe.party_size,
                                        check_date=snipe.target_date,
                                    )
                                else:
                                    # Real booking requires auth
                                    token = decrypt_token(snipe.resy_token_encrypted)
                                    auth_client = ResyClient(auth_token=token)
                                    book_result = await auth_client.quick_book(
                                        config_token=best_slot.config_token,
                                        party_size=snipe.party_size,
                                        check_date=snipe.target_date,
                                        payment_method_id=snipe.resy_payment_method_id,
                                    )
                                    await auth_client.close()

                                if book_result.success:
                                    result["success"] = True
                                    result["message"] = (
                                        f"Booked {best_slot.time} at {snipe.venue_name}"
                                    )
                                    result["reservation_id"] = book_result.reservation_id
                                    logger.info(f"✓ BOOKING SUCCESS: {result['message']}")
                                else:
                                    result["message"] = (
                                        f"Booking failed: {book_result.error_message}"
                                    )
                                    logger.error(f"✗ BOOKING FAILED: {result['message']}")

                                break
                            else:
                                logger.info("No slots in preferred time range")
                        else:
                            logger.info("No slots match table type filter")

                except ResyError as e:
                    logger.warning(f"API error: {e.message}")

                # Brief pause between requests
                await asyncio.sleep(0.3)

        finally:
            if not self.mock_client:
                await client.close()

        return result

    @staticmethod
    def _filter_by_table_type(slots: list[TimeSlot], table_type: str) -> list[TimeSlot]:
        """Filter slots by table type using case-insensitive partial matching."""
        table_type_lower = table_type.lower()
        return [
            slot
            for slot in slots
            if slot.type and table_type_lower in slot.type.lower()
        ]

    @staticmethod
    def _filter_by_time_range(
        slots: list[TimeSlot],
        earliest: Optional[time],
        latest: Optional[time],
    ) -> list[TimeSlot]:
        """Filter slots to those within the given time range."""
        if not earliest and not latest:
            return slots

        filtered = []
        for slot in slots:
            slot_time = slot.time_obj
            if earliest and slot_time < earliest:
                continue
            if latest and slot_time > latest:
                continue
            filtered.append(slot)
        return filtered

    @classmethod
    def _select_best_slot(
        cls,
        slots: list[TimeSlot],
        time_earliest: Optional[time],
        time_latest: Optional[time],
    ) -> Optional[TimeSlot]:
        """Select the best slot based on time preference."""
        if not slots:
            return None

        if time_earliest and time_latest:
            filtered = cls._filter_by_time_range(slots, time_earliest, time_latest)
            return filtered[0] if filtered else None

        # Try prime time first (7-8pm)
        prime_slots = cls._filter_by_time_range(slots, time(19, 0), time(20, 0))
        if prime_slots:
            return prime_slots[0]

        return slots[0]


async def list_pending_snipes():
    """List all pending snipes."""
    await Database.connect()
    try:
        # Get all pending snipes (query all users)
        rows = await Database.fetch(
            """
            SELECT s.*, u.telegram_id
            FROM snipes s
            JOIN users u ON s.user_id = u.id
            WHERE s.status = 'pending'
            ORDER BY s.release_date, s.release_time
            """
        )

        if not rows:
            print("\nNo pending snipes found.\n")
            return

        print(f"\n{'='*70}")
        print(f"{'ID':<6} {'Venue':<25} {'Target Date':<12} {'Release':<20}")
        print(f"{'='*70}")

        for row in rows:
            snipe = Snipe.model_validate(dict(row))
            release_str = f"{snipe.release_date} {snipe.release_time}"
            print(
                f"{snipe.id:<6} {snipe.venue_name[:24]:<25} "
                f"{str(snipe.target_date):<12} {release_str:<20}"
            )

        print(f"{'='*70}\n")

    finally:
        await Database.disconnect()


async def get_snipe_by_id(snipe_id: int) -> Optional[Snipe]:
    """Fetch a snipe by ID."""
    await Database.connect()
    try:
        return await SnipeQueries.get_by_id(snipe_id)
    finally:
        await Database.disconnect()


async def run_test(
    snipe_id: int,
    mock_slots: Optional[str],
    live: bool,
    timeout: float,
):
    """Run a test snipe."""
    # Connect to DB and get snipe
    await Database.connect()
    try:
        snipe = await SnipeQueries.get_by_id(snipe_id)
        if not snipe:
            logger.error(f"Snipe ID {snipe_id} not found")
            return

        # Parse mock slots
        mock_client = None
        if not live:
            if mock_slots is None:
                # Default: prime time slots
                slots = create_mock_slots(
                    ["18:30", "19:00", "19:30", "20:00", "20:30"],
                    "Dining Room",
                )
            elif mock_slots == "":
                # Empty = no availability
                slots = []
            else:
                # Parse comma-separated times
                times = [t.strip() for t in mock_slots.split(",")]
                slots = create_mock_slots(times, "Dining Room")

            mock_client = MockResyClient(slots=slots, booking_success=True)
            logger.info(f"Mock client configured with {len(slots)} slots")

        # Run the snipe
        sniper = TestableSniper(
            mock_client=mock_client,
            skip_wait=True,
            timeout_seconds=timeout,
        )

        print("\n" + "=" * 70)
        print("SNIPE TEST")
        print("=" * 70)

        result = await sniper.execute_snipe(snipe)

        print("\n" + "-" * 70)
        print("RESULT")
        print("-" * 70)
        print(f"  Success: {result['success']}")
        print(f"  Message: {result['message']}")
        print(f"  Slots found: {result['slots_found']}")
        print(f"  Requests made: {result['slots_checked']}")
        if result["booked_slot"]:
            print(f"  Booked slot: {result['booked_slot']}")
        print("=" * 70 + "\n")

    finally:
        await Database.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description="Test snipe execution without waiting for release time"
    )

    parser.add_argument(
        "--snipe-id",
        type=int,
        help="ID of the snipe to test",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List all pending snipes",
    )
    parser.add_argument(
        "--mock-slots",
        type=str,
        default=None,
        help='Comma-separated times for mock slots (e.g., "19:00,19:30,20:00"). '
        'Empty string "" for no availability.',
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Use real Resy API (WARNING: will actually book!)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout in seconds for the snipe attempt (default: 5)",
    )

    args = parser.parse_args()

    if args.list:
        asyncio.run(list_pending_snipes())
    elif args.snipe_id:
        if args.live:
            confirm = input(
                "\n⚠️  WARNING: --live will make REAL bookings!\n"
                "Type 'yes' to continue: "
            )
            if confirm.lower() != "yes":
                print("Aborted.")
                return

        asyncio.run(
            run_test(
                snipe_id=args.snipe_id,
                mock_slots=args.mock_slots,
                live=args.live,
                timeout=args.timeout,
            )
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()

