"""Watch management handlers for /watch and /watches commands."""

import re
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from resnype.db.queries import UserQueries, WatchQueries

# Conversation states for watch creation
WATCH_DATE, WATCH_PARTY_SIZE, WATCH_TIME_PREF = range(3)


async def watch_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the watch creation flow, or prompt to search first."""
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
            "Then select it to create a watch."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        f"📅 **Creating watch for: {venue_name}**\n\n"
        "What date(s) are you looking for?\n\n"
        "Single date: `2024-12-25`\n"
        "Date range: `2024-12-25 to 2024-12-30`",
        parse_mode="Markdown",
    )
    return WATCH_DATE


def parse_date_input(text: str) -> list[date] | None:
    """
    Parse date input - single date or range.
    Returns list of dates, or None if invalid.

    Formats:
      - 2024-12-25
      - 2024-12-25 to 2024-12-30
      - 2024-12-25 - 2024-12-30
    """
    text = text.strip()

    # Check for date range (supports "to", "-", or "–")
    range_match = re.match(
        r"(\d{4}-\d{2}-\d{2})\s*(?:to|-|–)\s*(\d{4}-\d{2}-\d{2})", text, re.IGNORECASE
    )

    if range_match:
        try:
            start = datetime.strptime(range_match.group(1), "%Y-%m-%d").date()
            end = datetime.strptime(range_match.group(2), "%Y-%m-%d").date()

            if end < start:
                start, end = end, start  # Swap if reversed

            # Generate all dates in range (max 14 days)
            days = (end - start).days + 1
            if days > 14:
                return None  # Too many days

            return [start + timedelta(days=i) for i in range(days)]
        except ValueError:
            return None

    # Single date
    try:
        return [datetime.strptime(text, "%Y-%m-%d").date()]
    except ValueError:
        return None


async def watch_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date input for watch."""
    text = update.message.text.strip()

    # Handle callback from venue selection (date prompt shown there)
    if not context.user_data.get("watch_venue_id"):
        await update.message.reply_text("Please start with /search first.")
        return ConversationHandler.END

    dates = parse_date_input(text)

    if dates is None:
        await update.message.reply_text(
            "Invalid date format.\n\n"
            "Single date: `YYYY-MM-DD`\n"
            "Date range: `YYYY-MM-DD to YYYY-MM-DD` (max 14 days)",
            parse_mode="Markdown",
        )
        return WATCH_DATE

    # Check dates are not in the past
    today = date.today()
    dates = [d for d in dates if d >= today]

    if not dates:
        await update.message.reply_text(
            "All dates are in the past. Please enter future date(s):"
        )
        return WATCH_DATE

    context.user_data["watch_dates"] = dates

    # Ask for party size
    keyboard = [
        [
            InlineKeyboardButton("1", callback_data="party:1"),
            InlineKeyboardButton("2", callback_data="party:2"),
            InlineKeyboardButton("3", callback_data="party:3"),
            InlineKeyboardButton("4", callback_data="party:4"),
        ],
        [
            InlineKeyboardButton("5", callback_data="party:5"),
            InlineKeyboardButton("6", callback_data="party:6"),
            InlineKeyboardButton("7+", callback_data="party:7"),
        ],
    ]

    date_summary = dates[0].strftime("%b %d")
    if len(dates) > 1:
        date_summary = f"{dates[0].strftime('%b %d')} - {dates[-1].strftime('%b %d')} ({len(dates)} days)"

    await update.message.reply_text(
        f"📅 {date_summary}\n\n👥 How many guests?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return WATCH_PARTY_SIZE


async def watch_party_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle party size selection."""
    query = update.callback_query
    await query.answer()

    _, size = query.data.split(":")
    context.user_data["watch_party_size"] = int(size)

    # Ask for time preference
    keyboard = [
        [
            InlineKeyboardButton("🌅 Early (5-6pm)", callback_data="time:17:00-18:00"),
            InlineKeyboardButton("🌆 Prime (7-8pm)", callback_data="time:19:00-20:00"),
        ],
        [
            InlineKeyboardButton("🌙 Late (9pm+)", callback_data="time:21:00-23:00"),
            InlineKeyboardButton("🕐 Any time", callback_data="time:any"),
        ],
    ]

    await query.edit_message_text(
        "⏰ What time do you prefer?", reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WATCH_TIME_PREF


async def watch_time_pref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle time preference and create the watch(es)."""
    query = update.callback_query
    await query.answer()

    _, time_range = query.data.split(":", 1)

    # Parse time range
    time_earliest = None
    time_latest = None

    if time_range != "any":
        start, end = time_range.split("-")
        time_earliest = datetime.strptime(start, "%H:%M").time()
        time_latest = datetime.strptime(end, "%H:%M").time()

    # Get user
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)

    # Get dates (single or range)
    dates = context.user_data.get("watch_dates", [])
    venue_id = context.user_data["watch_venue_id"]
    venue_name = context.user_data["watch_venue_name"]
    party_size = context.user_data["watch_party_size"]

    # Create a watch for each date
    watches_created = []
    for watch_date in dates:
        watch = await WatchQueries.create(
            user_id=user.id,
            venue_id=venue_id,
            venue_name=venue_name,
            watch_date=watch_date,
            party_size=party_size,
            time_earliest=time_earliest,
            time_latest=time_latest,
        )
        watches_created.append(watch)

    # Format confirmation
    time_str = "Any time"
    if time_earliest and time_latest:
        time_str = (
            f"{time_earliest.strftime('%I:%M %p')} - {time_latest.strftime('%I:%M %p')}"
        )

    if len(watches_created) == 1:
        watch = watches_created[0]
        date_str = watch.date.strftime("%A, %B %d, %Y")
    else:
        date_str = f"{dates[0].strftime('%b %d')} - {dates[-1].strftime('%b %d')} ({len(dates)} days)"

    await query.edit_message_text(
        f"✅ **{'Watch' if len(watches_created) == 1 else f'{len(watches_created)} Watches'} created!**\n\n"
        f"🍽 {venue_name}\n"
        f"📅 {date_str}\n"
        f"👥 {party_size} guests\n"
        f"⏰ {time_str}\n\n"
        f"I'll notify you when a table becomes available!",
        parse_mode="Markdown",
    )

    # Clear context
    for key in [
        "watch_venue_id",
        "watch_venue_name",
        "watch_dates",
        "watch_party_size",
    ]:
        context.user_data.pop(key, None)

    return ConversationHandler.END


async def watch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel watch creation."""
    for key in [
        "watch_venue_id",
        "watch_venue_name",
        "watch_dates",
        "watch_party_size",
    ]:
        context.user_data.pop(key, None)

    if update.callback_query:
        await update.callback_query.edit_message_text("Watch creation cancelled.")
    else:
        await update.message.reply_text("Watch creation cancelled.")

    return ConversationHandler.END


async def list_watches(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /watches command - list active watches."""
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /login first.")
        return

    watches = await WatchQueries.get_user_watches(update.effective_user.id)

    if not watches:
        await update.message.reply_text(
            "You don't have any active watches.\n"
            "Use /search to find a restaurant and set one up!"
        )
        return

    text_parts = ["📋 **Your Active Watches:**\n"]
    keyboard = []

    for watch in watches:
        time_str = "Any time"
        if watch.time_earliest and watch.time_latest:
            time_str = f"{watch.time_earliest.strftime('%I:%M%p')}-{watch.time_latest.strftime('%I:%M%p')}"

        text_parts.append(
            f"• **{watch.venue_name}**\n"
            f"  📅 {watch.date.strftime('%b %d')} | 👥 {watch.party_size} | ⏰ {time_str}"
        )

        keyboard.append(
            [
                InlineKeyboardButton(
                    f"❌ Remove: {watch.venue_name[:20]}",
                    callback_data=f"unwatch:{watch.id}",
                )
            ]
        )

    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None,
    )


async def unwatch(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unwatch button press."""
    query = update.callback_query
    await query.answer()

    _, watch_id = query.data.split(":")
    watch_id = int(watch_id)

    success = await WatchQueries.deactivate(watch_id, update.effective_user.id)

    if success:
        await query.edit_message_text(
            "✅ Watch removed.\nUse /watches to see your remaining watches."
        )
    else:
        await query.edit_message_text("❌ Watch not found or already removed.")


def setup_watch_handlers(application) -> None:
    """Register watch handlers with the application."""

    # Watch creation conversation
    watch_conv = ConversationHandler(
        entry_points=[
            CommandHandler("watch", watch_start),
        ],
        states={
            WATCH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, watch_date_input)
            ],
            WATCH_PARTY_SIZE: [
                CallbackQueryHandler(watch_party_size, pattern=r"^party:")
            ],
            WATCH_TIME_PREF: [CallbackQueryHandler(watch_time_pref, pattern=r"^time:")],
        },
        fallbacks=[
            CommandHandler("cancel", watch_cancel),
            # Any other command exits the conversation
            MessageHandler(filters.COMMAND, watch_cancel),
        ],
        per_message=False,
    )

    application.add_handler(watch_conv)
    application.add_handler(CommandHandler("watches", list_watches))
    application.add_handler(CallbackQueryHandler(unwatch, pattern=r"^unwatch:"))
