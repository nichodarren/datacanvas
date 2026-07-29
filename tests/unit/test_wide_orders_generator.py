"""The large-dataset generator (Gate 2, §20).

The file itself is 480 MB and deliberately not committed, so its SHA-256 in
``golden_queries.md`` §3 is only a contract if the generator is genuinely
deterministic. That is what is checked here — at a size that costs milliseconds,
because a test nobody can afford to run is not a guard.

Reproducibility means *fresh process, same bytes*, and the shape that quietly
breaks it is a module-level RNG: it advances with every call, so the second
invocation in one process differs from the first. Reproducible as a script,
not reproducible as a function — a distinction invisible until something calls
it twice, which is exactly what a reproducibility test does.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "eval" / "fixtures"))

from build_wide_orders import build

from app.domain.enums import LogicalType
from app.schema.inference import infer
from app.storage.engine import ColumnStatistics


@pytest.mark.invariant
def test_the_generator_is_reproducible_within_a_process() -> None:
    """Two calls, same bytes. The property the committed SHA-256 rests on."""
    assert build(500).equals(build(500))


def test_a_different_seed_produces_different_data() -> None:
    """The control. "Deterministic" is only meaningful if the seed does anything."""
    assert not build(500).equals(build(500, seed=1))


def test_every_inferable_logical_type_is_represented() -> None:
    """A large dataset that is all numbers tests performance and nothing else.

    Each D-029 rule needs at least one column here, or scale is only ever
    exercised against the easy half of the detector.
    """
    frame = build(2_000)
    assert frame.width == 12

    # Spot-check the columns that carry the interesting rules, using the same
    # inference the pipeline uses rather than re-deriving expectations.
    def kind(column: str, **counts: int) -> LogicalType:
        values = frame[column].to_list()
        present = [v for v in values if v not in (None, "")]
        return infer(
            ColumnStatistics(
                name=column,
                ordinal=0,
                physical_type="VARCHAR",
                total=len(values),
                non_null=len(present),
                distinct=len(set(present)),
                **{
                    field: counts.get(field, 0)
                    for field in (
                        "integer_like",
                        "decimal_like",
                        "boolean_like",
                        "date_like",
                        "datetime_like",
                    )
                },
            )
        ).logical_type

    present = [v for v in frame["legacy_code"].to_list() if v]
    numeric = sum(v.isdigit() for v in present)
    assert len(present) - numeric > 0, "legacy_code must contain non-numeric values"
    assert kind("legacy_code", integer_like=numeric) is LogicalType.TEXT

    assert kind("region", **{}) is LogicalType.CATEGORICAL
    assert kind("customer_ref", **{}) is LogicalType.TEXT


def test_the_note_column_is_mostly_empty_on_purpose() -> None:
    """PQ-14 territory, and the case that exercises "present" versus "null"."""
    values = build(2_000)["note"].to_list()
    empty = sum(1 for value in values if not value)
    assert empty / len(values) > 0.5
