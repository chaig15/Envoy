"""Telegram bot command handlers."""

from .auth import setup_auth_handlers
from .booking import setup_booking_handlers
from .llm_handler import setup_llm_handler
from .search import setup_search_handlers
from .snipe import setup_snipe_handlers
from .watch import setup_watch_handlers

__all__ = [
    "setup_auth_handlers",
    "setup_booking_handlers",
    "setup_llm_handler",
    "setup_search_handlers",
    "setup_snipe_handlers",
    "setup_watch_handlers",
]
