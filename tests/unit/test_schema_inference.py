"""Logical type inference (FR-C.1, FR-B.3, P0-7).

The rule under test is a single sentence: **a type is assigned only when every
present value conforms.** Everything else here is a consequence of it.

That rule exists because of one file. ``messy_sales.legacy_code`` is 4 850 of
5 000 pure digits, and any threshold below 100% types it ``integer`` — at which
point 150 real values become nulls the first time anything casts the column,
silently. FR-B.3 was written after exactly that happened, so the tests that
matter most here are the *near misses*: the columns a more confident detector
would get wrong.
"""

from __future__ import annotations

import pytest

from app.domain.enums import LogicalType
from app.schema.inference import (
    CATEGORY_LIKE_DISTINCT,
    MAX_CATEGORICAL_DISTINCT,
    build_columns,
    infer,
)
from app.storage.engine import ColumnStatistics


def _stats(
    *,
    name: str = "c",
    ordinal: int = 0,
    physical_type: str = "VARCHAR",
    total: int = 1_000,
    non_null: int | None = None,
    distinct: int = 500,
    integer_like: int = 0,
    decimal_like: int = 0,
    boolean_like: int = 0,
    date_like: int = 0,
    datetime_like: int = 0,
) -> ColumnStatistics:
    return ColumnStatistics(
        name=name,
        ordinal=ordinal,
        physical_type=physical_type,
        total=total,
        non_null=total if non_null is None else non_null,
        distinct=distinct,
        integer_like=integer_like,
        decimal_like=decimal_like,
        boolean_like=boolean_like,
        date_like=date_like,
        datetime_like=datetime_like,
    )


# ------------------------------------------------------- the coverage rule ---


@pytest.mark.invariant
def test_a_column_that_is_almost_numeric_is_text() -> None:
    """FR-B.3's origin story, as a unit test.

    97% is not "numeric with a few bad rows". It is a text column, because the
    other 3% are values a user put there on purpose and typing them away is
    data loss — the silent kind, discovered three analyses later if at all.
    """
    result = infer(_stats(total=5_000, distinct=4_868, integer_like=4_850))

    assert result.logical_type is LogicalType.TEXT
    assert result.confidence == 0.5
    assert "150 are not" in result.reason, "the reason must name what would have been lost"


@pytest.mark.parametrize("conforming", [999, 998, 900, 1])
def test_one_non_conforming_value_is_enough_to_refuse_a_type(conforming: int) -> None:
    """There is no threshold to tune, which is the point.

    A percentage would need a number, every number is arguable, and whichever
    number won would still discard values below it.
    """
    assert infer(_stats(integer_like=conforming)).logical_type is LogicalType.TEXT


def test_a_fully_numeric_column_is_numeric() -> None:
    assert infer(_stats(integer_like=1_000)).logical_type is LogicalType.INTEGER


def test_mixed_whole_and_fractional_numbers_are_decimal() -> None:
    """Titanic's ``Age``: 689 whole, 25 fractional, nothing else.

    Typing it ``integer`` because most values are whole would round away every
    half-year — arithmetically defensible and factually wrong.
    """
    result = infer(_stats(total=891, non_null=714, distinct=88, integer_like=689, decimal_like=25))
    assert result.logical_type is LogicalType.DECIMAL


def test_whole_numbers_alone_are_never_decimal() -> None:
    """``decimal_like`` counts values with a point in them, and nothing else."""
    assert infer(_stats(integer_like=1_000, decimal_like=0)).logical_type is LogicalType.INTEGER


# ------------------------------------------------------------- dates ---------


def test_a_fully_parseable_date_column_is_a_date() -> None:
    result = infer(_stats(total=5_000, distinct=365, date_like=5_000))
    assert result.logical_type is LogicalType.DATE
    assert result.confidence == 1.0


def test_a_timestamp_column_does_not_become_a_date() -> None:
    """Typing a timestamp as a date drops the time of day, silently.

    The shape rules are written so the two counts are disjoint; this pins the
    consequence rather than the mechanism.
    """
    result = infer(_stats(total=1_000, distinct=1_000, datetime_like=1_000))
    assert result.logical_type is LogicalType.DATETIME


def test_a_column_that_is_almost_dates_is_text_and_says_so() -> None:
    result = infer(_stats(total=1_000, distinct=900, date_like=950))
    assert result.logical_type is LogicalType.TEXT
    assert "50 do not" in result.reason


# ------------------------------------------------------------ booleans -------


def test_word_booleans_are_boolean() -> None:
    """``Yes``/``No`` in tips.csv. Unambiguous, so full confidence."""
    result = infer(_stats(total=244, distinct=2, boolean_like=244))
    assert result.logical_type is LogicalType.BOOLEAN


def test_zero_and_one_are_integers_rather_than_booleans() -> None:
    """Titanic's ``Survived``. A deliberate refusal to guess.

    ``0``/``1`` is equally an integer, and choosing wrong turns arithmetic into
    logic — a mean of 0.38 becomes meaningless, or a true/false becomes
    summable. The detector says integer and flags the ambiguity; the user, who
    knows what the column means, decides.
    """
    result = infer(_stats(total=891, distinct=2, integer_like=891))
    assert result.logical_type is LogicalType.INTEGER
    assert result.confidence == 0.6
    assert "coded category" in result.reason


# -------------------------------------------------- categorical vs text ------


def test_few_repeated_values_are_categorical() -> None:
    result = infer(_stats(total=5_000, distinct=7))
    assert result.logical_type is LogicalType.CATEGORICAL
    assert "7 distinct" in result.reason


def test_mostly_unique_values_are_text_however_few_they_are() -> None:
    """The ratio bound. 4 800 distinct in 5 000 rows is a name, not a category.

    ``messy_sales.customer_name``, and the case PQ-6 warns about from the other
    direction.
    """
    assert infer(_stats(total=5_000, distinct=4_800)).logical_type is LogicalType.TEXT


def test_many_distinct_values_are_text_however_small_the_ratio() -> None:
    """The count bound, which the ratio alone would miss.

    400 product names in a million rows is a ratio of 0.0004 — and a 400-row
    frequency table is not a profile anyone can read (§11.7.3).
    """
    stats = _stats(total=1_000_000, distinct=MAX_CATEGORICAL_DISTINCT + 1)
    assert infer(stats).logical_type is LogicalType.TEXT


def test_a_small_file_does_not_get_a_confident_categorical() -> None:
    """Ten distinct values in twenty rows says nothing — arithmetic guarantees it."""
    result = infer(_stats(total=20, distinct=8))
    assert result.logical_type is LogicalType.CATEGORICAL
    assert result.confidence < 1.0


# ------------------------------------------------------------- edges ---------


def test_an_empty_column_is_text_with_no_confidence() -> None:
    """Honest rather than convenient: there was nothing to infer from."""
    result = infer(_stats(total=1_000, non_null=0, distinct=0))
    assert result.logical_type is LogicalType.TEXT
    assert result.confidence == 0.0
    assert "no values" in result.reason


def test_a_nested_column_is_unsupported_rather_than_flattened() -> None:
    """A Parquet upload can carry a LIST or STRUCT. §9.6 is single-table.

    Saying so beats stringifying it into something that looks analysable (P6).
    """
    result = infer(_stats(physical_type="STRUCT(a INTEGER)", distinct=10))
    assert result.logical_type is LogicalType.UNSUPPORTED


def test_a_unique_integer_column_is_flagged_as_a_possible_identifier() -> None:
    """PQ-3. Still an integer — but ``mean(order_id)`` is a number about nothing."""
    result = infer(_stats(total=5_000, distinct=5_000, integer_like=5_000))
    assert result.logical_type is LogicalType.INTEGER
    assert result.confidence == 0.7
    assert "identifier" in result.reason


def test_the_category_like_threshold_is_exclusive_at_its_edge() -> None:
    """Boundaries get their own test, because off-by-one is where they fail."""
    at = infer(_stats(total=5_000, distinct=CATEGORY_LIKE_DISTINCT, integer_like=5_000))
    just_over = infer(_stats(total=5_000, distinct=CATEGORY_LIKE_DISTINCT + 1, integer_like=5_000))
    assert at.confidence == 0.6
    assert just_over.confidence == 1.0


# ------------------------------------------------------------ contract -------


def test_version_one_columns_carry_no_human_decisions() -> None:
    """§9.2: version 1 is pure auto-detection.

    Roles, format hints, null markers and ``overridden_by`` all belong to later
    versions. Keeping v1 clean is what makes "what did the machine think before
    anyone touched it?" a question with an answer.
    """
    columns = build_columns(
        [
            _stats(name="b", ordinal=1, distinct=3),
            _stats(name="a", ordinal=0, integer_like=1_000),
        ]
    )

    assert [c.name for c in columns] == ["a", "b"], "ordinals decide order, not input order"
    assert all(c.role is None for c in columns)
    assert all(c.null_markers == () for c in columns)
    assert all(c.overridden_by is None for c in columns)
    assert all(c.detection_reason for c in columns), "every column explains itself"


@pytest.mark.invariant
def test_inference_is_a_pure_function_of_the_measurements() -> None:
    """INV-6 at this layer: same input, same schema, every time.

    Inference feeds ``schema_contract_id``, which feeds every fingerprint
    (§9.4). A detector that wavered would make identical analyses miss cache
    for reasons nobody could see.
    """
    stats = _stats(total=5_000, distinct=7)
    assert len({infer(stats) for _ in range(50)}) == 1
