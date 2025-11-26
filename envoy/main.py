"""Main entry point for the Envoy Telegram bot."""

import logging

# Configure logging (INFO for production, DEBUG for development)
import os
import sys
from pathlib import Path

from telegram import BotCommand, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from envoy.config import get_settings
from envoy.db import Database
from envoy.handlers import (
    setup_auth_handlers,
    setup_booking_handlers,
    setup_llm_handler,
    setup_search_handlers,
    setup_snipe_handlers,
    setup_watch_handlers,
)
from envoy.services import AvailabilityMonitor, Sniper

log_level = logging.DEBUG if os.getenv("DEV") else logging.INFO
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=log_level,
)
# Reduce noise from http libraries
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("aiohttp").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "👋 **Welcome to Envoy!**\n\n"
        "I'm your personal AI agent for booking reservations.\n\n"
        "**How it works:**\n"
        "1️⃣ Connect your Resy account with /login\n"
        "2️⃣ Tell me what you want (or use /search)\n"
        "3️⃣ I'll handle the rest - watches, snipes, booking\n\n"
        "**Commands:**\n"
        "/login - Connect your Resy account\n"
        "/search `<restaurant>` - Find restaurants\n"
        "/watches - View your active watches\n"
        "/snipes - View pending snipes\n"
        "/help - Show this message\n\n"
        "💬 Or just tell me what you need in plain English!",
        parse_mode="Markdown",
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    settings = get_settings()
    llm_text = ""
    if settings.llm_enabled:
        llm_text = (
            "\n**Natural Language Mode:** ✅ Enabled\n"
            "Just type naturally! e.g., 'Get me Carbone for 2 on Dec 15'\n"
            "/clear - Reset conversation context\n"
        )

    await update.message.reply_text(
        "🤖 **Envoy Commands**\n\n"
        "/start - Welcome message\n"
        "/login - Connect your Resy account\n"
        "/logout - Disconnect Resy account\n"
        "/search `<name>` - Search for restaurants\n"
        "/watch - Watch for cancellations\n"
        "/watches - View your active watches\n"
        "/snipe - Auto-book at release time\n"
        "/snipes - View pending snipes\n"
        "/cancel - Cancel current operation\n"
        "/help - Show this message\n"
        f"{llm_text}\n"
        "**Watch vs Snipe:**\n"
        "• Watch = monitors for cancellations (ongoing)\n"
        "• Snipe = grabs new slots at 9am release (one-shot)",
        parse_mode="Markdown",
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
        BotCommand("snipes", "View pending snipes"),
        BotCommand("help", "Show help message"),
    ]
    await application.bot.set_my_commands(commands)

    # Start availability monitor
    monitor = AvailabilityMonitor(application.bot)
    application.bot_data["monitor"] = monitor
    monitor.start()
    logger.info("Availability monitor started")

    # Start sniper service
    sniper = Sniper(application.bot)
    application.bot_data["sniper"] = sniper
    sniper.start()
    logger.info("Sniper service started")


async def post_shutdown(application: Application) -> None:
    """Run on shutdown."""
    # Stop monitor
    monitor = application.bot_data.get("monitor")
    if monitor:
        monitor.stop()

    # Stop sniper
    sniper = application.bot_data.get("sniper")
    if sniper:
        sniper.stop()

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
    setup_snipe_handlers(application)
    setup_booking_handlers(application)

    # LLM handler should be last (catch-all for natural language)
    setup_llm_handler(application)

    # Run the bot
    logger.info("Starting Envoy bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


def main_dev() -> None:
    """Start the bot with hot reload for development."""
    # Enable debug logging for development
    os.environ["DEV"] = "1"

    try:
        from watchfiles import run_process
    except ImportError:
        logger.error("watchfiles not installed. Run: uv sync")
        sys.exit(1)

    logger.info("Starting Envoy in development mode with hot reload...")

    # Watch the envoy package directory
    watch_path = Path(__file__).parent

    run_process(
        watch_path,
        target=main,
        callback=lambda changes: logger.info(f"Detected changes: {changes}"),
    )


if __name__ == "__main__":
    main()
