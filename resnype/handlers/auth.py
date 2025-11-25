"""Authentication handlers for /login and /logout commands."""

import logging
import re

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from resnype.db.queries import UserQueries
from resnype.resy import ResyClient
from resnype.resy.client import ResyError
from resnype.encryption import encrypt_token

logger = logging.getLogger(__name__)


# Conversation states
PHONE, CODE = range(2)


def normalize_phone(phone: str) -> str | None:
    """
    Normalize phone number to E.164 format (+1XXXXXXXXXX for US).
    Returns None if invalid.
    """
    # Strip all non-digit characters except leading +
    digits = re.sub(r"[^\d]", "", phone)
    
    # Handle US numbers (10 digits without country code)
    if len(digits) == 10:
        return f"+1{digits}"
    
    # Handle numbers with country code (11+ digits)
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    
    # Already has full international format
    if len(digits) >= 11:
        return f"+{digits}"
    
    return None


async def login_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start the login flow."""
    # Check if user is already logged in
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)
    if user and user.resy_token_encrypted:
        await update.message.reply_text(
            "You're already logged in to Resy! Use /logout first if you want to switch accounts."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Let's connect your Resy account.\n\n"
        "Please enter your phone number (the one linked to your Resy account):"
    )
    return PHONE


async def login_phone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle phone number input and request SMS code."""
    raw_phone = update.message.text.strip()
    phone = normalize_phone(raw_phone)
    
    if not phone:
        await update.message.reply_text(
            "That doesn't look like a valid phone number.\n"
            "Please enter a 10-digit US number or include your country code:"
        )
        return PHONE

    # Store phone in context for verification step
    context.user_data["resy_phone"] = phone
    
    # Request SMS code from Resy
    status_msg = await update.message.reply_text("📱 Sending verification code...")
    
    client = ResyClient()
    try:
        await client.request_sms_code(phone)
        
        await status_msg.edit_text(
            f"✅ Code sent to {phone}!\n\n"
            "Please enter the 6-digit code you received:"
        )
        return CODE
        
    except ResyError as e:
        logger.error(f"Resy error sending SMS code: {e.message}")
        await status_msg.edit_text(
            f"❌ Failed to send code: {e.message}\n\n"
            "Please check your phone number and try /login again."
        )
        context.user_data.pop("resy_phone", None)
        return ConversationHandler.END
    except Exception as e:
        logger.exception(f"Error sending SMS code: {e}")
        await status_msg.edit_text(
            "❌ Something went wrong sending the code.\n"
            "Please try /login again."
        )
        context.user_data.pop("resy_phone", None)
        return ConversationHandler.END
    finally:
        await client.close()


async def login_code(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle SMS code input and complete login."""
    code = update.message.text.strip()
    phone = context.user_data.get("resy_phone", "")
    
    # Basic validation - codes are typically 6 digits
    if not re.match(r"^\d{4,6}$", code):
        await update.message.reply_text(
            "Please enter the numeric code from your SMS:"
        )
        return CODE

    status_msg = await update.effective_chat.send_message("🔐 Verifying code...")

    client = ResyClient()
    try:
        # Verify code with Resy
        auth = await client.verify_sms_code(phone, code)

        # Ensure user exists in database
        await UserQueries.get_or_create(update.effective_user.id)

        # Store encrypted token
        encrypted_token = encrypt_token(auth.token)
        await UserQueries.update_resy_token(
            update.effective_user.id, encrypted_token, auth.payment_method_id
        )

        # Success message
        name = auth.first_name or "there"
        await status_msg.edit_text(
            f"✅ Welcome, {name}! You're now connected to Resy.\n\n"
            "You can now:\n"
            "• /search - Find restaurants\n"
            "• /watch - Set up availability alerts\n"
            "• /watches - View your active watches"
        )

    except ResyError as e:
        logger.error(f"Resy error verifying code: {e.message}")
        await status_msg.edit_text(
            f"❌ Verification failed: {e.message}\n\n"
            "Please try /login again to get a new code."
        )
    except Exception as e:
        logger.exception(f"Error verifying code: {e}")
        await status_msg.edit_text("❌ Something went wrong. Please try /login again.")
    finally:
        await client.close()

    # Clear stored phone
    context.user_data.pop("resy_phone", None)
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login flow."""
    context.user_data.pop("resy_phone", None)
    await update.message.reply_text("Login cancelled.")
    return ConversationHandler.END


async def logout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /logout command."""
    user = await UserQueries.get_by_telegram_id(update.effective_user.id)

    if not user or not user.resy_token_encrypted:
        await update.message.reply_text("You're not logged in.")
        return

    await UserQueries.clear_resy_token(update.effective_user.id)
    await update.message.reply_text(
        "✅ You've been logged out of Resy.\nUse /login to connect again."
    )


def setup_auth_handlers(application) -> None:
    """Register authentication handlers with the application."""

    # Login conversation handler
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_phone)],
            CODE: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_code)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )

    application.add_handler(login_handler)
    application.add_handler(CommandHandler("logout", logout))
