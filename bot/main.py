"""Main entry point for the Resnype Telegram bot."""

import asyncio
import logging
from telegram import Update, BotCommand
from telegram.ext import Application, CommandHandler, ContextTypes

from bot.config import get_settings
from bot.db import Database
from bot.handlers import (
    setup_auth_handlers,
    setup_search_handlers,
    setup_watch_handlers,
    setup_booking_handlers,
)
from bot.services import AvailabilityMonitor


# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "👋 **Welcome to Resnype!**\n\n"
        "I help you snag hard-to-get restaurant reservations on Resy.\n\n"
        "**How it works:**\n"
        "1️⃣ Connect your Resy account with /login\n"
        "2️⃣ Search for a restaurant with /search\n"
        "3️⃣ Set up a watch for the date you want\n"
        "4️⃣ I'll notify you instantly when a table opens!\n"
        "5️⃣ One-click to book it before anyone else\n\n"
        "**Commands:**\n"
        "/login - Connect your Resy account\n"
        "/search `<restaurant>` - Find restaurants\n"
        "/watches - View your active watches\n"
        "/help - Show this message",
        parse_mode="Markdown"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "🍽 **Resnype Commands**\n\n"
        "/start - Welcome message\n"
        "/login - Connect your Resy account\n"
        "/logout - Disconnect Resy account\n"
        "/search `<name>` - Search for restaurants\n"
        "/watches - View your active watches\n"
        "/cancel - Cancel current operation\n"
        "/help - Show this message\n\n"
        "**Tips:**\n"
        "• Set watches for dates 1-2 weeks out\n"
        "• Popular spots release cancellations throughout the day\n"
        "• Book quickly when you get an alert!",
        parse_mode="Markdown"
    )


async def post_init(application: Application) -> None:
    """Run after the application is initialized."""
    # Connect to database
    await Database.connect()
    logger.info("Database connected")
    
    # Set bot commands for the menu
    commands = [
        BotCommand("start", "Welcome message"),
        BotCommand("login", "Connect your Resy account"),
        BotCommand("logout", "Disconnect Resy account"),
        BotCommand("search", "Search for restaurants"),
        BotCommand("watches", "View your active watches"),
        BotCommand("help", "Show help message"),
    ]
    await application.bot.set_my_commands(commands)
    
    # Start availability monitor
    monitor = AvailabilityMonitor(application.bot)
    application.bot_data["monitor"] = monitor
    monitor.start()
    logger.info("Availability monitor started")


async def post_shutdown(application: Application) -> None:
    """Run on shutdown."""
    # Stop monitor
    monitor = application.bot_data.get("monitor")
    if monitor:
        monitor.stop()
    
    # Disconnect database
    await Database.disconnect()
    logger.info("Shutdown complete")


def main() -> None:
    """Start the bot."""
    settings = get_settings()
    
    # Build application
    application = (
        Application.builder()
        .token(settings.telegram_bot_token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )
    
    # Register handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    
    setup_auth_handlers(application)
    setup_search_handlers(application)
    setup_watch_handlers(application)
    setup_booking_handlers(application)
    
    # Run the bot
    logger.info("Starting Resnype bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

