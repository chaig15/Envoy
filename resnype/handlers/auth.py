"""Authentication handlers for /login and /logout commands."""

from telegram import Update
from telegram.ext import (
    ContextTypes,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
)

from resnype.db import Database
from resnype.db.queries import UserQueries
from resnype.resy import ResyClient
from resnype.resy.client import ResyError
from resnype.encryption import encrypt_token, decrypt_token


# Conversation states
EMAIL, PASSWORD = range(2)


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
        "Please enter your Resy email address:"
    )
    return EMAIL


async def login_email(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle email input."""
    email = update.message.text.strip()
    
    if "@" not in email:
        await update.message.reply_text(
            "That doesn't look like a valid email. Please try again:"
        )
        return EMAIL
    
    # Store email in context for next step
    context.user_data["resy_email"] = email
    
    await update.message.reply_text(
        "Got it! Now please enter your Resy password:\n\n"
        "_(Your message will be deleted for security)_",
        parse_mode="Markdown"
    )
    return PASSWORD


async def login_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle password input and complete login."""
    password = update.message.text
    email = context.user_data.get("resy_email", "")
    
    # Delete the password message for security
    try:
        await update.message.delete()
    except Exception:
        pass  # May fail if bot doesn't have delete permission
    
    # Send a processing message
    status_msg = await update.effective_chat.send_message("🔐 Logging in to Resy...")
    
    try:
        # Authenticate with Resy
        client = ResyClient()
        auth = await client.login(email, password)
        await client.close()
        
        # Ensure user exists in database
        await UserQueries.get_or_create(update.effective_user.id)
        
        # Store encrypted token
        encrypted_token = encrypt_token(auth.token)
        await UserQueries.update_resy_token(
            update.effective_user.id,
            encrypted_token,
            auth.payment_method_id
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
        await status_msg.edit_text(
            f"❌ Login failed: {e.message}\n\n"
            "Please check your credentials and try /login again."
        )
    except Exception as e:
        await status_msg.edit_text(
            "❌ Something went wrong. Please try /login again."
        )
    
    # Clear stored email
    context.user_data.pop("resy_email", None)
    return ConversationHandler.END


async def login_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel the login flow."""
    context.user_data.pop("resy_email", None)
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
        "✅ You've been logged out of Resy.\n"
        "Use /login to connect again."
    )


def setup_auth_handlers(application) -> None:
    """Register authentication handlers with the application."""
    
    # Login conversation handler
    login_handler = ConversationHandler(
        entry_points=[CommandHandler("login", login_start)],
        states={
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_email)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, login_password)],
        },
        fallbacks=[CommandHandler("cancel", login_cancel)],
    )
    
    application.add_handler(login_handler)
    application.add_handler(CommandHandler("logout", logout))

