"""Database connectivity (D-021).

One engine per process, connections handed out per unit of work. Repositories
never create their own connection: they receive one, so a request that touches
three repositories still commits or rolls back as a single transaction.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine


def async_url(url: str) -> str:
    """Spell out the async driver.

    SQLAlchemy chooses its driver from the scheme, and a bare ``postgresql://``
    resolves to the sync one. Converting here keeps ``DATABASE_URL`` a plain
    Postgres URL that psql, Alembic and any ops tool can also use.
    """
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


class Database:
    """Owns the engine and hands out connections."""

    def __init__(self, url: str, *, pool_size: int = 5, max_overflow: int = 5) -> None:
        self._engine: AsyncEngine = create_async_engine(
            async_url(url),
            pool_size=pool_size,
            max_overflow=max_overflow,
            # Postgres drops idle connections and load balancers do it sooner.
            # Without this, the first query after an idle period fails once and
            # then works, which is the most confusing kind of intermittent bug.
            pool_pre_ping=True,
            # Every `TIMESTAMPTZ` comes back in UTC, whatever the server's own
            # timezone happens to be.
            #
            # Found by comparing a cached API response with a freshly computed
            # one: byte for byte identical except the timestamp, which read
            # `2026-08-21T09:48:56Z` when it came from Python and
            # `2026-08-21T16:48:56+07:00` when it came back from the database.
            # The same instant, spelled two ways, and which one a client got
            # depended on whether the value had made a round trip. That was
            # true of every timestamp in the API — `ingested_at`, `created_at`,
            # `last_seen_at` — not only the one that exposed it.
            #
            # Set on the connection rather than fixed at each read: a converter
            # per repository is a rule seventeen call sites have to remember,
            # and the eighteenth is where it breaks.
            connect_args={"options": "-c timezone=UTC"},
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[AsyncConnection]:
        """A connection inside a transaction: commits on success, rolls back on error.

        Every write path uses this. A handler that half-succeeds leaves a user
        with a workspace and no membership, and no way to notice.
        """
        async with self._engine.connect() as connection, connection.begin():
            yield connection

    @asynccontextmanager
    async def connect(self) -> AsyncIterator[AsyncConnection]:
        """A connection without an explicit transaction, for read-only work."""
        async with self._engine.connect() as connection:
            yield connection

    async def dispose(self) -> None:
        await self._engine.dispose()


__all__ = ["Database", "async_url"]
