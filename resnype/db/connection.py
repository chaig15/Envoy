"""Database connection pool management."""

import asyncpg
from typing import Optional
from contextlib import asynccontextmanager

from resnype.config import get_settings


class Database:
    """Manages PostgreSQL connection pool."""
    
    _pool: Optional[asyncpg.Pool] = None
    
    @classmethod
    async def connect(cls) -> None:
        """Initialize the connection pool."""
        if cls._pool is not None:
            return
        
        settings = get_settings()
        cls._pool = await asyncpg.create_pool(
            settings.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
    
    @classmethod
    async def disconnect(cls) -> None:
        """Close the connection pool."""
        if cls._pool is not None:
            await cls._pool.close()
            cls._pool = None
    
    @classmethod
    def get_pool(cls) -> asyncpg.Pool:
        """Get the connection pool."""
        if cls._pool is None:
            raise RuntimeError("Database not connected. Call Database.connect() first.")
        return cls._pool
    
    @classmethod
    @asynccontextmanager
    async def acquire(cls):
        """Acquire a connection from the pool."""
        pool = cls.get_pool()
        async with pool.acquire() as connection:
            yield connection
    
    @classmethod
    async def execute(cls, query: str, *args) -> str:
        """Execute a query and return status."""
        async with cls.acquire() as conn:
            return await conn.execute(query, *args)
    
    @classmethod
    async def fetch(cls, query: str, *args) -> list:
        """Execute a query and return all rows."""
        async with cls.acquire() as conn:
            return await conn.fetch(query, *args)
    
    @classmethod
    async def fetchrow(cls, query: str, *args) -> Optional[asyncpg.Record]:
        """Execute a query and return a single row."""
        async with cls.acquire() as conn:
            return await conn.fetchrow(query, *args)
    
    @classmethod
    async def fetchval(cls, query: str, *args):
        """Execute a query and return a single value."""
        async with cls.acquire() as conn:
            return await conn.fetchval(query, *args)

