"""Snipe handlers for /snipe and /snipes commands."""

import logging
import re
from datetime import date, datetime, time, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from resnype.db.queries import SnipeQueries, UserQueries

logger = logging.getLogger(__name__)

# Conversation states
(
    SNIPE_DATE,
    SNIPE_PARTY_SIZE,
    SNIPE_DAYS_ADVANCE,
    SNIPE_RELEASE_TIME,
    SNIPE_CUSTOM_TIME,
) = range(5)


async def snipe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the snipe creation flow."""
    # Check if logged in
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user or not user.resy_token_encrypted:
        await update.message.reply_text("Please /login first.")
        return ConversationHandler.END

    # Check if venue was selected from search
    venue_id = context.user_data.get("watch_venue_id")
    venue_name = context.user_data.get("watch_venue_name")

    if not venue_id:
        await update.message.reply_text(
            "First, search for a restaurant with /search\n"
            "Then select it to create a snipe."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"🎯 **Setting up snipe for: {venue_name}**\n\n"
        "What date do you want to snipe?\n"
        "Enter as `YYYY-MM-DD` (e.g., `2025-01-15`)\n\n"
        "I'll auto-book at 9:00 AM EST when reservations open!",
        parse_mode="Markdown",
    )
    return SNIPE_DATE


async def snipe_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date input for snipe."""
    text = update.message.text.strip()

    if not context.user_data.get("watch_venue_id"):
        await update.message.reply_text("Please start with /search first.")
        return ConversationHandler.END

    try:
        target_date = datetime.strptime(text, "%Y-%m-%d").date()

        if target_date <= date.today():
            await update.message.reply_text(
                "That date has already passed or is today.\n"
                "Snipes are for future reservation releases.\n"
                "Please enter a future date:"
            )
            return SNIPE_DATE

        context.user_data["snipe_date"] = target_date

        # Ask for party size
        keyboard = [
            [
                InlineKeyboardButton("1", callback_data="snipe_party:1"),
                InlineKeyboardButton("2", callback_data="snipe_party:2"),
                InlineKeyboardButton("3", callback_data="snipe_party:3"),
                InlineKeyboardButton("4", callback_data="snipe_party:4"),
            ],
            [
                InlineKeyboardButton("5", callback_data="snipe_party:5"),
                InlineKeyboardButton("6", callback_data="snipe_party:6"),
                InlineKeyboardButton("7+", callback_data="snipe_party:7"),
            ],
        ]

        await update.message.reply_text(
            f"📅 Target date: {target_date.strftime('%B %d, %Y')}\n\n"
            "👥 How many guests?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return SNIPE_PARTY_SIZE

    except ValueError:
        await update.message.reply_text(
            "Invalid date format. Please use `YYYY-MM-DD`:",
            parse_mode="Markdown",
        )
        return SNIPE_DATE


async def snipe_party_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle party size selection, then ask about days in advance."""
    query = update.callback_query
    await query.answer()

    _, size = query.data.split(":")
    context.user_data["snipe_party_size"] = int(size)

    target_date = context.user_data["snipe_date"]

    # Calculate common options (only show if release date would be today or future)
    today = date.today()
    keyboard = []

    # Common advance booking windows
    for days in [7, 14, 21, 30]:
        release_date = target_date - timedelta(days=days)
        if release_date >= today:
            keyboard.append(
                [
                    InlineKeyboardButton(
                        f"{days} days (releases {release_date.strftime('%b %d')})",
                        callback_data=f"snipe_advance:{days}",
                    )
                ]
            )

    # Always offer "tomorrow" as release (today + 1)
    if target_date > today:
        days_until = (target_date - today).days
        keyboard.append(
            [
                InlineKeyboardButton(
                    f"Tomorrow at open ({days_until} days advance)",
                    callback_data="snipe_advance:tomorrow",
                )
            ]
        )

    await query.edit_message_text(
        f"👥 Party size: {size}\n\n"
        "📆 How many days in advance does this restaurant release?\n\n"
        "Most popular spots are 7-14 days. Check their Resy page if unsure.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SNIPE_DAYS_ADVANCE


async def snipe_days_advance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle days in advance selection."""
    query = update.callback_query
    await query.answer()

    _, value = query.data.split(":")
    target_date = context.user_data["snipe_date"]
    today = date.today()

    if value == "tomorrow":
        release_date = today + timedelta(days=1)
    else:
        days = int(value)
        release_date = target_date - timedelta(days=days)

    context.user_data["snipe_release_date"] = release_date

    # Now ask about release time
    keyboard = [
        [
            InlineKeyboardButton(
                "🕘 9:00 AM EST (default)", callback_data="snipe_time:default"
            ),
        ],
        [
            InlineKeyboardButton("⏰ Custom time", callback_data="snipe_time:custom"),
        ],
    ]

    await query.edit_message_text(
        f"📆 Snipe will run on: {release_date.strftime('%A, %B %d')}\n\n"
        "⏰ What time do reservations open?\n\n"
        "Most restaurants release at 9:00 AM EST.",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return SNIPE_RELEASE_TIME


async def snipe_release_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle release time selection."""
    query = update.callback_query
    await query.answer()

    _, choice = query.data.split(":")

    if choice == "default":
        # Use default 9am EST
        context.user_data["snipe_release_time"] = time(9, 0)
        context.user_data["snipe_release_timezone"] = "America/New_York"
        return await create_snipe(update, context)
    else:
        # Ask for custom time
        await query.edit_message_text(
            "Enter the release time:\n\n"
            "Examples:\n"
            "• `9:00 AM` or `09:00`\n"
            "• `10:00 AM` or `10:00`\n"
            "• `12:00 PM` or `12:00`\n\n"
            "All times are assumed EST.",
            parse_mode="Markdown",
        )
        return SNIPE_CUSTOM_TIME


async def snipe_custom_time(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom time input."""
    text = update.message.text.strip().upper()

    # Parse various time formats
    parsed_time = None

    # Try "HH:MM AM/PM" format
    match = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", text)
    if match:
        hour = int(match.group(1))
        minute = int(match.group(2))
        period = match.group(3)

        if period == "PM" and hour != 12:
            hour += 12
        elif period == "AM" and hour == 12:
            hour = 0

        if 0 <= hour <= 23 and 0 <= minute <= 59:
            parsed_time = time(hour, minute)

    if not parsed_time:
        await update.message.reply_text(
            "Invalid time format. Please enter like `9:00 AM` or `10:00`:",
            parse_mode="Markdown",
        )
        return SNIPE_CUSTOM_TIME

    context.user_data["snipe_release_time"] = parsed_time
    context.user_data["snipe_release_timezone"] = "America/New_York"

    return await create_snipe(update, context)


async def create_snipe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Create the snipe after all info collected."""
    # Get user
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)

    venue_id = context.user_data["watch_venue_id"]
    venue_name = context.user_data["watch_venue_name"]
    target_date = context.user_data["snipe_date"]
    release_date = context.user_data["snipe_release_date"]
    party_size = context.user_data["snipe_party_size"]
    release_time = context.user_data["snipe_release_time"]
    release_timezone = context.user_data["snipe_release_timezone"]

    # Create the snipe
    snipe = await SnipeQueries.create(
        user_id=user.id,
        venue_id=venue_id,
        venue_name=venue_name,
        target_date=target_date,
        release_date=release_date,
        party_size=party_size,
        release_time=release_time,
        release_timezone=release_timezone,
    )

    # Format time for display
    hour = release_time.hour
    minute = release_time.minute
    period = "AM" if hour < 12 else "PM"
    display_hour = hour if hour <= 12 else hour - 12
    if display_hour == 0:
        display_hour = 12
    time_str = f"{display_hour}:{minute:02d} {period} EST"

    message = (
        f"🎯 **Snipe scheduled!**\n\n"
        f"🍽 {snipe.venue_name}\n"
        f"📅 Dinner: {snipe.target_date.strftime('%A, %B %d, %Y')}\n"
        f"👥 {snipe.party_size} guests\n\n"
        f"🚀 Snipe runs: {snipe.release_date.strftime('%b %d')} at {time_str}\n\n"
        f"I'll auto-book the first available slot!\n\n"
        f"Use /snipes to view or cancel pending snipes."
    )

    if update.callback_query:
        await update.callback_query.edit_message_text(message, parse_mode="Markdown")
    else:
        await update.message.reply_text(message, parse_mode="Markdown")

    # Clear context
    for key in [
        "watch_venue_id",
        "watch_venue_name",
        "snipe_date",
        "snipe_release_date",
        "snipe_party_size",
        "snipe_release_time",
        "snipe_release_timezone",
    ]:
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def snipe_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel snipe creation."""
    for key in [
        "watch_venue_id",
        "watch_venue_name",
        "snipe_date",
        "snipe_release_date",
        "snipe_party_size",
        "snipe_release_time",
        "snipe_release_timezone",
    ]:
        context.user_data.pop(key, None)

    if update.callback_query:
        await update.callback_query.edit_message_text("Snipe creation cancelled.")
    else:
        await update.message.reply_text("Snipe creation cancelled.")

    return ConversationHandler.END


async def list_snipes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /snipes command - list pending snipes."""
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /login first.")
        return

    snipes = await SnipeQueries.get_user_snipes(update.effective_user.id)

    if not snipes:
        await update.message.reply_text(
            "You don't have any pending snipes.\n"
            "Use /search to find a restaurant, then /snipe to set one up!"
        )
        return

    text_parts = ["🎯 **Your Pending Snipes:**\n"]
    keyboard = []

    for snipe in snipes:
        # Format release time
        hour = snipe.release_time.hour
        minute = snipe.release_time.minute
        period = "AM" if hour < 12 else "PM"
        display_hour = hour if hour <= 12 else hour - 12
        if display_hour == 0:
            display_hour = 12
        time_str = f"{display_hour}:{minute:02d} {period}"

        text_parts.append(
            f"• **{snipe.venue_name}**\n"
            f"  📅 Dinner: {snipe.target_date.strftime('%b %d')} | 👥 {snipe.party_size}\n"
            f"  🚀 Snipe: {snipe.release_date.strftime('%b %d')} at {time_str} EST"
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"❌ Cancel: {snipe.venue_name[:20]}",
                    callback_data=f"cancel_snipe:{snipe.id}",
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def cancel_snipe_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle cancel snipe button press."""
    query = update.callback_query
    await query.answer()

    _, snipe_id = query.data.split(":")
    snipe_id = int(snipe_id)

    success = await SnipeQueries.cancel(snipe_id, update.effective_user.id)

    if success:
        await query.edit_message_text(
            "✅ Snipe cancelled.\nUse /snipes to see your remaining snipes."
        )
    else:
        await query.edit_message_text("❌ Snipe not found or already executed.")


def setup_snipe_handlers(application) -> None:
    """Register snipe handlers with the application."""

    # Snipe creation conversation
    snipe_conv = ConversationHandler(
        entry_points=[CommandHandler("snipe", snipe_start)],
        states={
            SNIPE_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, snipe_date_input)
            ],
            SNIPE_PARTY_SIZE: [
                CallbackQueryHandler(snipe_party_size, pattern=r"^snipe_party:")
            ],
            SNIPE_DAYS_ADVANCE: [
                CallbackQueryHandler(snipe_days_advance, pattern=r"^snipe_advance:")
            ],
            SNIPE_RELEASE_TIME: [
                CallbackQueryHandler(snipe_release_time, pattern=r"^snipe_time:")
            ],
            SNIPE_CUSTOM_TIME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, snipe_custom_time)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", snipe_cancel),
            # Any other command exits the conversation
            MessageHandler(filters.COMMAND, snipe_cancel),
        ],
    )

    application.add_handler(snipe_conv)
    application.add_handler(CommandHandler("snipes", list_snipes))
    application.add_handler(
        CallbackQueryHandler(cancel_snipe_callback, pattern=r"^cancel_snipe:")
    )
