"""Search handlers for /search command."""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from resnype.db.queries import UserQueries
from resnype.resy import ResyClient
from resnype.resy.client import ResyError
from resnype.encryption import decrypt_token

logger = logging.getLogger(__name__)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command."""
    # Check if logged in
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user or not user.resy_token_encrypted:
        await update.message.reply_text(
            "Please /login first to search restaurants."
        )
        return

    # Get search query from command args
    if not context.args:
        await update.message.reply_text(
            "Please provide a restaurant name.\n"
            "Usage: `/search carbone`",
            parse_mode="Markdown"
        )
        return

    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Searching for '{query}'...")

    # Decrypt token and search
    token = decrypt_token(user.resy_token_encrypted)
    client = ResyClient(auth_token=token)

    try:
        venues = await client.search_venues(query)

        if not venues:
            await status_msg.edit_text(
                f"No restaurants found for '{query}'.\n"
                "Try a different search term."
            )
            return

        # Build response with inline buttons
        text_parts = [f"🍽 **Results for '{query}':**\n"]
        keyboard = []

        for venue in venues[:8]:  # Limit to 8 results
            location = venue.display_location
            price = "💰" * (venue.price_range or 1)

            text_parts.append(
                f"• **{venue.name}**\n"
                f"  {location} {price}"
            )

            # Button to start watching this venue
            keyboard.append([
                InlineKeyboardButton(
                    f"📍 {venue.name}",
                    callback_data=f"venue:{venue.id}:{venue.name[:30]}"
                )
            ])

        await status_msg.edit_text(
            "\n".join(text_parts) + "\n\n_Select a restaurant to watch:_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    except ResyError as e:
        await status_msg.edit_text(f"❌ Search failed: {e.message}")
    except Exception as e:
        logger.exception(f"Error in search: {e}")
        await status_msg.edit_text("❌ Something went wrong. Please try again.")
    finally:
        await client.close()


async def venue_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle venue selection from search results."""
    query = update.callback_query
    await query.answer()

    # Parse callback data: venue:{id}:{name}
    _, venue_id, venue_name = query.data.split(":", 2)
    venue_id = int(venue_id)

    # Store in user context for watch creation
    context.user_data["watch_venue_id"] = venue_id
    context.user_data["watch_venue_name"] = venue_name

    # Prompt for date
    await query.edit_message_text(
        f"📅 **Watching: {venue_name}**\n\n"
        "What date are you looking for?\n"
        "Enter in format: `YYYY-MM-DD` (e.g., `2024-12-25`)\n\n"
        "Or /cancel to stop.",
        parse_mode="Markdown"
    )


def setup_search_handlers(application) -> None:
    """Register search handlers with the application."""
    application.add_handler(CommandHandler("search", search))
    application.add_handler(
        CallbackQueryHandler(venue_selected, pattern=r"^venue:")
    )

