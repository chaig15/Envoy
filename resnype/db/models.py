"""Database models as Pydantic classes."""

import json
from datetime import datetime, date, time
from typing import Optional, Any
from pydantic import BaseModel, field_validator


class User(BaseModel):
    """User model representing a Telegram user."""

    id: int
    telegram_id: int
    resy_token_encrypted: Optional[str] = None
    resy_payment_method_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class Watch(BaseModel):
    """Watch model representing a reservation watch request."""

    id: int
    user_id: int
    venue_id: int
    venue_name: str
    date: date
    party_size: int
    time_earliest: Optional[time] = None
    time_latest: Optional[time] = None
    active: bool = True
    created_at: datetime
    notified_slots: list[str] = []

    # Joined fields (optional, populated in some queries)
    telegram_id: Optional[int] = None
    resy_token_encrypted: Optional[str] = None

    @field_validator("notified_slots", mode="before")
    @classmethod
    def parse_notified_slots(cls, v: Any) -> list[str]:
        """Parse notified_slots from JSON string if needed."""
        if isinstance(v, str):
            return json.loads(v)
        return v or []

    class Config:
        from_attributes = True


class WatchGroup(BaseModel):
    """Group of watches with the same venue, date, and party size."""

    venue_id: int
    date: date
    party_size: int
    watches: list[Watch]

