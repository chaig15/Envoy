"""Handler for natural language messages via LLM."""

import logging
from typing import Optional

from telegram import Update
from telegram.ext import ContextTypes, MessageHandler, filters

from envoy.config import get_settings
from envoy.db.queries import UserQueries

logger = logging.getLogger(__name__)

# Lazy-loaded orchestrator
_orchestrator: Optional["LLMOrchestrator"] = None  # noqa: F821


def get_orchestrator():
    """Get or create the LLM orchestrator (lazy loaded)."""
    global _orchestrator
    if _orchestrator is None:
        from envoy.llm import LLMOrchestrator

        _orchestrator = LLMOrchestrator()
    return _orchestrator


async def handle_natural_language(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """
    Handle natural language messages when LLM mode is enabled.

    This catches all non-command text messages and routes them through
    the LLM orchestrator for intent detection and tool execution.
    """
    settings = get_settings()

    # Only handle if LLM is enabled
    if not settings.llm_enabled:
        return

    # Skip if it's a command
    if update.message.text.startswith("/"):
        return

    # Get user from database
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if not user:
        await update.message.reply_text(
            "Please /login first to use natural language mode."
        )
        return

    if not user.resy_token_encrypted:
        await update.message.reply_text("Please /login to your Resy account first.")
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    # Process through LLM
    orchestrator = get_orchestrator()
    response = await orchestrator.handle_message(
        telegram_id=update.effective_user.id,
        user_message=update.message.text,
        user=user,
    )

    # Send response
    await update.message.reply_text(response, parse_mode="Markdown")


async def clear_context(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /clear command to reset conversation context."""
    orchestrator = get_orchestrator()
    await orchestrator.clear_history(update.effective_user.id)
    await update.message.reply_text("🧹 Conversation context cleared!")


def setup_llm_handler(application) -> None:
    """Register LLM handlers with the application."""
    settings = get_settings()

    if not settings.llm_enabled:
        logger.info("LLM mode disabled (set LLM_ENABLED=true to enable)")
        return

    logger.info(f"LLM mode enabled with provider: {settings.llm_provider}")

    # Catch-all for non-command text messages
    # Must be added LAST so command handlers take priority
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_natural_language,
        ),
        group=100,  # High group number = low priority
    )

    # Add /clear command
    from telegram.ext import CommandHandler

    application.add_handler(CommandHandler("clear", clear_context))
