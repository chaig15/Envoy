"""Sniper service for executing scheduled reservation snipes."""

import asyncio
import logging
from datetime import datetime
from typing import Optional

import pytz
from telegram import Bot

from resnype.config import get_settings
from resnype.db.models import Snipe
from resnype.db.queries import SnipeQueries
from resnype.encryption import decrypt_token
from resnype.resy import ResyClient
from resnype.resy.client import ResyError

logger = logging.getLogger(__name__)


class Sniper:
    """
    Service that executes scheduled snipes at release time.

    Checks every minute for snipes due soon, then hammers the API
    at the exact release time to grab the first available slot.
    """

    # Sniping parameters
    SNIPE_DURATION_SECONDS = 60  # How long to try
    REQUESTS_PER_SECOND = 3  # Rate during sniping
    PRE_SNIPE_SECONDS = 5  # Start polling before release time

    def __init__(self, bot: Bot):
        self.bot = bot
        self.settings = get_settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None

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
        """Main scheduler loop - checks every minute for due snipes."""
        while self._running:
            try:
                await self._check_due_snipes()
            except Exception as e:
                logger.error(f"Error in sniper scheduler: {e}")

            # Check every 30 seconds
            await asyncio.sleep(30)

    async def _check_due_snipes(self) -> None:
        """Find and execute snipes that are due now."""
        # Get snipes scheduled for today
        snipes = await SnipeQueries.get_pending_snipes_due()

        if not snipes:
            return

        now = datetime.now(pytz.timezone("America/New_York"))
        current_time = now.time()

        for snipe in snipes:
            # Calculate if this snipe should execute now
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
                # Run snipe in background task
                asyncio.create_task(self._execute_snipe(snipe, release_datetime))

    async def _execute_snipe(self, snipe: Snipe, release_datetime: datetime) -> None:
        """
        Execute a single snipe.

        1. Wait until just before release time
        2. Start polling availability aggressively
        3. Book immediately when slots found
        4. Notify user of result
        """
        try:
            # Mark as sniping
            await SnipeQueries.update_status(snipe.id, "sniping")

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

            client = ResyClient()  # No auth needed for availability

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
                        # Found slots! Book immediately
                        logger.info(
                            f"Found {len(availability.slots)} slots for {snipe.venue_name}!"
                        )
                        await client.close()
                        await self._book_slot(snipe, availability.slots[0].config_token)
                        return

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
        await self.bot.send_message(
            chat_id=snipe.telegram_id,
            text=(
                f"🎉 **Snipe Successful!**\n\n"
                f"🍽 {snipe.venue_name}\n"
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
        await self.bot.send_message(
            chat_id=snipe.telegram_id,
            text=(
                f"❌ **Snipe Failed**\n\n"
                f"🍽 {snipe.venue_name}\n"
                f"📅 {snipe.target_date}\n\n"
                f"Reason: {error}\n\n"
                f"You can try setting up a /watch to catch cancellations."
            ),
            parse_mode="Markdown",
        )

        logger.warning(f"Snipe FAILED: {snipe.venue_name} - {error}")
