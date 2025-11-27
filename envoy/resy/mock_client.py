"""Mock Resy client for testing snipe logic without hitting the real API."""

import logging
from datetime import date
from typing import Optional

from .models import (
    Availability,
    BookingDetails,
    BookingResult,
    TimeSlot,
)

logger = logging.getLogger(__name__)


class MockResyClient:
    """
    Mock implementation of ResyClient for testing.

    Allows configuring what availability and booking results to return,
    enabling full snipe flow testing without network calls.

    Usage:
        # Simulate finding slots
        client = MockResyClient(
            slots=[
                TimeSlot(config_id="token1", time="19:00", type="Dining Room"),
                TimeSlot(config_id="token2", time="20:00", type="Bar"),
            ]
        )

        # Simulate no availability
        client = MockResyClient(slots=[])

        # Simulate booking failure
        client = MockResyClient(
            slots=[TimeSlot(config_id="token1", time="19:00", type="Dining Room")],
            booking_success=False,
            booking_error="Slot no longer available"
        )
    """

    def __init__(
        self,
        slots: Optional[list[TimeSlot]] = None,
        booking_success: bool = True,
        booking_error: Optional[str] = None,
        delay_seconds: float = 0.0,
    ):
        """
        Initialize mock client.

        Args:
            slots: List of TimeSlot objects to return from get_availability
            booking_success: Whether booking should succeed
            booking_error: Error message if booking fails
            delay_seconds: Artificial delay to simulate network latency
        """
        self.slots = slots or []
        self.booking_success = booking_success
        self.booking_error = booking_error
        self.delay_seconds = delay_seconds

        # Track calls for assertions in tests
        self.availability_calls: list[dict] = []
        self.booking_calls: list[dict] = []

    async def close(self) -> None:
        """No-op for mock client."""
        pass

    async def get_availability(
        self,
        venue_id: int,
        check_date: date,
        party_size: int,
    ) -> Availability:
        """Return mock availability."""
        import asyncio

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        # Track the call
        self.availability_calls.append(
            {
                "venue_id": venue_id,
                "check_date": check_date,
                "party_size": party_size,
            }
        )

        logger.debug(
            f"MockResyClient.get_availability: venue={venue_id}, "
            f"date={check_date}, party={party_size}, returning {len(self.slots)} slots"
        )

        return Availability(
            venue_id=venue_id,
            venue_name="Mock Restaurant",
            date=check_date,
            party_size=party_size,
            slots=self.slots,
        )

    async def get_booking_details(
        self, config_token: str, party_size: int, check_date: date
    ) -> BookingDetails:
        """Return mock booking details."""
        import asyncio

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        return BookingDetails(
            book_token=f"mock_book_token_{config_token}",
            config_id=config_token,
            day=check_date.isoformat(),
            party_size=party_size,
            venue_id=12345,
        )

    async def book(
        self,
        book_token: str,
        payment_method_id: Optional[str] = None,
    ) -> BookingResult:
        """Return mock booking result."""
        import asyncio

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        self.booking_calls.append(
            {
                "book_token": book_token,
                "payment_method_id": payment_method_id,
            }
        )

        if self.booking_success:
            return BookingResult(
                success=True,
                reservation_id="mock_res_12345",
                confirmation_number="MOCK123",
                venue_name="Mock Restaurant",
                date="2025-01-15",
                time="7:00 PM",
                party_size=2,
            )
        else:
            return BookingResult(
                success=False,
                error_message=self.booking_error or "Mock booking failed",
            )

    async def quick_book(
        self,
        config_token: str,
        party_size: int,
        check_date: date,
        payment_method_id: Optional[str] = None,
    ) -> BookingResult:
        """One-step mock booking."""
        import asyncio

        if self.delay_seconds > 0:
            await asyncio.sleep(self.delay_seconds)

        self.booking_calls.append(
            {
                "config_token": config_token,
                "party_size": party_size,
                "check_date": check_date,
                "payment_method_id": payment_method_id,
            }
        )

        logger.debug(
            f"MockResyClient.quick_book: token={config_token}, "
            f"success={self.booking_success}"
        )

        if self.booking_success:
            return BookingResult(
                success=True,
                reservation_id="mock_res_12345",
                confirmation_number="MOCK123",
                venue_name="Mock Restaurant",
                date=check_date.isoformat(),
                time="7:00 PM",
                party_size=party_size,
            )
        else:
            return BookingResult(
                success=False,
                error_message=self.booking_error or "Mock booking failed",
            )


def create_mock_slots(
    times: list[str], slot_type: str = "Dining Room"
) -> list[TimeSlot]:
    """
    Helper to create mock TimeSlot objects.

    Args:
        times: List of time strings like ["19:00", "19:30", "20:00"]
        slot_type: Type of seating (e.g., "Dining Room", "Bar")

    Returns:
        List of TimeSlot objects
    """
    return [
        TimeSlot(config_id=f"token_{i}", time=t, type=slot_type)
        for i, t in enumerate(times)
    ]
