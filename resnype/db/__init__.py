"""Database module for PostgreSQL operations."""

from .connection import Database
from .queries import UserQueries, WatchQueries

__all__ = [
    "Database",
    "UserQueries",
    "WatchQueries",
]

