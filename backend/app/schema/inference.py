"""Deciding what a column *means* (FR-C.1, FR-B.3, P0-7).

The engine measures; this module decides. Nothing here reads data — it takes
:class:`ColumnStatistics` and returns a verdict, which makes every rule testable
without a file and makes the whole thing deterministic by construction (INV-6).

**The rule everything else follows from: a logical type is assigned only when
every present value conforms.** Not most, not 97% — every one.

That threshold is not conservatism for its own sake. It is FR-B.3's rationale
turned into an algorithm. ``messy_sales.legacy_code`` is 4 850 of 5 000 pure
digits: a 90% or 95% rule calls it ``integer``, and then 150 values that were
never numbers become nulls the moment anything casts the column. The data loss
is silent, it is invisible in a preview, and it is discovered — if ever — when a
count comes out wrong three analyses later. **A type that discards values is not
an inference, it is a decision to throw data away.**

So *coverage* decides the type, and **confidence measures something else
entirely: ambiguity.** A column can be unambiguously ``integer`` and still be
low-confidence because five distinct values on five thousand rows are much more
likely to be a category than a quantity (PQ-4). That is the signal FR-C.6 and
the §11.7.4 warnings are built on, and the number the UI uses to decide how
loudly to ask.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from app.domain.data import ColumnSpec
from app.domain.enums import LogicalType
from app.storage.engine import ColumnStatistics

#: Above this many distinct values a column is prose, not a category — however
#: small the ratio. A 5 000-row file with 400 distinct product names is not a
#: 400-way categorical, and offering it as one produces a frequency table
#: nobody can read (§11.7.3).
MAX_CATEGORICAL_DISTINCT: Final = 50

#: And a column whose values are mostly unique is not a category either, however
#: few of them there are. Both bounds are needed: the ratio alone mislabels tiny
#: files, the count alone mislabels wide ones.
MAX_CATEGORICAL_RATIO: Final = 0.5

#: Below this many rows, "few distinct values" says nothing — a 20-row file has
#: few distinct values in every column by arithmetic.
MIN_ROWS_FOR_CARDINALITY_SIGNAL: Final = 100

#: A numeric column with no more distinct values than this looks like a coded
#: category (PQ-4): Pclass, Survived, qty. Still typed numeric — that is what
#: the values *are* — but flagged as worth a second look.
CATEGORY_LIKE_DISTINCT: Final = 10

#: How much of a text column has to look numeric or date-shaped before the
#: near-miss is worth reporting (PQ-8, PQ-9).
NEAR_MISS_SHARE: Final = 0.9

#: Physical types the MVP can interpret at all. Anything else — a Parquet file
#: carrying a LIST, STRUCT or MAP column — is honestly unsupported rather than
#: quietly flattened into text (P6).
_SCALAR_PHYSICAL_PREFIXES: Final = (
    "VARCHAR",
    "BOOLEAN",
    "TINYINT",
    "SMALLINT",
    "INTEGER",
    "BIGINT",
    "HUGEINT",
    "UTINYINT",
    "USMALLINT",
    "UINTEGER",
    "UBIGINT",
    "FLOAT",
    "DOUBLE",
    "DECIMAL",
    "DATE",
    "TIME",
    "TIMESTAMP",
    "INTERVAL",
    "UUID",
)


@dataclass(frozen=True, slots=True)
class Inference:
    """One column's verdict, with the reasoning attached.

    ``reason`` is not decoration. FR-B.3 requires the detection be shown for
    correction, and "categorical" on its own gives a user nothing to agree or
    disagree with — "7 distinct values in 5 000 rows" does.
    """

    logical_type: LogicalType
    confidence: float
    reason: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be within 0..1, got {self.confidence}")


def _is_scalar(physical_type: str) -> bool:
    return physical_type.upper().startswith(_SCALAR_PHYSICAL_PREFIXES)


def _looks_like_a_category(stats: ColumnStatistics) -> bool:
    return (
        stats.distinct <= MAX_CATEGORICAL_DISTINCT
        and stats.share(stats.distinct) <= MAX_CATEGORICAL_RATIO
    )


def _numeric_confidence(stats: ColumnStatistics) -> tuple[float, str]:
    """How sure we are that a numeric column is really a quantity.

    Two competing readings, both from §11.7.4: very few distinct values suggests
    a coded category (PQ-4), and all-distinct integers suggest an identifier
    (PQ-3). Neither changes the *type* — the values are numbers either way — but
    both change what the column is *for*, and the user is the one who knows.
    """
    if stats.total < MIN_ROWS_FOR_CARDINALITY_SIGNAL:
        return 1.0, f"every value is numeric ({stats.non_null} values)"
    if stats.distinct <= CATEGORY_LIKE_DISTINCT:
        return 0.6, (
            f"numeric, but only {stats.distinct} distinct values in {stats.total} rows:"
            f" this may be a coded category rather than a quantity"
        )
    if stats.distinct == stats.non_null and stats.integer_like == stats.non_null:
        return 0.7, (
            f"numeric and unique across all {stats.non_null} values:"
            f" this may be an identifier rather than a quantity"
        )
    return 1.0, f"every value is numeric ({stats.non_null} values)"


def _text_confidence(stats: ColumnStatistics) -> tuple[float, str]:
    """Text is where the near misses land, and they are worth reporting.

    A column that is 97% numeric is text — nothing else is honest, because the
    other 3% are real values. But *why* it is text is exactly what the user
    needs to see, since the answer is usually "a handful of rows are dirty".
    """
    numeric = stats.share(stats.integer_like + stats.decimal_like)
    dated = stats.share(stats.date_like + stats.datetime_like)

    if numeric >= NEAR_MISS_SHARE:
        remainder = stats.non_null - stats.integer_like - stats.decimal_like
        return 0.5, (
            f"{numeric:.1%} of values are numeric, but {remainder} are not:"
            f" typed as text so those values are not discarded"
        )
    if dated >= NEAR_MISS_SHARE:
        remainder = stats.non_null - stats.date_like - stats.datetime_like
        return 0.5, (
            f"{dated:.1%} of values parse as dates, but {remainder} do not:"
            f" typed as text so those values are not discarded"
        )
    return 1.0, f"{stats.distinct} distinct values across {stats.non_null}, free text"


def infer(stats: ColumnStatistics) -> Inference:
    """The whole decision, in the order the checks have to happen.

    The ladder had two more rungs until 2026-08-21: ``datetime`` above ``date``,
    and ``integer`` above ``decimal``. Both pairs now answer with one type, so
    the ordering between them no longer decides anything — but the *shape* rules
    still do, and the reasons below still name which shape matched. A column of
    timestamps and a column of dates are both ``date``; which one it was is in
    ``physical_type`` and in the sentence this returns.
    """
    if not _is_scalar(stats.physical_type):
        return Inference(
            LogicalType.UNSUPPORTED,
            1.0,
            f"{stats.physical_type} is not a scalar column; the MVP works on flat tables (§9.6)",
        )

    if stats.is_empty:
        return Inference(
            LogicalType.TEXT,
            0.0,
            f"no values to infer from: all {stats.total} rows are empty or null",
        )

    present = stats.non_null

    if stats.boolean_like == present:
        return Inference(LogicalType.BOOLEAN, 1.0, f"every value is true/false ({present} values)")

    if stats.datetime_like == present:
        return Inference(LogicalType.DATE, 1.0, f"every value is a timestamp ({present})")

    if stats.date_like == present:
        return Inference(LogicalType.DATE, 1.0, f"every value is a date ({present})")

    # One rung where there were two. `integer_like` counts whole numbers and
    # `decimal_like` counts the rest, so their sum is "every value is a number"
    # whether or not any of them have a fractional part.
    if stats.integer_like + stats.decimal_like == present:
        confidence, reason = _numeric_confidence(stats)
        return Inference(LogicalType.NUMERICAL, confidence, reason)

    if _looks_like_a_category(stats):
        ratio = stats.share(stats.distinct)
        return Inference(
            LogicalType.CATEGORICAL,
            1.0 if stats.total >= MIN_ROWS_FOR_CARDINALITY_SIGNAL else 0.7,
            f"{stats.distinct} distinct values across {present} rows ({ratio:.1%})",
        )

    confidence, reason = _text_confidence(stats)
    return Inference(LogicalType.TEXT, confidence, reason)


def build_columns(statistics: Sequence[ColumnStatistics]) -> tuple[ColumnSpec, ...]:
    """Turn a whole-file measurement into the ``columns[]`` of a SchemaContract.

    Version 1 is **pure auto-detection** (§9.2): no format hints, no
    null markers, and ``overridden_by`` empty on every column. Everything a
    person decides arrives in version 2 or later, and keeping v1 free of it is
    what makes "what did the machine think before anyone touched it?" a
    question with an answer.
    """
    return tuple(
        ColumnSpec(
            name=stats.name,
            ordinal=stats.ordinal,
            physical_type=stats.physical_type,
            logical_type=(result := infer(stats)).logical_type,
            detection_confidence=result.confidence,
            detection_reason=result.reason,
        )
        for stats in sorted(statistics, key=lambda s: s.ordinal)
    )


__all__ = [
    "CATEGORY_LIKE_DISTINCT",
    "MAX_CATEGORICAL_DISTINCT",
    "MAX_CATEGORICAL_RATIO",
    "MIN_ROWS_FOR_CARDINALITY_SIGNAL",
    "NEAR_MISS_SHARE",
    "Inference",
    "build_columns",
    "infer",
]
