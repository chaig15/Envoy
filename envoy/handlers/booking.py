"""Booking handlers for one-click reservation."""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from envoy.db.queries import UserQueries, WatchQueries
from envoy.resy import ResyClient
from envoy.resy.client import ResyError
from envoy.encryption import decrypt_token
from envoy.services.notifier import get_pending_slot, clear_pending_slots

logger = logging.getLogger(__name__)


async def book_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle one-click booking from alert notification.

    Callback data format: book:{watch_id}:{slot_index}
    """
    query = update.callback_query
    await query.answer("Booking...")

    # Parse callback data
    parts = query.data.split(":")
    if len(parts) != 3:
        await query.edit_message_text("❌ Invalid booking data.")
        return

    _, watch_id, slot_index = parts
    watch_id = int(watch_id)
    slot_index = int(slot_index)

    # Get config token from cache
    config_token = get_pending_slot(watch_id, slot_index)
    if not config_token:
        await query.edit_message_text(
            "❌ Booking expired. Please wait for a new availability alert."
        )
        return

    # Get watch and user info
    watch = await WatchQueries.get_by_id(watch_id)
    if not watch:
        await query.edit_message_text("❌ Watch not found.")
        return

    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user or not user.resy_token_encrypted:
        await query.edit_message_text("❌ Please /login first.")
        return

    # Update message to show booking in progress
    await query.edit_message_text(
        f"⏳ **Booking {watch.venue_name}...**\n\nPlease wait, securing your table!",
        parse_mode="Markdown",
    )

    client = ResyClient(auth_token=decrypt_token(user.resy_token_encrypted))
    try:
        result = await client.quick_book(
            config_token=config_token,
            party_size=watch.party_size,
            check_date=watch.date,
            payment_method_id=user.resy_payment_method_id,
        )

        if result.success:
            # Deactivate the watch and clear pending slots
            await WatchQueries.deactivate(watch_id, update.effective_user.id)
            clear_pending_slots(watch_id)

            await query.edit_message_text(
                f"🎉 **Reservation Confirmed!**\n\n"
                f"🍽 {result.venue_name or watch.venue_name}\n"
                f"📅 {result.date or watch.date.isoformat()}\n"
                f"⏰ {result.time or 'See confirmation'}\n"
                f"👥 {result.party_size or watch.party_size} guests\n\n"
                f"Confirmation: `{result.confirmation_number or 'Check Resy app'}`",
                parse_mode="Markdown",
            )
        else:
            # Booking failed - offer to try again
            keyboard = [
                [
                    InlineKeyboardButton(
                        "🔄 Try Again",
                        callback_data=f"book:{watch_id}:{slot_index}",
                    )
                ]
            ]

            await query.edit_message_text(
                f"❌ **Booking Failed**\n\n"
                f"{result.error_message or 'The table may no longer be available.'}\n\n"
                "The slot might have been taken. I'll keep watching for more availability!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )

    except ResyError as e:
        logger.error(f"Booking error: {e.message}")
        await query.edit_message_text(
            f"❌ Booking error: {e.message}\n\n"
            "Please try again or book directly on Resy."
        )
    except Exception as e:
        logger.exception(f"Unexpected booking error: {e}")
        await query.edit_message_text(
            "❌ Something went wrong. Please try booking directly on Resy."
        )
    finally:
        await client.close()


async def dismiss_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dismiss an availability alert."""
    query = update.callback_query
    await query.answer("Dismissed")

    await query.edit_message_text(
        "Alert dismissed. I'll keep watching for more availability!"
    )


def setup_booking_handlers(application) -> None:
    """Register booking handlers with the application."""
    application.add_handler(CallbackQueryHandler(book_slot, pattern=r"^book:"))
    application.add_handler(CallbackQueryHandler(dismiss_alert, pattern=r"^dismiss:"))
