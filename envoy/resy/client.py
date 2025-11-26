"""Resy API client for authentication, search, availability, and booking."""

import json
import logging
from datetime import date
from typing import Optional

import aiohttp

from envoy.config import get_settings
from .models import (
    ResyAuth,
    ResyChallenge,
    Venue,
    TimeSlot,
    Availability,
    BookingDetails,
    BookingResult,
)

logger = logging.getLogger(__name__)


class ResyError(Exception):
    """Error from Resy API."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ResyClient:
    """Async client for Resy API."""

    # Resy API requires these headers
    API_KEY = "VbWk7s3L4KiK5fzlO7JD3Q5EYolJI7n5"  # Public API key used by resy.com

    def __init__(self, auth_token: Optional[str] = None):
        self.auth_token = auth_token
        self.settings = get_settings()
        self._session: Optional[aiohttp.ClientSession] = None

    @property
    def base_url(self) -> str:
        return self.settings.resy_api_base

    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        headers = {
            "Authorization": f'ResyAPI api_key="{self.API_KEY}"',
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://resy.com",
            "Referer": "https://resy.com/",
        }
        if self.auth_token:
            headers["X-Resy-Auth-Token"] = self.auth_token
        return headers

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        endpoint: str,
        params: Optional[dict] = None,
        data: Optional[dict] = None,
        use_json: bool = False,
    ) -> dict:
        """Make an API request."""
        session = await self._get_session()
        url = f"{self.base_url}{endpoint}"

        headers = self._get_headers()

        # Some endpoints need JSON instead of form-urlencoded
        if use_json:
            headers["Content-Type"] = "application/json"

        logger.debug(
            f"Resy API {method} {endpoint} params={params} data={data} json={use_json}"
        )

        request_kwargs = {
            "headers": headers,
            "params": params,
        }

        if data:
            if use_json:
                request_kwargs["json"] = data
            else:
                request_kwargs["data"] = data

        async with session.request(method, url, **request_kwargs) as response:
            text = await response.text()
            logger.debug(f"Resy API response {response.status}: {text[:500]}")

            if response.status == 401:
                raise ResyError("Authentication failed. Please login again.", 401)
            if response.status == 404:
                raise ResyError("Not found.", 404)
            if response.status >= 400:
                raise ResyError(f"API error: {text}", response.status)

            return json.loads(text)

    # ============ Authentication ============

    async def request_sms_code(self, phone_number: str) -> bool:
        """
        Request an SMS verification code for phone login.

        Args:
            phone_number: Phone number with country code (e.g., "+14155551234")

        Returns:
            True if SMS was sent successfully
        """
        # Resy API wants E.164 format with + prefix, form-urlencoded
        data = {"mobile_number": phone_number}

        await self._request("POST", "/3/auth/mobile", data=data, use_json=False)
        return True

    async def verify_sms_code(
        self, phone_number: str, code: str
    ) -> ResyAuth | ResyChallenge:
        """
        Verify SMS code and complete phone authentication.

        Args:
            phone_number: Phone number used to request the code
            code: The SMS verification code

        Returns:
            ResyAuth with token if successful, or ResyChallenge if additional verification needed
        """
        # Verify also uses form-urlencoded with E.164 format
        data = {
            "mobile_number": phone_number,
            "code": code,
        }

        # Same endpoint as request_sms_code - adding code param completes verification
        result = await self._request(
            "POST", "/3/auth/mobile", data=data, use_json=False
        )

        # Check if we got a challenge instead of direct auth
        if "challenge" in result:
            challenge = result["challenge"]
            mobile_claim = result.get("mobile_claim", {})
            return ResyChallenge(
                challenge_id=challenge["challenge_id"],
                claim_token=mobile_claim.get("claim_token", ""),
                first_name=challenge.get("first_name"),
                challenge_type="email",  # Currently only email challenges
                message=challenge.get("message"),
            )

        # Direct auth - extract payment method if available
        payment_method_id = None
        if "payment_method_id" in result:
            payment_method_id = str(result["payment_method_id"])
        elif "payment_methods" in result and result["payment_methods"]:
            payment_method_id = str(result["payment_methods"][0].get("id"))

        return ResyAuth(
            token=result["token"],
            payment_method_id=payment_method_id,
            first_name=result.get("first_name"),
            last_name=result.get("last_name"),
        )

    async def complete_challenge(
        self, challenge_id: str, claim_token: str, email: str
    ) -> ResyAuth:
        """
        Complete an email verification challenge.

        Args:
            challenge_id: Challenge ID from verify_sms_code
            claim_token: Claim token from verify_sms_code
            email: Email address to verify

        Returns:
            ResyAuth with token and user info
        """
        data = {
            "challenge_id": challenge_id,
            "claim_token": claim_token,
            "em_address": email,
        }

        result = await self._request(
            "POST", "/3/auth/challenge", data=data, use_json=False
        )

        # Extract payment method if available
        payment_method_id = None
        if "payment_method_id" in result:
            payment_method_id = str(result["payment_method_id"])
        elif "payment_methods" in result and result["payment_methods"]:
            payment_method_id = str(result["payment_methods"][0].get("id"))

        return ResyAuth(
            token=result["token"],
            payment_method_id=payment_method_id,
            first_name=result.get("first_name"),
            last_name=result.get("last_name"),
        )

    # ============ Search ============

    async def search_venues(self, query: str, location: str = "ny") -> list[Venue]:
        """
        Search for venues by name.

        Args:
            query: Search term
            location: City code (ny, la, chi, sf, etc.) - currently not used as API doesn't accept geo param
        """
        # The search endpoint requires POST with struct_data parameter
        struct_data = {
            "query": query,
            "per_page": 10,
            "page": 1,
        }

        data = {"struct_data": json.dumps(struct_data)}

        result = await self._request("POST", "/3/venuesearch/search", data=data)

        venues = []
        for hit in result.get("search", {}).get("hits", []):
            try:
                # Rating can be a float or dict with 'average' key
                rating = hit.get("rating")
                if isinstance(rating, dict):
                    rating = rating.get("average")

                venue = Venue(
                    venue_id=hit["id"]["resy"],
                    name=hit["name"],
                    location=hit.get("location"),
                    price_range=hit.get("price_range"),
                    cuisine=hit.get("cuisine", [None])[0]
                    if hit.get("cuisine")
                    else None,
                    rating=rating,
                )
                venues.append(venue)
            except (KeyError, IndexError):
                continue

        return venues

    # ============ Availability ============

    async def get_availability(
        self,
        venue_id: int,
        check_date: date,
        party_size: int,
    ) -> Availability:
        """
        Get available time slots for a venue.

        Args:
            venue_id: Resy venue ID
            check_date: Date to check
            party_size: Number of guests
        """
        params = {
            "venue_id": venue_id,
            "day": check_date.isoformat(),
            "party_size": party_size,
            "lat": 0,
            "long": 0,
        }

        result = await self._request("GET", "/4/find", params=params)

        slots = []
        venue_name = ""

        # Parse the response - structure varies
        results = result.get("results", {})
        venues = results.get("venues", [])

        if venues:
            venue_data = venues[0]
            venue_info = venue_data.get("venue", {})
            venue_name = venue_info.get("name", "")

            for slot_data in venue_data.get("slots", []):
                config = slot_data.get("config", {})
                date_info = slot_data.get("date", {})

                slot = TimeSlot(
                    config_id=config.get("token", ""),
                    time=date_info.get("start", ""),
                    type=config.get("type", ""),
                )
                slots.append(slot)

        return Availability(
            venue_id=venue_id,
            venue_name=venue_name,
            date=check_date,
            party_size=party_size,
            slots=slots,
        )

    # ============ Booking ============

    async def get_booking_details(
        self, config_token: str, party_size: int, check_date: date
    ) -> BookingDetails:
        """
        Get booking details/token needed to complete a reservation.
        This is the step before actually booking.
        """
        params = {
            "config_id": config_token,
            "party_size": party_size,
            "day": check_date.isoformat(),
        }

        result = await self._request("GET", "/3/details", params=params)

        book_token = result.get("book_token", {}).get("value", "")

        return BookingDetails(
            book_token=book_token,
            config_id=config_token,
            day=check_date.isoformat(),
            party_size=party_size,
            venue_id=result.get("venue", {}).get("id", 0),
        )

    async def book(
        self,
        book_token: str,
        payment_method_id: Optional[str] = None,
    ) -> BookingResult:
        """
        Complete a booking.

        Args:
            book_token: Token from get_booking_details
            payment_method_id: Payment method ID from user's account
        """
        data = {
            "book_token": book_token,
        }

        if payment_method_id:
            data["struct_payment_method"] = f'{{"id":{payment_method_id}}}'

        try:
            result = await self._request("POST", "/3/book", data=data)

            reservation = result.get("reservation", {})

            return BookingResult(
                success=True,
                reservation_id=str(result.get("reservation_id", "")),
                confirmation_number=reservation.get("confirmation_number"),
                venue_name=reservation.get("venue", {}).get("name"),
                date=reservation.get("day"),
                time=reservation.get("time_slot"),
                party_size=reservation.get("party_size"),
            )
        except ResyError as e:
            return BookingResult(
                success=False,
                error_message=e.message,
            )

    async def quick_book(
        self,
        config_token: str,
        party_size: int,
        check_date: date,
        payment_method_id: Optional[str] = None,
    ) -> BookingResult:
        """
        One-step booking: get details and book in sequence.
        """
        # Get the book token
        details = await self.get_booking_details(config_token, party_size, check_date)

        if not details.book_token:
            return BookingResult(
                success=False,
                error_message="Could not get booking token. Slot may no longer be available.",
            )

        # Complete the booking
        return await self.book(details.book_token, payment_method_id)
