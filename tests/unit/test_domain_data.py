"""Rules carried by the data-identity entities (DESIGN.md §9.2).

INV-2 and INV-3 have two enforcement points. The in-process half lives here
(frozen dataclasses, version rules); the storage half is a Postgres trigger,
tested in ``tests/integration/test_immutability_invariants.py``. Neither alone
is a guarantee.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.domain import (
    ColumnSpec,
    DatasetVersion,
    InvariantViolation,
    LogicalType,
    SchemaContract,
)
from app.domain.ids import DatasetId, DatasetVersionId, SchemaContractId, UserId

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
USER = UserId(UUID("00000000-0000-4000-8000-000000000001"))
DATASET = DatasetId(UUID("00000000-0000-4000-8000-000000000010"))
VERSION = DatasetVersionId(UUID("00000000-0000-4000-8000-000000000011"))


def _column(name: str, ordinal: int, **overrides: object) -> ColumnSpec:
    defaults: dict[str, object] = {
        "name": name,
        "ordinal": ordinal,
        "physical_type": "INT64",
        "logical_type": LogicalType.INTEGER,
    }
    return ColumnSpec(**{**defaults, **overrides})  # type: ignore[arg-type]


def _version(**overrides: object) -> DatasetVersion:
    defaults: dict[str, object] = {
        "id": VERSION,
        "dataset_id": DATASET,
        "version_no": 1,
        "content_hash": "f" * 64,
        "parquet_uri": "storage://workspaces/w/datasets/d/versions/v/data.parquet",
        "row_count": 891,
        "column_count": 12,
        "byte_size": 1024,
        "ingested_at": T0,
        "ingested_by": USER,
    }
    return DatasetVersion(**{**defaults, **overrides})  # type: ignore[arg-type]


def _contract(**overrides: object) -> SchemaContract:
    defaults: dict[str, object] = {
        "id": SchemaContractId(uuid4()),
        "dataset_version_id": VERSION,
        "version_no": 1,
        "columns": (_column("id", 0), _column("amount", 1)),
        "created_at": T0,
    }
    return SchemaContract(**{**defaults, **overrides})  # type: ignore[arg-type]


# ------------------------------------------------------- dataset version ----


@pytest.mark.invariant
def test_dataset_version_cannot_be_mutated_in_process() -> None:
    """INV-2, in-process half. The storage half is a database trigger."""
    version = _version()
    with pytest.raises(dataclasses.FrozenInstanceError):
        version.row_count = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"version_no": 0},
        {"row_count": -1},
        {"column_count": -1},
        {"byte_size": -1},
        {"content_hash": ""},
        {"parquet_uri": "  "},
    ],
)
def test_dataset_version_rejects_impossible_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(InvariantViolation):
        _version(**kwargs)


# -------------------------------------------------------- schema contract ----


@pytest.mark.invariant
def test_schema_contract_cannot_be_mutated_in_process() -> None:
    """INV-3: a correction is a new version, never an edit."""
    contract = _contract()
    with pytest.raises(dataclasses.FrozenInstanceError):
        contract.version_no = 2  # type: ignore[misc]


def test_version_one_is_pure_auto_detection() -> None:
    """§9.2: version 1 is always auto-detect and derives from nothing."""
    with pytest.raises(InvariantViolation):
        _contract(version_no=1, derived_from=SchemaContractId(uuid4()))


def test_corrected_contract_must_record_its_predecessor() -> None:
    """Losing the chain would make "why is this column text now?" unanswerable."""
    with pytest.raises(InvariantViolation):
        _contract(version_no=2, derived_from=None)

    parent = SchemaContractId(uuid4())
    assert _contract(version_no=2, derived_from=parent).derived_from == parent


def test_contract_rejects_duplicate_column_names() -> None:
    with pytest.raises(InvariantViolation):
        _contract(columns=(_column("amount", 0), _column("amount", 1)))


def test_contract_rejects_sparse_ordinals() -> None:
    """Ordinals are positions in the file, so a gap means something was lost."""
    with pytest.raises(InvariantViolation):
        _contract(columns=(_column("id", 0), _column("amount", 5)))


def test_column_names_follow_ordinal_order_not_insertion_order() -> None:
    contract = _contract(columns=(_column("amount", 1), _column("id", 0)))
    assert contract.column_names == ("id", "amount")


def test_column_lookup_by_name() -> None:
    contract = _contract()
    assert contract.column("amount").ordinal == 1
    with pytest.raises(InvariantViolation):
        contract.column("nope")


# ------------------------------------------------------------ column spec ----


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_detection_confidence_stays_within_bounds(confidence: float) -> None:
    with pytest.raises(InvariantViolation):
        _column("x", 0, detection_confidence=confidence)


def test_override_is_visible_on_the_column() -> None:
    """FR-C.2: a user-corrected type must be distinguishable from a guess."""
    assert not _column("x", 0).is_user_overridden
    assert _column("x", 0, overridden_by=USER).is_user_overridden
