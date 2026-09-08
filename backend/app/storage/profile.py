"""What one cheap pass measures about every column (§11.8).

``column_statistics`` in :mod:`app.storage.engine` answers the question schema
inference asks — *what shape are these values?* — and it answers it for every
column in one projection. This module answers the question the Profile tab asks:
*what does each column look like, given the type we settled on?*

The two are deliberately separate. Inference runs once, at ingest, before any
type exists; this runs whenever somebody opens the tab, and it **reads the
contract** to decide what to measure. Asking a column for its median before
anybody has said it holds numbers is how you get ``mean(PassengerId) = 446``.

## The cost, stated

§11.8.6(b): one scalar pass over all columns, plus one query per column that
needs a distribution — a histogram or a top-N. Parquet is columnar, so each of
those extra queries reads exactly one column. The alternative, one enormous
statement with lateral subqueries, is faster on paper and unreadable in
practice; D-021 prefers explicit SQL and this is where that preference is spent.

## Why everything is cast rather than read

Every column lands in Parquet as VARCHAR (``ingest/normalize.py``), so a median
over a ``numerical`` column needs a cast. It is done **only on values matching
the same shape rules inference used** — never ``TRY_CAST`` over everything,
because ``TRY_CAST`` is forgiving and forgiveness is what destroyed information
in the ``utf8-lossy`` defect (D-029). A column that is 97% numeric yields a
median over that 97%, and the bundle says how many were left out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.enums import LogicalType
from app.storage.engine import (
    _DATE_RE,
    _DATETIME_RE,
    _DECIMAL_RE,
    _INTEGER_RE,
    DuckDBEngine,
    EngineError,
    _quote,
)

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle
    from app.domain.data import SchemaContract


@dataclass(frozen=True, slots=True)
class Bin:
    """One bucket of a histogram, with the edges it was cut at.

    The edges travel with the count because §11.8.6(c) sends them explicitly:
    a bin the caller cannot describe is a bar nobody can label, and a binning
    rule that changes between calls breaks INV-6 quietly.
    """

    lower: float
    upper: float
    count: int


@dataclass(frozen=True, slots=True)
class TopValue:
    value: str
    count: int


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """One column as the Profile tab draws it (§11.8.2).

    ``kind`` is the renderer, and it is decided here rather than in the browser
    — §11.8.6(e). The ordering rule that produces it (empty → unsupported →
    constant → logical type) lives in one place, because two places that must
    agree eventually will not.
    """

    name: str
    ordinal: int
    physical_type: str
    logical_type: LogicalType
    total: int
    present: int
    distinct: int
    kind: str

    #: How many present values could actually be read as the declared type.
    #: Equal to ``present`` for text and categorical, which discard nothing.
    conforming: int | None = None

    # --- numerical -------------------------------------------------------
    minimum: float | None = None
    median: float | None = None
    maximum: float | None = None

    # --- date ------------------------------------------------------------
    earliest: str | None = None
    latest: str | None = None

    # --- numerical and date ----------------------------------------------
    bins: tuple[Bin, ...] = ()

    # --- categorical -----------------------------------------------------
    top: tuple[TopValue, ...] = ()
    others_count: int = 0
    others_distinct: int = 0

    # --- text ------------------------------------------------------------
    length_min: int | None = None
    length_median: float | None = None
    length_max: int | None = None
    samples: tuple[str, ...] = ()

    # --- constant --------------------------------------------------------
    value: str | None = None

    @property
    def null_share(self) -> float:
        return 0.0 if self.total == 0 else 1.0 - self.present / self.total


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """The whole bundle — one Computation, one fingerprint (§11.8.1)."""

    row_count: int
    columns: tuple[ColumnProfile, ...] = field(default_factory=tuple)


# --------------------------------------------------------------- SQL parts ---

_SLOT = "@@col@@"
_PRESENT = f"{_SLOT} IS NOT NULL AND trim({_SLOT}) <> ''"
_TRIM = f"trim({_SLOT})"

#: A value readable as a number: whole or fractional, by the shape rules
#: inference uses. Anything else becomes NULL and is counted, never guessed at.
_AS_NUMBER = (
    f"CASE WHEN {_PRESENT} AND (regexp_matches({_TRIM}, '{_INTEGER_RE}')"
    f" OR regexp_matches({_TRIM}, '{_DECIMAL_RE}'))"
    f" THEN CAST({_TRIM} AS DOUBLE) END"
)

#: Same for a point in time. The shape rejects `inf`; the cast rejects
#: `2024-13-45`, which has a perfectly good shape and is not a date.
_AS_MOMENT = (
    f"CASE WHEN {_PRESENT} AND (regexp_matches({_TRIM}, '{_DATETIME_RE}')"
    f" OR regexp_matches({_TRIM}, '{_DATE_RE}'))"
    f" THEN try_cast({_TRIM} AS TIMESTAMP) END"
)

#: What a column **declared** boolean counts as true and as false.
#:
#: `1` and `0` are here and are deliberately **not** in `_BOOLEAN_WORDS`, which
#: is what inference reads. The two lists answer different questions and the
#: split is the whole point (D-068):
#:
#: - *Should this column be treated as a boolean?* — inference, and it must not
#:   guess `1,0,1,1` because that is equally a count of items. Guessing wrong
#:   turns arithmetic into logic.
#: - *This column **is** a boolean; what do its values mean?* — here, where
#:   somebody has already answered the first question. There is nothing left to
#:   guess, and refusing to read `1` as true at that point is the product
#:   ignoring a declaration it asked for.
#:
#: Compared with `lower(trim(...))`, so `TRUE`, `True`, `Y` and `t` all land.
_TRUE_WORDS = "('true','t','yes','y','1')"
_FALSE_WORDS = "('false','f','no','n','0')"

#: Per-column aggregates cheap enough to compute for every column at once.
#: Order matters: :func:`_scalars` unpacks by position.
_SCALAR_SQL = ", ".join(
    (
        f"count(*) FILTER (WHERE {_PRESENT})",
        f"count(DISTINCT {_TRIM}) FILTER (WHERE {_PRESENT})",
        f"count({_AS_NUMBER})",
        f"min({_AS_NUMBER})",
        f"median({_AS_NUMBER})",
        f"max({_AS_NUMBER})",
        f"count({_AS_MOMENT})",
        f"min({_AS_MOMENT})",
        f"max({_AS_MOMENT})",
        f"min(length({_TRIM})) FILTER (WHERE {_PRESENT})",
        f"median(length({_TRIM})) FILTER (WHERE {_PRESENT})",
        f"max(length({_TRIM})) FILTER (WHERE {_PRESENT})",
        f"count(*) FILTER (WHERE {_PRESENT} AND lower({_TRIM}) IN {_TRUE_WORDS})",
        f"count(*) FILTER (WHERE {_PRESENT} AND lower({_TRIM}) IN {_FALSE_WORDS})",
    )
)

#: Three aggregates left with the quality warnings (D-041): a count of values
#: padded with spaces, and two shape counts read against ``present``. They fed
#: PQ-8, PQ-9 and PQ-10 and nothing else, so keeping them would have meant three
#: regexp passes per column computing numbers no caller could ask for.
_SCALAR_FIELDS = 14


@dataclass(frozen=True, slots=True)
class _Scalars:
    """One column's row out of the single scalar pass."""

    present: int
    distinct: int
    numbers: int
    minimum: float | None
    median: float | None
    maximum: float | None
    moments: int
    earliest: str | None
    latest: str | None
    length_min: int | None
    length_median: float | None
    length_max: int | None
    true_count: int
    false_count: int


def _scalars(row: tuple[object, ...], index: int) -> _Scalars:
    """Unpack one column's slice of the flat aggregate row."""
    base = 1 + index * _SCALAR_FIELDS

    def num(offset: int) -> float | None:
        """A float, or nothing. DuckDB returns `Decimal` for some aggregates."""
        value = row[base + offset]
        return None if value is None else float(value)  # type: ignore[arg-type]

    def whole(offset: int) -> int | None:
        value = row[base + offset]
        return None if value is None else int(value)  # type: ignore[call-overload]

    def count(offset: int) -> int:
        """A COUNT never returns NULL, which is why this one cannot be None."""
        value: int = int(row[base + offset])  # type: ignore[call-overload]
        return value

    def text(offset: int) -> str | None:
        value = row[base + offset]
        return None if value is None else str(value)

    return _Scalars(
        present=count(0),
        distinct=count(1),
        numbers=count(2),
        minimum=num(3),
        median=num(4),
        maximum=num(5),
        moments=count(6),
        earliest=text(7),
        latest=text(8),
        length_min=whole(9),
        length_median=num(10),
        length_max=whole(11),
        true_count=count(12),
        false_count=count(13),
    )


def _kind(stats: _Scalars, logical_type: LogicalType) -> str:
    """Which of the eight shapes this column gets (§11.8.3).

    The order is the specification, not an implementation detail. Reversing any
    two of the first three produces a histogram with one bar for a constant
    column, which is arithmetically correct and about nothing (§11.7.1).

    There was a fourth override until 2026-08-21: a column whose values were
    ≥99% distinct became ``identifier`` and was shown by example rather than by
    histogram. It was removed on the product owner's decision, and the cost is
    stated rather than hidden — ``PassengerId`` now gets a median of 446 and a
    flat ten-bar histogram, which is exactly the reading §11.7.1 warns about.
    Three complaints drove it out and all three were about the *guess*: it fired
    on high-precision measurements, it could never fire on a string key (the
    check only ran for numerical and categorical), and nobody could correct it.
    """
    if stats.present == 0:
        return "empty"
    if logical_type is LogicalType.UNSUPPORTED:
        return "unsupported"
    if stats.distinct == 1:
        return "constant"
    return logical_type.value


def _bin_edges(low: float, high: float, count: int) -> list[float]:
    """``count`` buckets between two values, edges included.

    A degenerate range — every value identical — would divide by zero, and a
    column like that is `constant` anyway, so it never reaches here. The guard
    stays because "never reaches here" is a claim about callers.
    """
    if count < 1 or high <= low:
        return [low, high if high > low else low + 1.0]
    width = (high - low) / count
    return [low + width * step for step in range(count + 1)]


class ProfileReader:
    """Reads §11.8's bundle out of one dataset version.

    Takes the engine rather than being part of it: ``TableEngine`` is the
    protocol §13.3.1 L3 constrains to ``DataHandle``, and widening it with a
    method only the Profile tab uses would make every implementer carry it.
    """

    def __init__(self, engine: DuckDBEngine) -> None:
        self._engine = engine

    def describe(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        top_n: int = 3,
        n_bins: int = 10,
        samples: int = 3,
    ) -> DatasetProfile:
        source = self._engine._source(handle)
        physical = {c.name: c for c in self._engine.columns(handle)}
        columns = sorted(contract.columns, key=lambda c: c.ordinal)
        if not columns:
            return DatasetProfile(row_count=0)

        projection = ", ".join(
            _SCALAR_SQL.replace(_SLOT, _quote(c.name)) for c in columns if c.name in physical
        )
        present_columns = [c for c in columns if c.name in physical]
        if not present_columns:
            return DatasetProfile(row_count=self._engine.row_count(handle))

        row = (
            self._engine._cursor()
            .execute(f"SELECT count(*), {projection} FROM read_parquet(?)", [source])  # noqa: S608
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("dataset profile returned nothing")

        total = int(row[0])
        profiles = tuple(
            self._column(
                source=source,
                spec=spec,
                physical_type=physical[spec.name].physical_type,
                stats=_scalars(row, index),
                total=total,
                top_n=top_n,
                n_bins=n_bins,
                samples=samples,
            )
            for index, spec in enumerate(present_columns)
        )
        return DatasetProfile(row_count=total, columns=profiles)

    # ------------------------------------------------------------ per column --

    def _column(
        self,
        *,
        source: str,
        spec: object,
        physical_type: str,
        stats: _Scalars,
        total: int,
        top_n: int,
        n_bins: int,
        samples: int,
    ) -> ColumnProfile:
        name: str = spec.name  # type: ignore[attr-defined]
        ordinal: int = spec.ordinal  # type: ignore[attr-defined]
        logical: LogicalType = spec.logical_type  # type: ignore[attr-defined]

        kind = _kind(stats, logical)
        top: tuple[TopValue, ...] = ()
        others_count = others_distinct = 0

        # The top-N query runs for `categorical` and for `constant`, which needs
        # the one value it holds to print it.
        if kind in ("categorical", "constant"):
            top, others_count, others_distinct = self._top_values(source, name, top_n, stats)

        common = {
            "name": name,
            "ordinal": ordinal,
            "physical_type": physical_type,
            "logical_type": logical,
            "total": total,
            "present": stats.present,
            "distinct": stats.distinct,
            "kind": kind,
        }

        if kind == "empty":
            return ColumnProfile(**common)  # type: ignore[arg-type]

        if kind == "unsupported":
            return ColumnProfile(**common)  # type: ignore[arg-type]

        if kind == "constant":
            return ColumnProfile(
                **common,  # type: ignore[arg-type]
                value=top[0].value if top else None,
            )

        if kind == LogicalType.NUMERICAL.value:
            return ColumnProfile(
                **common,  # type: ignore[arg-type]
                conforming=stats.numbers,
                minimum=stats.minimum,
                median=stats.median,
                maximum=stats.maximum,
                bins=self._numeric_bins(source, name, stats, n_bins),
            )

        if kind == LogicalType.DATE.value:
            return ColumnProfile(
                **common,  # type: ignore[arg-type]
                conforming=stats.moments,
                earliest=stats.earliest,
                latest=stats.latest,
                bins=self._date_bins(source, name, n_bins),
            )

        if kind == LogicalType.BOOLEAN.value:
            return ColumnProfile(
                **common,  # type: ignore[arg-type]
                conforming=stats.true_count + stats.false_count,
                top=(
                    TopValue("true", stats.true_count),
                    TopValue("false", stats.false_count),
                ),
            )

        if kind == LogicalType.CATEGORICAL.value:
            return ColumnProfile(
                **common,  # type: ignore[arg-type]
                conforming=stats.present,
                top=top,
                others_count=others_count,
                others_distinct=others_distinct,
            )

        return ColumnProfile(
            **common,  # type: ignore[arg-type]
            conforming=stats.present,
            length_min=stats.length_min,
            length_median=stats.length_median,
            length_max=stats.length_max,
            samples=self._samples(source, name, samples),
        )

    # ------------------------------------------------------ distribution SQL --

    def _top_values(
        self, source: str, name: str, top_n: int, stats: _Scalars
    ) -> tuple[tuple[TopValue, ...], int, int]:
        """The most common values, and an honest account of the rest.

        Ordered by count and then by the value itself. The tiebreak is not
        decoration: two categories with identical counts would otherwise come
        back in whatever order the scan produced, and two calls with the same
        fingerprint would disagree — INV-6, broken by a missing ORDER BY.
        """
        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT trim({column}) AS v, count(*) AS n FROM read_parquet(?)"  # noqa: S608
                f" WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                f" GROUP BY v ORDER BY n DESC, v ASC LIMIT ?",
                [source, top_n],
            )
            .fetchall()
        )
        top = tuple(TopValue(value=str(v), count=int(n)) for v, n in rows)
        counted = sum(item.count for item in top)
        return top, stats.present - counted, max(0, stats.distinct - len(top))

    def _numeric_bins(
        self, source: str, name: str, stats: _Scalars, n_bins: int
    ) -> tuple[Bin, ...]:
        """A histogram over the values that are actually numbers.

        Edges are computed here and sent into the query, never inferred by the
        database — §11.8.6(c). An auto-binning rule that picks its own
        boundaries makes two calls with the same fingerprint disagree on where
        the bars fall, which is INV-6 broken somewhere nobody would look.
        """
        if stats.minimum is None or stats.maximum is None or stats.numbers == 0:
            return ()

        edges = _bin_edges(stats.minimum, stats.maximum, n_bins)
        column = _quote(name)
        value = _AS_NUMBER.replace(_SLOT, column)

        # `least` clamps the maximum into the last bucket. Without it the single
        # largest value lands in bin `n_bins`, one past the end, and the tallest
        # bar in a right-skewed column silently disappears.
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT least(floor(({value} - ?) / ?), ?) AS b, count(*)"  # noqa: S608
                f" FROM read_parquet(?) WHERE {value} IS NOT NULL"
                f" GROUP BY b ORDER BY b",
                [
                    stats.minimum,
                    (edges[-1] - edges[0]) / n_bins,
                    n_bins - 1,
                    source,
                ],
            )
            .fetchall()
        )
        counts = {int(b): int(n) for b, n in rows if b is not None}
        return tuple(
            Bin(lower=edges[i], upper=edges[i + 1], count=counts.get(i, 0)) for i in range(n_bins)
        )

    def _date_bins(self, source: str, name: str, n_bins: int) -> tuple[Bin, ...]:
        """The same histogram over epoch seconds, so the axis is time.

        Edges are returned as numbers rather than timestamps on purpose: the
        card draws bars, and a bar needs a width. The two ends a reader actually
        sees — earliest and latest — travel separately, already formatted.
        """
        column = _quote(name)
        value = _AS_MOMENT.replace(_SLOT, column)
        seconds = f"epoch({value})"

        bounds = (
            self._engine._cursor()
            .execute(
                f"SELECT min({seconds}), max({seconds}) FROM read_parquet(?)",  # noqa: S608
                [source],
            )
            .fetchone()
        )
        if bounds is None or bounds[0] is None:
            return ()

        low, high = float(bounds[0]), float(bounds[1])
        edges = _bin_edges(low, high, n_bins)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT least(floor(({seconds} - ?) / ?), ?) AS b, count(*)"  # noqa: S608
                f" FROM read_parquet(?) WHERE {value} IS NOT NULL"
                f" GROUP BY b ORDER BY b",
                [low, (edges[-1] - edges[0]) / n_bins, n_bins - 1, source],
            )
            .fetchall()
        )
        counts = {int(b): int(n) for b, n in rows if b is not None}
        return tuple(
            Bin(lower=edges[i], upper=edges[i + 1], count=counts.get(i, 0)) for i in range(n_bins)
        )

    def _samples(self, source: str, name: str, count: int) -> tuple[str, ...]:
        """A few real values, chosen the same way every time.

        §11.7.3 asks for a seeded sample. A seeded PRNG would do it; ordering by
        the value itself does it with nothing to seed and nothing to remember,
        and it has a second virtue — the examples are stable when the file grows
        at the end, which is what makes two runs comparable by eye.
        """
        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT DISTINCT trim({column}) AS v FROM read_parquet(?)"  # noqa: S608
                f" WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                f" ORDER BY v LIMIT ?",
                [source, count],
            )
            .fetchall()
        )
        return tuple(str(v) for (v,) in rows)


__all__ = [
    "Bin",
    "ColumnProfile",
    "DatasetProfile",
    "ProfileReader",
    "TopValue",
]
