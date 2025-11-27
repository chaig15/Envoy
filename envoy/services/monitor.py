"""Availability monitoring service with smart batching."""

import asyncio
import logging
from typing import Optional

from telegram import Bot

from envoy.config import get_settings
from envoy.db.queries import WatchQueries
from envoy.db.models import WatchGroup, Watch
from envoy.resy import ResyClient
from envoy.resy.client import ResyError
from envoy.resy.models import TimeSlot
from .notifier import Notifier


logger = logging.getLogger(__name__)


class AvailabilityMonitor:
    """
    Background service that checks for reservation availability.

    Uses smart batching: watches with the same (venue, date, party_size)
    are checked with a single API call, then all watchers are notified.
    """

    def __init__(self, bot: Bot):
        self.bot = bot
        self.notifier = Notifier(bot)
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None

        # Semaphore to rate limit Resy API calls
        self._semaphore = asyncio.Semaphore(self.settings.max_concurrent_checks)

    def start(self) -> None:
        """Start the monitoring loop."""
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("Availability monitor started")

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("Availability monitor stopped")

    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                await self._check_all_watches()
            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

            # Wait before next check
            await asyncio.sleep(self.settings.check_interval_seconds)

    async def _check_all_watches(self) -> None:
        """Check availability for all active watches, batched by venue/date/party."""
        # Get watches grouped by (venue, date, party_size)
        groups = await WatchQueries.get_active_watches_grouped()

        if not groups:
            return

        logger.info(f"Checking {len(groups)} watch groups")

        # Check each group concurrently (with rate limiting)
        tasks = [self._check_group(group) for group in groups]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _check_group(self, group: WatchGroup) -> None:
        """
        Check availability for a group of watches.

        All watches in a group share the same venue, date, and party size,
        so we only need ONE API call.
        """
        async with self._semaphore:  # Rate limit
            try:
                # Skip groups where no watches have tokens (needed for booking later)
                # But availability checking doesn't require auth
                has_token = any(w.resy_token_encrypted for w in group.watches)
                if not has_token:
                    return

                # get_availability() doesn't require authentication
                client = ResyClient()

                # Make ONE API call for the whole group
                availability = await client.get_availability(
                    venue_id=group.venue_id,
                    check_date=group.date,
                    party_size=group.party_size,
                )
                await client.close()

                if not availability.slots:
                    return

                # Notify each watcher in the group
                for watch in group.watches:
                    await self._notify_if_new(watch, availability.slots)

            except ResyError as e:
                logger.warning(
                    f"Resy API error for venue {group.venue_id}: {e.message}"
                )
            except Exception as e:
                logger.error(f"Error checking group {group.venue_id}: {e}")

    async def _notify_if_new(self, watch: Watch, slots: list[TimeSlot]) -> None:
        """
        Notify a user about available slots if they haven't been notified already.

        Filters by time preference, table type, and tracks which slots have been notified.
        """
        # Filter by table type first (if specified)
        if watch.table_type:
            slots = self._filter_by_table_type(slots, watch.table_type)
            if not slots:
                return

        # Filter by time preference
        filtered_slots = []
        for slot in slots:
            slot_time = slot.time_obj

            # Check time range
            if watch.time_earliest and slot_time < watch.time_earliest:
                continue
            if watch.time_latest and slot_time > watch.time_latest:
                continue

            # Check if already notified for this slot
            if slot.config_token in watch.notified_slots:
                continue

            filtered_slots.append(slot)

        if not filtered_slots:
            return

        # Send notification
        try:
            await self.notifier.send_availability_alert(watch, filtered_slots)

            # Mark slots as notified
            for slot in filtered_slots:
                await WatchQueries.mark_slot_notified(watch.id, slot.config_token)

            logger.info(
                f"Notified user {watch.telegram_id} about {len(filtered_slots)} slots "
                f"at {watch.venue_name}"
            )
        except Exception as e:
            logger.error(f"Failed to notify user {watch.telegram_id}: {e}")

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
