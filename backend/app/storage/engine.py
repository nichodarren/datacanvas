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


def _quote(identifier: str) -> str:
    """Quote a column name for SQL.

    Identifiers cannot be bound parameters, so this is the one place where
    user-controlled text reaches a statement as text. Doubling the quote is the
    standard escape and it is complete for the double-quoted form: there is no
    sequence that closes the identifier early once every ``"`` is doubled.
    Column names arrive from a Parquet file the user uploaded, so treating them
    as hostile is not paranoia (NFR-SEC.3, NFR-SEC.5).
    """
    return '"' + identifier.replace('"', '""') + '"'


#: Shape rules, written out rather than inferred by a cast. See
#: :meth:`DuckDBEngine.column_statistics` for why.
#:
#: ``integer`` — no leading zeros (``007`` is an identifier, and reading it as 7
#: loses a digit that mattered), no scientific notation, no hex, no underscores,
#: bounded to 18 digits so the value fits a BIGINT without wrapping.
#: ``decimal`` — must actually contain a point; whole numbers are counted by the
#: integer rule and a column is only decimal if something in it is not whole.
#: ``date``/``datetime`` — shape *and* cast. The shape rejects ``inf``; the cast
#: rejects ``2024-13-45``, which has a perfectly good shape and is not a date.
#: ``boolean`` — a word vocabulary only. ``0``/``1`` are deliberately absent:
#: they are equally an integer, and guessing wrong turns arithmetic into logic.
_INTEGER_RE = r"^[+-]?(0|[1-9][0-9]{0,17})$"
_DECIMAL_RE = r"^[+-]?([0-9]+\.[0-9]*|\.[0-9]+)$"
_DATE_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$"
_DATETIME_RE = r"^[0-9]{4}-[0-9]{2}-[0-9]{2}[ T][0-9]{2}:[0-9]{2}(:[0-9]{2})?"
_BOOLEAN_WORDS = "('true','false','t','f','yes','no','y','n')"

#: A value is "present" when it is neither NULL nor blank. An empty string is
#: not a value, and counting it as one makes every completeness number wrong.
_COLUMN_SLOT = "@@col@@"
_PRESENT = f"{_COLUMN_SLOT} IS NOT NULL AND trim({_COLUMN_SLOT}) <> ''"
_TRIMMED = f"trim({_COLUMN_SLOT})"

_STATISTICS_SQL = ", ".join(
    (
        f"count(*) FILTER (WHERE {_PRESENT})",
        f"count(DISTINCT {_COLUMN_SLOT}) FILTER (WHERE {_PRESENT})",
        f"count(*) FILTER (WHERE {_PRESENT} AND regexp_matches({_TRIMMED}, '{_INTEGER_RE}'))",
        f"count(*) FILTER (WHERE {_PRESENT} AND regexp_matches({_TRIMMED}, '{_DECIMAL_RE}'))",
        f"count(*) FILTER (WHERE {_PRESENT} AND lower({_TRIMMED}) IN {_BOOLEAN_WORDS})",
        f"count(*) FILTER (WHERE {_PRESENT} AND regexp_matches({_TRIMMED}, '{_DATE_RE}')"
        f" AND try_cast({_TRIMMED} AS DATE) IS NOT NULL)",
        f"count(*) FILTER (WHERE {_PRESENT} AND regexp_matches({_TRIMMED}, '{_DATETIME_RE}')"
        f" AND try_cast({_TRIMMED} AS TIMESTAMP) IS NOT NULL)",
    )
)

#: How many aggregates :data:`_STATISTICS_SQL` produces per column.
_STATISTICS_FIELDS = 7


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
class ColumnStatistics:
    """What one whole-file pass measured about a column (FR-B.3).

    Measurements only — no verdict. The engine counts; ``app.schema`` decides
    what the counts mean. §10.2 draws that line explicitly: Schema Inference
    produces the contract, and the thing that reads bytes is *not* the thing
    that interprets them.

    Every ``*_like`` count is over **non-empty, non-null** values, so a column
    that is half empty is judged on the half that is there.
    """

    name: str
    ordinal: int
    physical_type: str
    total: int
    non_null: int
    distinct: int
    integer_like: int
    decimal_like: int
    boolean_like: int
    date_like: int
    datetime_like: int

    @property
    def is_empty(self) -> bool:
        """No values at all — nothing to infer from, and worth saying so."""
        return self.non_null == 0

    def share(self, count: int) -> float:
        """Fraction of the values that are actually there."""
        return 0.0 if self.non_null == 0 else count / self.non_null


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

    def column_statistics(self, handle: DataHandle) -> tuple[ColumnStatistics, ...]: ...


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

    def column_statistics(self, handle: DataHandle) -> tuple[ColumnStatistics, ...]:
        """Measure every column in **one** pass over the whole file (FR-B.3).

        One pass, not one per column: a 5 million row file read thirty-two times
        is thirty-two times the work for a result that is identical.

        **Shape rules, never ``TRY_CAST``.** Measured before choosing, and the
        results ruled it out — ``TRY_CAST`` is a *conversion* tuned to be
        forgiving, and forgiveness is exactly what destroys information here:

        =========================  ==================  =========================
        value                      ``AS BIGINT``       what that would cost
        =========================  ==================  =========================
        ``1.5``                    ``2``               decimals read as integers
        ``007``                    ``7``               a zip code loses its zero
        ``0x1F``                   ``31``              hex accepted as decimal
        ``1_000``                  ``1000``            underscores accepted
        ``inf``                    ``9999-12-31``      as a *date*
        ``2024-03-01 10:00:00``    a ``DATE``          the time silently dropped
        =========================  ==================  =========================

        Every one of those is the ``utf8-lossy`` mistake again: a permissive
        converter quietly reinterpreting data. So the counts below come from
        explicit regular expressions that say what we accept, with a cast used
        only where a shape is insufficient — ``2024-13-45`` has the right shape
        and is not a date.
        """
        source = self._source(handle)
        columns = self.columns(handle)
        if not columns:
            return ()

        # `replace`, not `format`: the shape rules contain `{0,17}`, and
        # `str.format` reads that as a field name. A quantifier is not a
        # placeholder, and the two notations should not have to share a string.
        projection = ", ".join(
            _STATISTICS_SQL.replace(_COLUMN_SLOT, _quote(c.name)) for c in columns
        )
        row = (
            self._cursor()
            .execute(f"SELECT count(*), {projection} FROM read_parquet(?)", [source])  # noqa: S608
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("column statistics returned nothing")

        total = int(row[0])
        return tuple(
            ColumnStatistics(
                name=column.name,
                ordinal=column.ordinal,
                physical_type=column.physical_type,
                total=total,
                non_null=int(row[1 + i * _STATISTICS_FIELDS + 0]),
                distinct=int(row[1 + i * _STATISTICS_FIELDS + 1]),
                integer_like=int(row[1 + i * _STATISTICS_FIELDS + 2]),
                decimal_like=int(row[1 + i * _STATISTICS_FIELDS + 3]),
                boolean_like=int(row[1 + i * _STATISTICS_FIELDS + 4]),
                date_like=int(row[1 + i * _STATISTICS_FIELDS + 5]),
                datetime_like=int(row[1 + i * _STATISTICS_FIELDS + 6]),
            )
            for i, column in enumerate(columns)
        )

    def close(self) -> None:
        self._db.close()


__all__ = [
    "MAX_PAGE_SIZE",
    "ColumnStatistics",
    "DuckDBEngine",
    "EngineError",
    "Page",
    "PhysicalColumn",
    "TableEngine",
]
