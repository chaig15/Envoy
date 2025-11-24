"""Watch management handlers for /watch and /watches commands."""

from datetime import datetime, date, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
)

from bot.db.queries import UserQueries, WatchQueries


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
        "What date are you looking for?\n"
        "Enter as `YYYY-MM-DD` (e.g., `2024-12-25`)",
        parse_mode="Markdown"
    )
    return WATCH_DATE


async def watch_date_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle date input for watch."""
    text = update.message.text.strip()
    
    # Handle callback from venue selection (date prompt shown there)
    if not context.user_data.get("watch_venue_id"):
        await update.message.reply_text("Please start with /search first.")
        return ConversationHandler.END
    
    try:
        watch_date = datetime.strptime(text, "%Y-%m-%d").date()
        
        if watch_date < date.today():
            await update.message.reply_text(
                "That date is in the past. Please enter a future date:"
            )
            return WATCH_DATE
        
        context.user_data["watch_date"] = watch_date
        
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
        
        await update.message.reply_text(
            "👥 How many guests?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return WATCH_PARTY_SIZE
        
    except ValueError:
        await update.message.reply_text(
            "Invalid date format. Please use `YYYY-MM-DD`:",
            parse_mode="Markdown"
        )
        return WATCH_DATE


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
        "⏰ What time do you prefer?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return WATCH_TIME_PREF


async def watch_time_pref(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle time preference and create the watch."""
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
    
    # Create the watch
    watch = await WatchQueries.create(
        user_id=user.id,
        venue_id=context.user_data["watch_venue_id"],
        venue_name=context.user_data["watch_venue_name"],
        watch_date=context.user_data["watch_date"],
        party_size=context.user_data["watch_party_size"],
        time_earliest=time_earliest,
        time_latest=time_latest,
    )
    
    # Format confirmation
    time_str = "Any time"
    if time_earliest and time_latest:
        time_str = f"{time_earliest.strftime('%I:%M %p')} - {time_latest.strftime('%I:%M %p')}"
    
    await query.edit_message_text(
        f"✅ **Watch created!**\n\n"
        f"🍽 {watch.venue_name}\n"
        f"📅 {watch.date.strftime('%A, %B %d, %Y')}\n"
        f"👥 {watch.party_size} guests\n"
        f"⏰ {time_str}\n\n"
        f"I'll notify you when a table becomes available!",
        parse_mode="Markdown"
    )
    
    # Clear context
    for key in ["watch_venue_id", "watch_venue_name", "watch_date", "watch_party_size"]:
        context.user_data.pop(key, None)
    
    return ConversationHandler.END


async def watch_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel watch creation."""
    for key in ["watch_venue_id", "watch_venue_name", "watch_date", "watch_party_size"]:
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
        
        keyboard.append([
            InlineKeyboardButton(
                f"❌ Remove: {watch.venue_name[:20]}",
                callback_data=f"unwatch:{watch.id}"
            )
        ])
    
    await update.message.reply_text(
        "\n".join(text_parts),
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard) if keyboard else None
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
            "✅ Watch removed.\n"
            "Use /watches to see your remaining watches."
        )
    else:
        await query.edit_message_text("❌ Watch not found or already removed.")


def setup_watch_handlers(application) -> None:
    """Register watch handlers with the application."""
    
    # Watch creation conversation - handles both /watch and date input after venue selection
    watch_conv = ConversationHandler(
        entry_points=[
            CommandHandler("watch", watch_start),
            MessageHandler(
                filters.Regex(r"^\d{4}-\d{2}-\d{2}$") & ~filters.COMMAND,
                watch_date_input
            ),
        ],
        states={
            WATCH_DATE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, watch_date_input)
            ],
            WATCH_PARTY_SIZE: [
                CallbackQueryHandler(watch_party_size, pattern=r"^party:")
            ],
            WATCH_TIME_PREF: [
                CallbackQueryHandler(watch_time_pref, pattern=r"^time:")
            ],
        },
        fallbacks=[
            CommandHandler("cancel", watch_cancel),
        ],
        per_message=False,
    )
    
    application.add_handler(watch_conv)
    application.add_handler(CommandHandler("watches", list_watches))
    application.add_handler(CallbackQueryHandler(unwatch, pattern=r"^unwatch:"))

