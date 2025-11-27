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
    # Always recreate to pick up config changes
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

    # Skip if user is in an active conversation flow
    # ConversationHandler has higher priority (group 0) than LLM handler (group 100),
    # so ConversationHandler will process messages first. This check is a safety measure.
    #
    # Note: If user types natural language mid-conversation (e.g., "get me carbone for 2"),
    # ConversationHandler will process it first and show an error. LLM handler won't get it
    # because ConversationHandler consumed the update. But we check here just in case.
    active_conversation_keys = [
        "resy_phone",  # Login flow - cleared after completion
        "resy_challenge_id",  # Login flow - cleared after completion
        "resy_claim_token",  # Login flow - cleared after completion
        "watch_dates",  # Watch flow - only set during active watch creation
        "watch_party_size",  # Watch flow - only set during active watch creation
        "snipe_date",  # Snipe flow - set after user enters date
        "snipe_party_size",  # Snipe flow - only set during active snipe creation
        "snipe_release_date",  # Snipe flow - only set during active snipe creation
        "snipe_release_time",  # Snipe flow - only set during active snipe creation
        "snipe_release_timezone",  # Snipe flow - only set during active snipe creation
    ]

    # Check for active conversation state
    # Note: watch_venue_id persists after search, so we don't check it alone
    # If user is in SNIPE_DATE state but hasn't entered date yet, ConversationHandler
    # will still process the message first (higher priority), so this is just a safety check
    if any(key in context.user_data for key in active_conversation_keys):
        return  # Let conversation handlers process this message

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
    try:
        response = await orchestrator.handle_message(
            telegram_id=update.effective_user.id,
            user_message=update.message.text,
            user=user,
        )

        # Send response (try Markdown first, fall back to plain text on error)
        try:
            await update.message.reply_text(response, parse_mode="Markdown")
        except Exception:
            # If Markdown parsing fails, send as plain text
            await update.message.reply_text(response)
    except Exception as e:
        logger.exception(f"Error handling LLM message: {e}")
        # Send error as plain text (no Markdown to avoid parsing issues)
        await update.message.reply_text(f"Sorry, something went wrong: {str(e)}")


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
