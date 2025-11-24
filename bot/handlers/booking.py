"""Booking handlers for one-click reservation."""

from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from bot.db.queries import UserQueries, WatchQueries
from bot.resy import ResyClient
from bot.resy.client import ResyError
from bot.encryption import decrypt_token


async def book_slot(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Handle one-click booking from alert notification.
    
    Callback data format: book:{watch_id}:{config_token}:{date}
    """
    query = update.callback_query
    await query.answer("Booking...")
    
    # Parse callback data
    parts = query.data.split(":", 3)
    if len(parts) != 4:
        await query.edit_message_text("❌ Invalid booking data.")
        return
    
    _, watch_id, config_token, date_str = parts
    watch_id = int(watch_id)
    
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
        f"⏳ **Booking {watch.venue_name}...**\n\n"
        "Please wait, securing your table!",
        parse_mode="Markdown"
    )
    
    try:
        # Decrypt token and book
        token = decrypt_token(user.resy_token_encrypted)
        client = ResyClient(auth_token=token)
        
        check_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        result = await client.quick_book(
            config_token=config_token,
            party_size=watch.party_size,
            check_date=check_date,
            payment_method_id=user.resy_payment_method_id,
        )
        await client.close()
        
        if result.success:
            # Deactivate the watch since we booked
            await WatchQueries.deactivate(watch_id, update.effective_user.id)
            
            await query.edit_message_text(
                f"🎉 **Reservation Confirmed!**\n\n"
                f"🍽 {result.venue_name or watch.venue_name}\n"
                f"📅 {result.date or date_str}\n"
                f"⏰ {result.time or 'See confirmation'}\n"
                f"👥 {result.party_size or watch.party_size} guests\n\n"
                f"Confirmation: `{result.confirmation_number or 'Check Resy app'}`",
                parse_mode="Markdown"
            )
        else:
            # Booking failed - offer to try again or slot may be gone
            keyboard = [[
                InlineKeyboardButton(
                    "🔄 Try Again",
                    callback_data=f"book:{watch_id}:{config_token}:{date_str}"
                )
            ]]
            
            await query.edit_message_text(
                f"❌ **Booking Failed**\n\n"
                f"{result.error_message or 'The table may no longer be available.'}\n\n"
                "The slot might have been taken. I'll keep watching for more availability!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    
    except ResyError as e:
        await query.edit_message_text(
            f"❌ Booking error: {e.message}\n\n"
            "Please try again or book directly on Resy."
        )
    except Exception as e:
        await query.edit_message_text(
            "❌ Something went wrong. Please try booking directly on Resy."
        )


async def dismiss_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Dismiss an availability alert."""
    query = update.callback_query
    await query.answer("Dismissed")
    
    await query.edit_message_text(
        "Alert dismissed. I'll keep watching for more availability!"
    )


def setup_booking_handlers(application) -> None:
    """Register booking handlers with the application."""
    application.add_handler(
        CallbackQueryHandler(book_slot, pattern=r"^book:")
    )
    application.add_handler(
        CallbackQueryHandler(dismiss_alert, pattern=r"^dismiss:")
    )

