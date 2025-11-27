"""Unit tests for the Sniper service."""

import pytest
from datetime import date, time, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from envoy.db.models import Snipe
from envoy.resy.mock_client import MockResyClient, create_mock_slots
from envoy.resy.models import TimeSlot
from envoy.services.sniper import Sniper


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_bot():
    """Create a mock Telegram bot."""
    bot = MagicMock()
    bot.send_message = AsyncMock()
    return bot


@pytest.fixture
def sniper(mock_bot):
    """Create a Sniper instance with mock bot."""
    return Sniper(bot=mock_bot)


@pytest.fixture
def sample_snipe():
    """Create a sample snipe for testing."""
    return Snipe(
        id=1,
        user_id=100,
        venue_id=12345,
        venue_name="Test Restaurant",
        target_date=date.today() + timedelta(days=7),
        release_date=date.today(),
        party_size=2,
        table_type=None,
        time_earliest=None,
        time_latest=None,
        release_time=time(9, 0),
        release_timezone="America/New_York",
        status="pending",
        created_at=datetime.now(),
        telegram_id=999,
        resy_token_encrypted="encrypted_token",
        resy_payment_method_id="pm_123",
    )


# ============================================================================
# _filter_by_table_type tests
# ============================================================================


class TestFilterByTableType:
    """Tests for _filter_by_table_type method."""

    def test_exact_match(self, sniper):
        """Exact table type match should work."""
        slots = [
            TimeSlot(config_id="1", time="19:00", type="Dining Room"),
            TimeSlot(config_id="2", time="19:30", type="Bar"),
        ]
        result = sniper._filter_by_table_type(slots, "Dining Room")
        assert len(result) == 1
        assert result[0].type == "Dining Room"

    def test_partial_match(self, sniper):
        """Partial table type match should work."""
        slots = [
            TimeSlot(config_id="1", time="19:00", type="Butter Chicken Experience"),
            TimeSlot(config_id="2", time="19:30", type="Regular Dining"),
        ]
        result = sniper._filter_by_table_type(slots, "Butter Chicken")
        assert len(result) == 1
        assert result[0].type == "Butter Chicken Experience"

    def test_case_insensitive(self, sniper):
        """Case-insensitive matching should work."""
        slots = [
            TimeSlot(config_id="1", time="19:00", type="Dining Room"),
            TimeSlot(config_id="2", time="19:30", type="BAR SEATING"),
        ]
        result = sniper._filter_by_table_type(slots, "bar")
        assert len(result) == 1
        assert result[0].type == "BAR SEATING"

    def test_no_match(self, sniper):
        """No matches should return empty list."""
        slots = [
            TimeSlot(config_id="1", time="19:00", type="Dining Room"),
            TimeSlot(config_id="2", time="19:30", type="Bar"),
        ]
        result = sniper._filter_by_table_type(slots, "Patio")
        assert len(result) == 0

    def test_none_type_slots(self, sniper):
        """Slots with None type should be filtered out."""
        slots = [
            TimeSlot(config_id="1", time="19:00", type=None),
            TimeSlot(config_id="2", time="19:30", type="Bar"),
        ]
        result = sniper._filter_by_table_type(slots, "Dining")
        assert len(result) == 0


# ============================================================================
# _filter_by_time_range tests
# ============================================================================


class TestFilterByTimeRange:
    """Tests for _filter_by_time_range method."""

    def test_no_filter(self, sniper):
        """No time range should return all slots."""
        slots = create_mock_slots(["18:00", "19:00", "20:00", "21:00"])
        result = sniper._filter_by_time_range(slots, None, None)
        assert len(result) == 4

    def test_earliest_only(self, sniper):
        """Filter by earliest time only."""
        slots = create_mock_slots(["18:00", "19:00", "20:00", "21:00"])
        result = sniper._filter_by_time_range(slots, time(19, 0), None)
        assert len(result) == 3
        assert all(s.time >= "19:00" for s in result)

    def test_latest_only(self, sniper):
        """Filter by latest time only."""
        slots = create_mock_slots(["18:00", "19:00", "20:00", "21:00"])
        result = sniper._filter_by_time_range(slots, None, time(20, 0))
        assert len(result) == 3
        assert all(s.time <= "20:00" for s in result)

    def test_both_bounds(self, sniper):
        """Filter by both earliest and latest."""
        slots = create_mock_slots(["18:00", "19:00", "20:00", "21:00"])
        result = sniper._filter_by_time_range(slots, time(19, 0), time(20, 0))
        assert len(result) == 2
        assert result[0].time == "19:00"
        assert result[1].time == "20:00"


# ============================================================================
# _select_best_slot tests
# ============================================================================


class TestSelectBestSlot:
    """Tests for _select_best_slot method."""

    def test_empty_slots(self, sniper):
        """Empty slots should return None."""
        result = sniper._select_best_slot([], None, None)
        assert result is None

    def test_with_time_range(self, sniper):
        """Should return first slot in time range."""
        slots = create_mock_slots(["18:00", "19:00", "19:30", "20:00"])
        result = sniper._select_best_slot(slots, time(19, 0), time(20, 0))
        assert result is not None
        assert result.time == "19:00"

    def test_time_range_no_match(self, sniper):
        """Should return None if no slots in time range."""
        slots = create_mock_slots(["18:00", "21:00", "22:00"])
        result = sniper._select_best_slot(slots, time(19, 0), time(20, 0))
        assert result is None

    def test_any_time_prefers_prime(self, sniper):
        """Without time preference, should prefer 7-8pm (prime time)."""
        slots = create_mock_slots(["18:00", "19:30", "20:30", "21:00"])
        result = sniper._select_best_slot(slots, None, None)
        assert result is not None
        assert result.time == "19:30"  # 7:30pm is in prime time

    def test_any_time_falls_back(self, sniper):
        """Without prime time slots, should return first available."""
        slots = create_mock_slots(["18:00", "21:00", "22:00"])
        result = sniper._select_best_slot(slots, None, None)
        assert result is not None
        assert result.time == "18:00"


# ============================================================================
# _calculate_interval tests
# ============================================================================


class TestCalculateInterval:
    """Tests for _calculate_interval method."""

    def test_idle_interval(self, sniper):
        """Far away snipes should use idle interval."""
        assert sniper._calculate_interval(300) == 30  # 5 min away
        assert sniper._calculate_interval(180) == 30  # 3 min away
        assert sniper._calculate_interval(121) == 30  # Just over 2 min

    def test_alert_interval(self, sniper):
        """Snipes within 2 minutes should use alert interval."""
        assert sniper._calculate_interval(120) == 5  # Exactly 2 min
        assert sniper._calculate_interval(60) == 5  # 1 min
        assert sniper._calculate_interval(31) == 5  # Just over 30s

    def test_active_interval(self, sniper):
        """Snipes within 30 seconds should use active interval."""
        assert sniper._calculate_interval(30) == 1  # Exactly 30s
        assert sniper._calculate_interval(10) == 1  # 10s
        assert sniper._calculate_interval(1) == 1  # 1s


# ============================================================================
# MockResyClient tests
# ============================================================================


class TestMockResyClient:
    """Tests for MockResyClient."""

    @pytest.mark.asyncio
    async def test_get_availability(self):
        """Mock client should return configured slots."""
        slots = create_mock_slots(["19:00", "20:00"])
        client = MockResyClient(slots=slots)

        result = await client.get_availability(
            venue_id=123,
            check_date=date.today(),
            party_size=2,
        )

        assert len(result.slots) == 2
        assert result.slots[0].time == "19:00"
        assert len(client.availability_calls) == 1

    @pytest.mark.asyncio
    async def test_empty_availability(self):
        """Mock client with no slots should return empty."""
        client = MockResyClient(slots=[])

        result = await client.get_availability(
            venue_id=123,
            check_date=date.today(),
            party_size=2,
        )

        assert len(result.slots) == 0

    @pytest.mark.asyncio
    async def test_booking_success(self):
        """Mock client should simulate successful booking."""
        client = MockResyClient(booking_success=True)

        result = await client.quick_book(
            config_token="token123",
            party_size=2,
            check_date=date.today(),
        )

        assert result.success is True
        assert result.reservation_id is not None

    @pytest.mark.asyncio
    async def test_booking_failure(self):
        """Mock client should simulate booking failure."""
        client = MockResyClient(
            booking_success=False,
            booking_error="Slot no longer available",
        )

        result = await client.quick_book(
            config_token="token123",
            party_size=2,
            check_date=date.today(),
        )

        assert result.success is False
        assert "no longer available" in result.error_message


# ============================================================================
# Integration-style tests
# ============================================================================


class TestSniperIntegration:
    """Integration tests for sniper with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_triggered_snipes_tracking(self, sniper):
        """Sniper should track triggered snipes to avoid double-firing."""
        # Initially empty
        assert len(sniper._triggered_snipes) == 0

        # Add a snipe ID
        sniper._triggered_snipes.add(1)
        assert 1 in sniper._triggered_snipes

        # Should not process same snipe twice
        assert 1 in sniper._triggered_snipes
