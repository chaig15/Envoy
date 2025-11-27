"""Search handlers for /search command."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from envoy.resy import ResyClient
from envoy.resy.client import ResyError

logger = logging.getLogger(__name__)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search command."""
    # Get search query from command args
    if not context.args:
        await update.message.reply_text(
            "Please provide a restaurant name.\nUsage: `/search carbone`",
            parse_mode="Markdown",
        )
        return

    query = " ".join(context.args)
    status_msg = await update.message.reply_text(f"🔍 Searching for '{query}'...")

    # Search doesn't require authentication - use client without token
    client = ResyClient()

    try:
        venues = await client.search_venues(query)

        if not venues:
            await status_msg.edit_text(
                f"No restaurants found for '{query}'.\nTry a different search term."
            )
            return

        # Build response with inline buttons
        text_parts = [f"🍽 **Results for '{query}':**\n"]
        keyboard = []

        for venue in venues[:8]:  # Limit to 8 results
            location = venue.display_location
            price = "💰" * (venue.price_range or 1)

            text_parts.append(f"• **{venue.name}**\n  {location} {price}")

            # Button to start watching this venue
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"📍 {venue.name}",
                        callback_data=f"venue:{venue.id}:{venue.name[:30]}",
                    )
                ]
            )

        await status_msg.edit_text(
            "\n".join(text_parts) + "\n\n_Select a restaurant:_",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except ResyError as e:
        await status_msg.edit_text(f"❌ Search failed: {e.message}")
    except Exception as e:
        logger.exception(f"Error in search: {e}")
        await status_msg.edit_text("❌ Something went wrong. Please try again.")
    finally:
        await client.close()


async def venue_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle venue selection from search results - show Watch vs Snipe options."""
    query = update.callback_query
    await query.answer()

    # Parse callback data: venue:{id}:{name}
    _, venue_id, venue_name = query.data.split(":", 2)
    venue_id = int(venue_id)

    # Store in user context for watch/snipe creation
    context.user_data["watch_venue_id"] = venue_id
    context.user_data["watch_venue_name"] = venue_name

    # Show Watch vs Snipe choice
    keyboard = [
        [
            InlineKeyboardButton(
                "👀 Watch for cancellations",
                callback_data=f"action:watch:{venue_id}",
            )
        ],
        [
            InlineKeyboardButton(
                "🎯 Snipe at release time",
                callback_data=f"action:snipe:{venue_id}",
            )
        ],
    ]

    await query.edit_message_text(
        f"**{venue_name}**\n\n"
        "What would you like to do?\n\n"
        "👀 **Watch** - Monitor for cancellations on already-released dates\n"
        "🎯 **Snipe** - Auto-book when new reservations open (e.g., 9am release)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


def setup_search_handlers(application) -> None:
    """Register search handlers with the application."""
    application.add_handler(CommandHandler("search", search))
    application.add_handler(CallbackQueryHandler(venue_selected, pattern=r"^venue:"))
    # Note: action:watch: and action:snipe: callbacks are handled by
    # ConversationHandler entry points in watch.py and snipe.py
