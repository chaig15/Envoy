"""Pydantic models for Resy API responses."""

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel, Field


class ResyAuth(BaseModel):
    """Authentication response from Resy."""

    token: str
    payment_method_id: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class ResyChallenge(BaseModel):
    """Challenge response when additional verification is needed."""

    challenge_id: str
    claim_token: str
    first_name: Optional[str] = None
    challenge_type: str = "email"  # Type of verification needed
    message: Optional[str] = None


class VenueLocation(BaseModel):
    """Venue location details."""

    city: Optional[str] = None
    neighborhood: Optional[str] = None


class Venue(BaseModel):
    """Restaurant/venue from Resy."""

    id: int = Field(alias="venue_id")
    name: str
    location: Optional[VenueLocation] = None
    price_range: Optional[int] = None
    cuisine: Optional[str] = None
    rating: Optional[float] = None

    class Config:
        populate_by_name = True

    @property
    def display_location(self) -> str:
        """Get formatted location string."""
        if self.location:
            parts = [self.location.neighborhood, self.location.city]
            return ", ".join(p for p in parts if p)
        return ""


class TimeSlot(BaseModel):
    """Available reservation time slot."""

    config_token: str = Field(alias="config_id")
    time: str  # "HH:MM:SS" or "HH:MM"
    type: Optional[str] = None  # "Dining Room", "Bar", etc.

    class Config:
        populate_by_name = True

    @property
    def time_display(self) -> str:
        """Get formatted time for display (e.g., '7:30 PM')."""
        try:
            # Parse the time string
            if len(self.time) == 8:  # HH:MM:SS
                t = datetime.strptime(self.time, "%H:%M:%S")
            else:  # HH:MM
                t = datetime.strptime(self.time, "%H:%M")
            return t.strftime("%-I:%M %p")
        except ValueError:
            return self.time

    @property
    def time_obj(self) -> time:
        """Get time as datetime.time object."""
        try:
            if len(self.time) == 8:
                return datetime.strptime(self.time, "%H:%M:%S").time()
            return datetime.strptime(self.time, "%H:%M").time()
        except ValueError:
            return time(0, 0)


class Availability(BaseModel):
    """Availability response for a venue."""

    venue_id: int
    venue_name: str
    date: date
    party_size: int
    slots: list[TimeSlot] = []

    def filter_by_time_range(
        self, earliest: Optional[time], latest: Optional[time]
    ) -> list[TimeSlot]:
        """Filter slots to those within the given time range."""
        if not earliest and not latest:
            return self.slots

        filtered = []
        for slot in self.slots:
            slot_time = slot.time_obj
            if earliest and slot_time < earliest:
                continue
            if latest and slot_time > latest:
                continue
            filtered.append(slot)
        return filtered


class BookingDetails(BaseModel):
    """Details needed to complete a booking."""

    book_token: str
    config_id: str
    day: str
    party_size: int
    venue_id: int


class BookingResult(BaseModel):
    """Result of a booking attempt."""

    success: bool
    reservation_id: Optional[str] = None
    confirmation_number: Optional[str] = None
    venue_name: Optional[str] = None
    date: Optional[str] = None
    time: Optional[str] = None
    party_size: Optional[int] = None
    error_message: Optional[str] = None
