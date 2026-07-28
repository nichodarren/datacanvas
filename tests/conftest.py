"""Shared test fixtures.

The database fixtures rebuild the test schema from migration 0001 on every
session. That is deliberately more work than reusing a schema: it means the
migration is exercised from zero every time the suite runs, so "the migration
still applies cleanly" is never a separate thing somebody has to remember to
check.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from pathlib import Path

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.api.app import create_app
from app.auth.passwords import PasswordHasher
from app.config import Settings
from app.repositories.connection import Database
from app.repositories.tables import metadata
from app.runtime import selector_event_loop
from app.storage.object_store import FilesystemObjectStore

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_TEST_DATABASE_URL = "postgresql://datacanvas:datacanvas@localhost:5432/datacanvas_test"

#: Set in CI. Turns "no database reachable" from a skip into a failure.
#:
#: Without this, the tenant-isolation suite that Gate 1 rests on could quietly
#: skip itself and the run would still be green — the exact failure mode that
#: makes a security test worthless.
REQUIRE_DB_ENV = "DATACANVAS_REQUIRE_DB"


def _test_database_url() -> str:
    return os.environ.get("TEST_DATABASE_URL") or os.environ.get(
        "DATABASE_URL", DEFAULT_TEST_DATABASE_URL
    )


def _async_url(url: str) -> str:
    if url.startswith("postgresql+"):
        return url
    return url.replace("postgresql://", "postgresql+psycopg://", 1)


def pytest_asyncio_loop_factories(
    config: pytest.Config, item: pytest.Item
) -> Mapping[str, Callable[[], asyncio.AbstractEventLoop]]:
    """Run every async test on a SelectorEventLoop.

    psycopg's async mode cannot use Windows' ProactorEventLoop, and the failure
    surfaces as an ``InterfaceError`` at the first query with nothing in the
    traceback pointing at the loop. See ``app.runtime``.
    """
    return {"selector": selector_event_loop}


@pytest.fixture(scope="session")
def migrated_database_url() -> Iterator[str]:
    """A database at migration head, rebuilt from empty.

    Drops and recreates the public schema first: applying the migration to a
    schema that is already populated proves much less than applying it to
    nothing.
    """
    url = _test_database_url()
    async_url = _async_url(url)

    async def rebuild() -> None:
        # A short connect timeout matters here: without it, a developer with no
        # Postgres running waits minutes for the suite to decide to skip.
        engine = create_async_engine(
            async_url, isolation_level="AUTOCOMMIT", connect_args={"connect_timeout": 3}
        )
        try:
            async with engine.connect() as conn:
                await conn.exec_driver_sql("DROP SCHEMA IF EXISTS public CASCADE")
                await conn.exec_driver_sql("CREATE SCHEMA public")
        finally:
            await engine.dispose()

    try:
        asyncio.run(rebuild(), loop_factory=asyncio.SelectorEventLoop)
    except Exception as exc:
        if os.environ.get(REQUIRE_DB_ENV):
            pytest.fail(f"{REQUIRE_DB_ENV} is set but the database is unreachable: {exc}")
        pytest.skip(f"no database at {url} ({type(exc).__name__})")

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "migrations"))
    previous = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = url
    try:
        command.upgrade(config, "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def engine(migrated_database_url: str) -> AsyncIterator[AsyncEngine]:
    created = create_async_engine(_async_url(migrated_database_url))
    yield created
    await created.dispose()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def database(migrated_database_url: str) -> AsyncIterator[Database]:
    """The application's own Database, pointed at the test schema."""
    created = Database(migrated_database_url)
    yield created
    await created.dispose()


@pytest.fixture(scope="session")
def test_hasher() -> PasswordHasher:
    """Argon2 with the cost turned down.

    Production parameters cost ~100 ms per hash by design (§13.2). Paying that
    in every test that logs somebody in buys no extra confidence — the thing
    under test is the flow, not the KDF's difficulty.
    """
    return PasswordHasher(memory_cost=8, time_cost=1, parallelism=1)


@pytest_asyncio.fixture(loop_scope="session")
async def api(
    database: Database, test_hasher: PasswordHasher, tmp_path: Path
) -> AsyncIterator[AsyncClient]:
    """An HTTP client speaking to the real application.

    The real app, not a rehearsal of it: same routes, same dependencies, same
    authorization. Only the clock, the password cost and the storage root are
    swapped, and each of those is an injection point the app already has.
    """
    application = create_app(
        settings=Settings(database_url=_test_database_url(), storage_root=tmp_path),
        database=database,
        store=FilesystemObjectStore(tmp_path / "storage"),
        hasher=test_hasher,
        # Secure cookies are dropped over the ASGI transport's http:// scheme,
        # and the failure looks like "login silently does nothing".
        secure_cookies=False,
    )
    # httpx's ASGI transport does not run lifespan, and lifespan is where the
    # app wires its database and store. Entering it explicitly keeps the test
    # exercising the same startup path production uses.
    async with (
        application.router.lifespan_context(application),
        AsyncClient(
            transport=ASGITransport(app=application), base_url="http://testserver"
        ) as client,
    ):
        yield client


@pytest_asyncio.fixture(loop_scope="session", autouse=True)
async def clean_tables(request: pytest.FixtureRequest) -> AsyncIterator[None]:
    """Empty every table between tests that touch the API.

    TRUNCATE rather than DELETE, because the audit log refuses DELETE (§13.7).
    That it works here is not a hole: TRUNCATE needs a privilege the
    application role was never granted, which is what makes the grant a real
    second line of defence rather than a decoration.
    """
    yield
    if "database" not in request.fixturenames:
        return
    database: Database = request.getfixturevalue("database")
    tables = ", ".join(
        table.name for table in metadata.sorted_tables if table.name != "organization"
    )
    async with database.transaction() as connection:
        await connection.exec_driver_sql(f"TRUNCATE TABLE {tables} RESTART IDENTITY CASCADE")


@pytest_asyncio.fixture(loop_scope="session")
async def db(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """A connection wrapped in a transaction that is always rolled back.

    Tests never clean up after themselves, and never see each other's rows.

    A statement that raises aborts the whole Postgres transaction, so a test
    that *expects* an error must scope it with ``async with db.begin_nested():``
    to keep the outer transaction usable.
    """
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            yield connection
        finally:
            await transaction.rollback()
