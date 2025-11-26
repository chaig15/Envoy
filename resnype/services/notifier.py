"""Notification service for sending availability alerts."""

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from resnype.db.models import Watch
from resnype.resy.models import TimeSlot


# Cache for pending booking slots (watch_id -> {slot_index -> token})
# This avoids Telegram's 64-byte callback_data limit
_pending_slots: dict[int, dict[int, str]] = {}


def get_pending_slot(watch_id: int, slot_index: int) -> str | None:
    """Get a cached slot token for booking."""
    return _pending_slots.get(watch_id, {}).get(slot_index)


def clear_pending_slots(watch_id: int) -> None:
    """Clear cached slots for a watch."""
    _pending_slots.pop(watch_id, None)


class Notifier:
    """Handles sending availability notifications to users."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_availability_alert(
        self,
        watch: Watch,
        slots: list[TimeSlot],
    ) -> None:
        """
        Send an availability alert with one-click booking buttons.

        Args:
            watch: The watch that matched
            slots: Available time slots
        """
        if not slots:
            return

        # Cache slots for booking (avoids 64-byte callback limit)
        _pending_slots[watch.id] = {
            i: slot.config_token for i, slot in enumerate(slots[:4])
        }

        # Format the message
        text_parts = [
            "🚨 **Table Available!**\n",
            f"🍽 **{watch.venue_name}**",
            f"📅 {watch.date.strftime('%A, %B %d')}",
            f"👥 {watch.party_size} guests\n",
            "**Available times:**",
        ]

        # Show up to 5 slots
        for slot in slots[:5]:
            slot_type = f" ({slot.type})" if slot.type else ""
            text_parts.append(f"• {slot.time_display}{slot_type}")

        if len(slots) > 5:
            text_parts.append(f"_...and {len(slots) - 5} more_")

        # Create booking buttons - use slot index instead of full token
        keyboard = []
        for i, slot in enumerate(slots[:4]):  # Max 4 buttons
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📍 Book {slot.time_display}",
                        callback_data=f"book:{watch.id}:{i}",
                    )
                ]
            )

        # Add dismiss button
        keyboard.append(
            [InlineKeyboardButton("✖️ Dismiss", callback_data=f"dismiss:{watch.id}")]
        )

        # Send the notification
        await self.bot.send_message(
            chat_id=watch.telegram_id,
            text="\n".join(text_parts),
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
