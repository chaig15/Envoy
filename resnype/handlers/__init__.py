"""Telegram bot command handlers."""

from .auth import setup_auth_handlers
from .search import setup_search_handlers
from .watch import setup_watch_handlers
from .booking import setup_booking_handlers

__all__ = [
    "setup_auth_handlers",
    "setup_search_handlers",
    "setup_watch_handlers",
    "setup_booking_handlers",
]

