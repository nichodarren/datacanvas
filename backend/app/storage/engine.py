"""The analytics engine (DESIGN.md §10.2, §10.3, §13.3.1 L3).

DuckDB reading normalized Parquet. This is the second half of P0-5, deliberately
deferred out of Phase 1: until ingest existed there was nothing to read, and a
wrapper with no callers is a wrapper whose shape is a guess.

**Every method takes a ``DataHandle``, never a path.** That is layer 3 of INV-7
and the reason this module imports from ``app.authz`` even though authorization
normally sits *above* storage. The inverted direction is the point: accepting a
``str`` here would make the type system agree with a caller who skipped the
authorization layer, and no amount of documentation undoes that.

Methods are synchronous, matching ``ObjectStore`` — DuckDB blocks, and wrapping
a blocking call in a coroutine buys nothing. Request-path callers offload with
``asyncio.to_thread``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Protocol

import duckdb

from app.authz.data_access import DataHandle
from app.domain.errors import DomainError

#: FR-D.2 lets the user choose the page size; it does not let them choose to
#: serialise a million rows into one response. The cap is the difference
#: between a setting and a denial of service.
MAX_PAGE_SIZE: Final = 1_000


class EngineError(DomainError):
    """The engine could not answer the question asked of it."""


@dataclass(frozen=True, slots=True)
class PhysicalColumn:
    """A column as the Parquet file describes it — not as we interpret it.

    ``physical_type`` feeds ``ColumnSpec.physical_type``; the *logical* type is
    a separate decision made by schema inference and overridable by the user
    (FR-C.1, FR-C.2). Keeping the two apart at the type level is what stops an
    interpretation from ever being mistaken for a fact about the file.
    """

    name: str
    ordinal: int
    physical_type: str


@dataclass(frozen=True, slots=True)
class Page:
    """One server-side page of rows (FR-D.1)."""

    columns: tuple[str, ...]
    rows: tuple[tuple[object, ...], ...]
    offset: int
    limit: int


class TableEngine(Protocol):
    """What the rest of the system may ask of the engine in Phase 2.

    Kept this narrow on purpose. Tools arrive in Phase 3 and will take a
    ``table_ref`` rather than a handle (§9.6); adding that later is an addition,
    while guessing at it now would be a rewrite.
    """

    def columns(self, handle: DataHandle) -> tuple[PhysicalColumn, ...]: ...

    def row_count(self, handle: DataHandle) -> int: ...

    def page(self, handle: DataHandle, *, offset: int, limit: int) -> Page: ...


class DuckDBEngine:
    """DuckDB over Parquet.

    One in-process database, one cursor per operation. ``cursor()`` is DuckDB's
    documented way to use a database from several threads; sharing the bare
    connection is not, and a fresh ``connect()`` per call measured ~22 ms of
    pure overhead — affordable against NFR-PERF.1 but wasted.
    """

    def __init__(self) -> None:
        self._db = duckdb.connect()
        self._configure(self._db)

    @staticmethod
    def _configure(connection: duckdb.DuckDBPyConnection) -> None:
        """Pin the settings that pagination correctness rests on.

        ``preserve_insertion_order`` already defaults to true. It is set anyway
        because :meth:`page` is only correct while it holds: with it off, DuckDB
        may return parallel scan results in any order, and a user paging through
        a table would see rows repeat and rows vanish — silently, and only on
        files large enough to be scanned in parallel, which is to say only on
        real data. A default we depend on is an assumption; a default we set is
        a decision. ``tests/unit/test_engine.py`` holds the matching test.
        """
        connection.execute("SET preserve_insertion_order = true")

    def _cursor(self) -> duckdb.DuckDBPyConnection:
        cursor = self._db.cursor()
        self._configure(cursor)
        return cursor

    @staticmethod
    def _source(handle: DataHandle) -> str:
        """Resolve the handle to something DuckDB can read.

        The ``isinstance`` check is INV-7 L3 made executable. mypy already
        rejects a ``str`` here, but mypy does not run in production and does not
        see callers that reach this through ``Any``. Without the check, passing
        a path fails with ``AttributeError: 'str' object has no attribute
        'local_path'`` — which reads like a bug in the engine rather than what
        it is: someone reaching data without authorization.

        The path is then passed as a **bound parameter**, never interpolated
        into SQL (NFR-SEC.3). It is ours rather than the user's, but building
        SQL by concatenation is a habit, and habits are what leak.
        """
        if not isinstance(handle, DataHandle):
            raise EngineError(
                "the engine only reads through a DataHandle, never a path "
                f"(got {type(handle).__name__}). Use data_access.open_dataset_version()."
            )
        return str(handle.local_path())

    def columns(self, handle: DataHandle) -> tuple[PhysicalColumn, ...]:
        rows = (
            self._cursor()
            .execute("DESCRIBE SELECT * FROM read_parquet(?)", [self._source(handle)])
            .fetchall()
        )
        return tuple(
            PhysicalColumn(name=str(row[0]), ordinal=i, physical_type=str(row[1]))
            for i, row in enumerate(rows)
        )

    def row_count(self, handle: DataHandle) -> int:
        row = (
            self._cursor()
            .execute("SELECT count(*) FROM read_parquet(?)", [self._source(handle)])
            .fetchone()
        )
        if row is None:  # pragma: no cover - count(*) always returns a row
            raise EngineError("row count returned nothing")
        return int(row[0])

    def page(self, handle: DataHandle, *, offset: int, limit: int) -> Page:
        """Rows ``offset..offset+limit`` in file order.

        No ``ORDER BY``: the order that matters here is the order the file is
        in, which is what the user uploaded and what they expect to page
        through. See :meth:`_configure` for why that order is trustworthy.
        """
        if offset < 0:
            raise EngineError(f"offset must not be negative, got {offset}")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise EngineError(f"limit must be within 1..{MAX_PAGE_SIZE}, got {limit}")

        cursor = self._cursor().execute(
            "SELECT * FROM read_parquet(?) LIMIT ? OFFSET ?",
            [self._source(handle), limit, offset],
        )
        description = cursor.description
        if description is None:  # pragma: no cover - a SELECT always describes itself
            raise EngineError("query returned no column description")

        return Page(
            columns=tuple(str(column[0]) for column in description),
            rows=tuple(tuple(row) for row in cursor.fetchall()),
            offset=offset,
            limit=limit,
        )

    def close(self) -> None:
        self._db.close()


__all__ = [
    "MAX_PAGE_SIZE",
    "DuckDBEngine",
    "EngineError",
    "Page",
    "PhysicalColumn",
    "TableEngine",
]
