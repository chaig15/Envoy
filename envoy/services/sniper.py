"""Sniper service for executing scheduled reservation snipes."""

import asyncio
import logging
from datetime import datetime, time
from typing import Optional

import pytz
from telegram import Bot

from envoy.config import get_settings
from envoy.db.models import Snipe
from envoy.db.queries import SnipeQueries
from envoy.encryption import decrypt_token
from envoy.resy import ResyClient
from envoy.resy.client import ResyError
from envoy.resy.models import TimeSlot

logger = logging.getLogger(__name__)


class Sniper:
    """
    Service that executes scheduled snipes at release time.

    Uses adaptive scheduling: checks more frequently as release time approaches,
    then hammers the API at the exact release time to grab the first available slot.
    """

    # Sniping parameters
    SNIPE_DURATION_SECONDS = 60  # How long to try
    REQUESTS_PER_SECOND = 3  # Rate during sniping
    PRE_SNIPE_SECONDS = 30  # Start snipe task early to pre-warm connection
    PRE_WARM_SECONDS = 25  # Warm connection this many seconds before release

    # Adaptive scheduler intervals (in seconds)
    INTERVAL_IDLE = 30  # No snipes soon
    INTERVAL_ALERT = 5  # Snipe within 2 minutes
    INTERVAL_ACTIVE = 1  # Snipe within 30 seconds

    def __init__(self, bot: Bot):
        self.bot = bot
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._triggered_snipes: set[int] = set()  # Track triggered snipe IDs to avoid double-firing

    def start(self) -> None:
        """Start the sniper scheduler."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Sniper service started")

    def stop(self) -> None:
        """Stop the sniper scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Sniper service stopped")

    async def _scheduler_loop(self) -> None:
        """
        Main scheduler loop with adaptive interval.

        Checks more frequently as release time approaches:
        - 30s when idle (no snipes within 2 min)
        - 5s when a snipe is within 2 minutes
        - 1s when a snipe is within 30 seconds
        """
        while self._running:
            try:
                next_interval = await self._check_due_snipes()
            except Exception as e:
                logger.error(f"Error in sniper scheduler: {e}")
                next_interval = self.INTERVAL_IDLE

            await asyncio.sleep(next_interval)

    async def _check_due_snipes(self) -> int:
        """
        Find and execute snipes that are due now.

        Returns the recommended interval (in seconds) until next check.
        """
        # Get snipes scheduled for today
        snipes = await SnipeQueries.get_pending_snipes_due()

        if not snipes:
            return self.INTERVAL_IDLE

        now = datetime.now(pytz.timezone("America/New_York"))
        soonest_seconds = float("inf")

        for snipe in snipes:
            # Skip if we've already triggered this snipe
            if snipe.id in self._triggered_snipes:
                continue

            # Calculate release datetime
            release_time = snipe.release_time
            release_datetime = now.replace(
                hour=release_time.hour,
                minute=release_time.minute,
                second=0,
                microsecond=0,
            )

            # Time until release
            time_until = (release_datetime - now).total_seconds()

            # If within pre-snipe window, start sniping
            if -self.SNIPE_DURATION_SECONDS <= time_until <= self.PRE_SNIPE_SECONDS:
                logger.info(
                    f"Starting snipe for {snipe.venue_name} "
                    f"(release in {time_until:.0f}s)"
                )
                # Mark as triggered to prevent double-firing
                self._triggered_snipes.add(snipe.id)
                # Run snipe in background task
                asyncio.create_task(self._execute_snipe(snipe, release_datetime))
            elif time_until > self.PRE_SNIPE_SECONDS:
                # Track soonest upcoming snipe for interval calculation
                soonest_seconds = min(soonest_seconds, time_until)

        return self._calculate_interval(soonest_seconds)

    def _calculate_interval(self, seconds_until_snipe: float) -> int:
        """
        Calculate the next scheduler check interval based on snipe proximity.

        - > 2 minutes away: check every 30s (IDLE)
        - 30s - 2 minutes away: check every 5s (ALERT)
        - < 30s away: check every 1s (ACTIVE)
        """
        if seconds_until_snipe <= 30:
            return self.INTERVAL_ACTIVE
        elif seconds_until_snipe <= 120:
            return self.INTERVAL_ALERT
        else:
            return self.INTERVAL_IDLE

    async def _execute_snipe(self, snipe: Snipe, release_datetime: datetime) -> None:
        """
        Execute a single snipe.

        1. Pre-warm HTTP connection
        2. Wait until just before release time
        3. Start polling availability aggressively
        4. Book immediately when slots found
        5. Notify user of result
        """
        try:
            # Mark as sniping
            await SnipeQueries.update_status(snipe.id, "sniping")

            now = datetime.now(pytz.timezone("America/New_York"))
            seconds_until_release = (release_datetime - now).total_seconds()

            # Create client early to pre-warm the connection
            client = ResyClient()  # No auth needed for availability

            # Pre-warm: make a request to establish TCP/TLS connection
            if seconds_until_release > self.PRE_WARM_SECONDS:
                logger.info(
                    f"Pre-warming connection for {snipe.venue_name} "
                    f"({seconds_until_release:.0f}s until release)"
                )
                try:
                    # Lightweight availability check to warm connection
                    await client.get_availability(
                        venue_id=snipe.venue_id,
                        check_date=snipe.target_date,
                        party_size=snipe.party_size,
                    )
                    logger.info("Connection pre-warmed successfully")
                except Exception as e:
                    logger.warning(f"Pre-warm request failed (non-fatal): {e}")

            # Wait until release time (minus a tiny bit)
            now = datetime.now(pytz.timezone("America/New_York"))
            wait_seconds = (release_datetime - now).total_seconds() - 0.5
            if wait_seconds > 0:
                logger.info(f"Waiting {wait_seconds:.1f}s until release...")
                await asyncio.sleep(wait_seconds)

            # Start aggressive polling
            logger.info(f"Sniping {snipe.venue_name} for {snipe.target_date}...")

            start_time = asyncio.get_event_loop().time()
            request_interval = 1.0 / self.REQUESTS_PER_SECOND

            # Use the pre-warmed client for aggressive polling
            while True:
                elapsed = asyncio.get_event_loop().time() - start_time

                # Stop after duration
                if elapsed > self.SNIPE_DURATION_SECONDS:
                    logger.warning(f"Snipe timeout for {snipe.venue_name}")
                    await self._snipe_failed(snipe, "No slots found within time limit")
                    await client.close()
                    return

                try:
                    # Check availability
                    availability = await client.get_availability(
                        venue_id=snipe.venue_id,
                        check_date=snipe.target_date,
                        party_size=snipe.party_size,
                    )

                    if availability.slots:
                        # Filter by table type if specified
                        matching_slots = availability.slots
                        if snipe.table_type:
                            matching_slots = self._filter_by_table_type(
                                availability.slots, snipe.table_type
                            )
                            logger.info(
                                f"Found {len(availability.slots)} total slots, "
                                f"{len(matching_slots)} matching '{snipe.table_type}'"
                            )

                        if matching_slots:
                            # Select best slot based on time preference
                            best_slot = self._select_best_slot(
                                matching_slots,
                                snipe.time_earliest,
                                snipe.time_latest,
                            )

                            if best_slot:
                                logger.info(
                                    f"Booking slot: {best_slot.type} at {best_slot.time}"
                                )
                                await client.close()
                                await self._book_slot(snipe, best_slot.config_token)
                                return
                            else:
                                # Slots exist but none in preferred time range
                                logger.info(
                                    f"No slots in preferred time range. "
                                    f"Available times: {[s.time for s in matching_slots[:5]]}"
                                )
                        elif availability.slots and snipe.table_type:
                            # Slots exist but none match the requested type
                            # Log available types for debugging
                            available_types = set(
                                s.type for s in availability.slots if s.type
                            )
                            logger.info(
                                f"No '{snipe.table_type}' slots found. "
                                f"Available types: {available_types}"
                            )

                except ResyError as e:
                    logger.warning(f"API error during snipe: {e.message}")

                # Wait before next request
                await asyncio.sleep(request_interval)

        except Exception as e:
            logger.exception(f"Snipe execution error: {e}")
            await self._snipe_failed(snipe, str(e))

    async def _book_slot(self, snipe: Snipe, config_token: str) -> None:
        """Attempt to book a slot."""
        try:
            # Need user's token for booking
            token = decrypt_token(snipe.resy_token_encrypted)
            client = ResyClient(auth_token=token)

            result = await client.quick_book(
                config_token=config_token,
                party_size=snipe.party_size,
                check_date=snipe.target_date,
                payment_method_id=snipe.resy_payment_method_id,
            )
            await client.close()

            if result.success:
                await self._snipe_success(snipe, result)
            else:
                # Booking failed but we found a slot - could retry
                await self._snipe_failed(
                    snipe, result.error_message or "Booking failed"
                )

        except Exception as e:
            logger.exception(f"Booking error: {e}")
            await self._snipe_failed(snipe, str(e))

    async def _snipe_success(self, snipe: Snipe, result) -> None:
        """Handle successful snipe."""
        await SnipeQueries.update_status(
            snipe.id,
            "success",
            reservation_id=result.reservation_id,
            message=f"Booked at {result.time}",
        )

        # Notify user
        table_type_info = f"\n🪑 {snipe.table_type}" if snipe.table_type else ""
        await self.bot.send_message(
            chat_id=snipe.telegram_id,
            text=(
                f"🎉 **Snipe Successful!**\n\n"
                f"🍽 {snipe.venue_name}{table_type_info}\n"
                f"📅 {result.date or snipe.target_date}\n"
                f"⏰ {result.time or 'See Resy app'}\n"
                f"👥 {result.party_size or snipe.party_size} guests\n\n"
                f"Confirmation: `{result.confirmation_number or 'Check Resy app'}`"
            ),
            parse_mode="Markdown",
        )

        logger.info(f"Snipe SUCCESS: {snipe.venue_name} for {snipe.target_date}")

    async def _snipe_failed(self, snipe: Snipe, error: str) -> None:
        """Handle failed snipe."""
        await SnipeQueries.update_status(
            snipe.id,
            "failed",
            message=error,
        )

        # Notify user
        table_type_info = (
            f"\n🪑 Table type: {snipe.table_type}" if snipe.table_type else ""
        )
        await self.bot.send_message(
            chat_id=snipe.telegram_id,
            text=(
                f"❌ **Snipe Failed**\n\n"
                f"🍽 {snipe.venue_name}\n"
                f"📅 {snipe.target_date}{table_type_info}\n\n"
                f"Reason: {error}\n\n"
                f"You can try setting up a /watch to catch cancellations."
            ),
            parse_mode="Markdown",
        )

        logger.warning(f"Snipe FAILED: {snipe.venue_name} - {error}")

    @staticmethod
    def _filter_by_table_type(slots: list[TimeSlot], table_type: str) -> list[TimeSlot]:
        """
        Filter slots by table type using case-insensitive partial matching.

        Examples:
            - "Butter Chicken" matches "Butter Chicken Experience"
            - "bar" matches "Bar Seating"
            - "dining" matches "Dining Room"
        """
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
        """
        Select the best slot based on time preference.

        Strategy:
        - If time range specified: return first slot in that range, or None
        - If no time range ("any"): try prime time (7-8pm) first, then any available
        """
        if not slots:
            return None

        # If specific time range requested, filter strictly
        if time_earliest and time_latest:
            filtered = cls._filter_by_time_range(slots, time_earliest, time_latest)
            return filtered[0] if filtered else None

        # "Any" time: try prime time first (7-8pm), then fall back to any
        prime_start = time(19, 0)  # 7pm
        prime_end = time(20, 0)  # 8pm

        prime_slots = cls._filter_by_time_range(slots, prime_start, prime_end)
        if prime_slots:
            return prime_slots[0]

        # No prime slots available, return first available
        return slots[0]
