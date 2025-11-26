"""Database query functions."""

from datetime import date, time
from typing import Optional
import json

from .connection import Database
from .models import User, Watch, WatchGroup, Snipe


class UserQueries:
    """Database operations for users."""

    @staticmethod
    async def get_or_create(telegram_id: int) -> User:
        """Get existing user or create a new one."""
        row = await Database.fetchrow(
            """
            INSERT INTO users (telegram_id)
            VALUES ($1)
            ON CONFLICT (telegram_id) DO UPDATE SET telegram_id = $1
            RETURNING *
            """,
            telegram_id,
        )
        return User.model_validate(dict(row))

    @staticmethod
    async def get_by_telegram_id(telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID."""
        row = await Database.fetchrow(
            "SELECT * FROM users WHERE telegram_id = $1", telegram_id
        )
        if row:
            return User.model_validate(dict(row))
        return None

    @staticmethod
    async def update_resy_token(
        telegram_id: int, encrypted_token: str, payment_method_id: Optional[str] = None
    ) -> None:
        """Update user's Resy token."""
        await Database.execute(
            """
            UPDATE users
            SET resy_token_encrypted = $2, resy_payment_method_id = $3
            WHERE telegram_id = $1
            """,
            telegram_id,
            encrypted_token,
            payment_method_id,
        )

    @staticmethod
    async def clear_resy_token(telegram_id: int) -> None:
        """Clear user's Resy token (logout)."""
        await Database.execute(
            """
            UPDATE users
            SET resy_token_encrypted = NULL, resy_payment_method_id = NULL
            WHERE telegram_id = $1
            """,
            telegram_id,
        )


class WatchQueries:
    """Database operations for watches."""

    @staticmethod
    async def create(
        user_id: int,
        venue_id: int,
        venue_name: str,
        watch_date: date,
        party_size: int,
        time_earliest: Optional[time] = None,
        time_latest: Optional[time] = None,
    ) -> Watch:
        """Create a new watch."""
        row = await Database.fetchrow(
            """
            INSERT INTO watches (user_id, venue_id, venue_name, date, party_size, time_earliest, time_latest)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING *
            """,
            user_id,
            venue_id,
            venue_name,
            watch_date,
            party_size,
            time_earliest,
            time_latest,
        )
        return Watch.model_validate(dict(row))

    @staticmethod
    async def get_user_watches(
        telegram_id: int, active_only: bool = True
    ) -> list[Watch]:
        """Get all watches for a user."""
        query = """
            SELECT w.* FROM watches w
            JOIN users u ON w.user_id = u.id
            WHERE u.telegram_id = $1
        """
        if active_only:
            query += " AND w.active = TRUE"
        query += " ORDER BY w.date, w.created_at"

        rows = await Database.fetch(query, telegram_id)
        return [Watch.model_validate(dict(row)) for row in rows]

    @staticmethod
    async def deactivate(watch_id: int, telegram_id: int) -> bool:
        """Deactivate a watch (soft delete). Returns True if found and deactivated."""
        result = await Database.execute(
            """
            UPDATE watches w
            SET active = FALSE
            FROM users u
            WHERE w.user_id = u.id
              AND w.id = $1
              AND u.telegram_id = $2
            """,
            watch_id,
            telegram_id,
        )
        return result == "UPDATE 1"

    @staticmethod
    async def get_active_watches_grouped() -> list[WatchGroup]:
        """
        Get all active watches grouped by (venue_id, date, party_size).
        This enables batched API calls - one call per unique combination.
        """
        rows = await Database.fetch(
            """
            SELECT
                w.*,
                u.telegram_id,
                u.resy_token_encrypted
            FROM watches w
            JOIN users u ON w.user_id = u.id
            WHERE w.active = TRUE
              AND w.date >= CURRENT_DATE
              AND u.resy_token_encrypted IS NOT NULL
            ORDER BY w.venue_id, w.date, w.party_size
            """
        )

        # Group watches by (venue_id, date, party_size)
        groups: dict[tuple, list[Watch]] = {}
        for row in rows:
            watch = Watch.model_validate(dict(row))
            key = (watch.venue_id, watch.date, watch.party_size)
            if key not in groups:
                groups[key] = []
            groups[key].append(watch)

        return [
            WatchGroup(venue_id=key[0], date=key[1], party_size=key[2], watches=watches)
            for key, watches in groups.items()
        ]

    @staticmethod
    async def mark_slot_notified(watch_id: int, slot_token: str) -> None:
        """Mark a slot as already notified for a watch."""
        await Database.execute(
            """
            UPDATE watches
            SET notified_slots = notified_slots || $2::jsonb
            WHERE id = $1
            """,
            watch_id,
            json.dumps([slot_token]),
        )

    @staticmethod
    async def get_by_id(watch_id: int) -> Optional[Watch]:
        """Get a watch by ID with user info."""
        row = await Database.fetchrow(
            """
            SELECT w.*, u.telegram_id, u.resy_token_encrypted
            FROM watches w
            JOIN users u ON w.user_id = u.id
            WHERE w.id = $1
            """,
            watch_id,
        )
        if row:
            return Watch.model_validate(dict(row))
        return None


class SnipeQueries:
    """Database operations for snipes."""

    @staticmethod
    async def create(
        user_id: int,
        venue_id: int,
        venue_name: str,
        target_date: date,
        release_date: date,
        party_size: int,
        release_time: Optional[time] = None,
        release_timezone: Optional[str] = None,
    ) -> Snipe:
        """Create a new snipe."""
        row = await Database.fetchrow(
            """
            INSERT INTO snipes (user_id, venue_id, venue_name, target_date, release_date, party_size, release_time, release_timezone)
            VALUES ($1, $2, $3, $4, $5, $6, COALESCE($7, '09:00'), COALESCE($8, 'America/New_York'))
            RETURNING *
            """,
            user_id,
            venue_id,
            venue_name,
            target_date,
            release_date,
            party_size,
            release_time,
            release_timezone,
        )
        return Snipe.model_validate(dict(row))

    @staticmethod
    async def get_user_snipes(
        telegram_id: int, pending_only: bool = True
    ) -> list[Snipe]:
        """Get all snipes for a user."""
        query = """
            SELECT s.*, u.telegram_id, u.resy_token_encrypted, u.resy_payment_method_id
            FROM snipes s
            JOIN users u ON s.user_id = u.id
            WHERE u.telegram_id = $1
        """
        if pending_only:
            query += " AND s.status = 'pending'"
        query += " ORDER BY s.target_date, s.created_at"

        rows = await Database.fetch(query, telegram_id)
        return [Snipe.model_validate(dict(row)) for row in rows]

    @staticmethod
    async def get_pending_snipes_due() -> list[Snipe]:
        """
        Get pending snipes that should execute soon.
        Returns snipes where release_date is today (reservations open today).
        """
        rows = await Database.fetch(
            """
            SELECT s.*, u.telegram_id, u.resy_token_encrypted, u.resy_payment_method_id
            FROM snipes s
            JOIN users u ON s.user_id = u.id
            WHERE s.status = 'pending'
              AND s.release_date = CURRENT_DATE
              AND u.resy_token_encrypted IS NOT NULL
            ORDER BY s.release_time
            """
        )
        return [Snipe.model_validate(dict(row)) for row in rows]

    @staticmethod
    async def update_status(
        snipe_id: int,
        status: str,
        reservation_id: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        """Update snipe status after execution."""
        await Database.execute(
            """
            UPDATE snipes
            SET status = $2,
                result_reservation_id = $3,
                result_message = $4,
                executed_at = NOW()
            WHERE id = $1
            """,
            snipe_id,
            status,
            reservation_id,
            message,
        )

    @staticmethod
    async def cancel(snipe_id: int, telegram_id: int) -> bool:
        """Cancel a pending snipe. Returns True if found and cancelled."""
        result = await Database.execute(
            """
            UPDATE snipes s
            SET status = 'cancelled'
            FROM users u
            WHERE s.user_id = u.id
              AND s.id = $1
              AND u.telegram_id = $2
              AND s.status = 'pending'
            """,
            snipe_id,
            telegram_id,
        )
        return result == "UPDATE 1"

    @staticmethod
    async def get_by_id(snipe_id: int) -> Optional[Snipe]:
        """Get a snipe by ID with user info."""
        row = await Database.fetchrow(
            """
            SELECT s.*, u.telegram_id, u.resy_token_encrypted, u.resy_payment_method_id
            FROM snipes s
            JOIN users u ON s.user_id = u.id
            WHERE s.id = $1
            """,
            snipe_id,
        )
        if row:
            return Snipe.model_validate(dict(row))
        return None
