"""A guard on the test harness itself.

Written after the harness migrated the *development* database instead of the
test one. ``get_settings()`` is lru_cached and Alembic's env.py reads the URL
through it, so any earlier call cached the URL from ``.env`` and the migration
went somewhere nobody was looking. The symptom appeared much later and much
further away: ``relation "app_user" does not exist`` in a teardown.

A test suite that can quietly point at the wrong database is a test suite whose
results mean nothing, so this checks the one fact everything else assumes.
"""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from app.repositories.connection import Database

pytestmark = pytest.mark.asyncio(loop_scope="session")


def _database_name(url: str) -> str:
    return url.rsplit("/", 1)[-1].split("?", 1)[0]


async def test_connected_to_the_configured_test_database(
    database: Database, migrated_database_url: str
) -> None:
    async with database.connect() as connection:
        current = await connection.scalar(sa.text("SELECT current_database()"))
    assert current == _database_name(migrated_database_url)


async def test_not_connected_to_the_development_database(database: Database) -> None:
    """Only meaningful when the two are actually configured differently."""
    dev = os.environ.get("DATABASE_URL")
    test = os.environ.get("TEST_DATABASE_URL")
    if not dev or not test or _database_name(dev) == _database_name(test):
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL name the same database")

    async with database.connect() as connection:
        current = await connection.scalar(sa.text("SELECT current_database()"))
    assert current != _database_name(dev)


async def test_the_schema_is_actually_migrated(database: Database) -> None:
    """Cheap, and it fails loudly instead of at the first unrelated query."""
    async with database.connect() as connection:
        tables = set(
            (
                await connection.execute(
                    sa.text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
                )
            )
            .scalars()
            .all()
        )
    assert {"app_user", "workspace", "membership", "audit_event"} <= tables
