"""Inference against the bundled datasets, end to end (FR-B.3, FR-C.1).

The unit tests next door check the rules against constructed numbers. This
checks the whole chain — ingest, a full-file scan, the shape rules, the
decision — against the actual bytes in ``eval/datasets/``.

Both are needed and they fail for different reasons. The unit tests break when
a rule changes; these break when reality does not match what the rules assumed,
which is the failure nobody predicts. ``legacy_code`` is the standing example:
it was found by running real data, not by reasoning about it.

These expectations are a **contract**. If one of them changes, the change is
either a bug or a decision — and either way it belongs in the commit message,
not in a quietly edited assertion.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.authz import data_access
from app.authz.data_access import DataHandle
from app.domain.data import DatasetVersion
from app.domain.enums import LogicalType, SourceFormat
from app.domain.ids import DatasetId, DatasetVersionId, SessionId, UserId, WorkspaceId
from app.domain.principal import Principal
from app.ingest import normalize
from app.ingest.dialect import detect
from app.schema.inference import build_columns
from app.storage.engine import DuckDBEngine
from app.storage.object_store import FilesystemObjectStore
from app.storage.uri import dataset_version_data_uri

DATASETS = Path(__file__).resolve().parents[2] / "eval" / "datasets"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _types(tmp_path: Path, filename: str) -> dict[str, tuple[LogicalType, float]]:
    """Ingest a bundled file and report what the schema came out as."""
    store = FilesystemObjectStore(tmp_path)
    workspace, dataset, version_id = (
        WorkspaceId(uuid.uuid4()),
        DatasetId(uuid.uuid4()),
        DatasetVersionId(uuid.uuid4()),
    )
    uri = dataset_version_data_uri(workspace, dataset, version_id)

    raw = DATASETS / filename
    dialect = detect(raw.read_bytes(), is_prefix=False)
    info = normalize.normalize_file(raw, SourceFormat.CSV, store.writable_path(uri), dialect)

    version = DatasetVersion(
        id=version_id,
        dataset_id=dataset,
        version_no=1,
        content_hash=info.content_hash,
        parquet_uri=str(uri),
        row_count=info.row_count,
        column_count=info.column_count,
        byte_size=info.byte_size,
        ingested_at=T0,
        ingested_by=UserId(uuid.uuid4()),
    )
    handle = DataHandle(
        principal=Principal(
            user_id=UserId(uuid.uuid4()), session_id=SessionId(uuid.uuid4()), memberships={}
        ),
        workspace_id=workspace,
        version=version,
        uri=uri,
        _store=store,
        _grant=data_access._GRANT,
    )

    columns = build_columns(DuckDBEngine().column_statistics(handle))
    return {c.name: (c.logical_type, c.detection_confidence) for c in columns}


@pytest.mark.golden
def test_messy_sales_types(tmp_path: Path) -> None:
    """The fixture built to be hard, and the reason FR-B.3 says "whole file"."""
    types = _types(tmp_path, "messy_sales.csv")

    assert {name: kind for name, (kind, _) in types.items()} == {
        "order_id": LogicalType.INTEGER,
        "order_date": LogicalType.DATE,
        "region": LogicalType.CATEGORICAL,
        "customer_name": LogicalType.TEXT,
        "amount": LogicalType.DECIMAL,
        "discount_pct": LogicalType.DECIMAL,
        "qty": LogicalType.INTEGER,
        "status": LogicalType.CATEGORICAL,
        "notes": LogicalType.CATEGORICAL,
        "signup_date": LogicalType.DATE,
        "legacy_code": LogicalType.TEXT,
        "promised_date": LogicalType.DATE,
    }


@pytest.mark.golden
@pytest.mark.invariant
def test_the_column_that_defeats_sampling_stays_text(tmp_path: Path) -> None:
    """``legacy_code``, the reason this whole design is what it is.

    97% pure digits with the first alphanumeric value far past any sample
    window. Sample-based inference guesses integer and explodes mid-file;
    threshold-based inference guesses integer and silently nulls 150 rows.
    Neither is acceptable, and this is the test that says so.
    """
    kind, confidence = _types(tmp_path, "messy_sales.csv")["legacy_code"]

    assert kind is LogicalType.TEXT
    assert confidence == 0.5, "a near miss must be reported as one, not as certainty"


@pytest.mark.golden
def test_titanic_types(tmp_path: Path) -> None:
    """A clean public dataset, where the interesting cases are the ambiguous ones."""
    types = _types(tmp_path, "titanic.csv")
    kinds = {name: kind for name, (kind, _) in types.items()}

    assert kinds["Name"] is LogicalType.TEXT
    assert kinds["Sex"] is LogicalType.CATEGORICAL
    assert kinds["Embarked"] is LogicalType.CATEGORICAL
    assert kinds["Fare"] is LogicalType.DECIMAL
    # 689 whole ages and 25 fractional ones. Rounding the halves away would be
    # the tidier answer and the wrong one.
    assert kinds["Age"] is LogicalType.DECIMAL
    # Ticket numbers are 74% digits — below the near-miss bar, so plainly text.
    assert kinds["Ticket"] is LogicalType.TEXT

    # Coded categories stay numeric and say they might not be (PQ-4).
    for coded in ("Survived", "Pclass"):
        kind, confidence = types[coded]
        assert kind is LogicalType.INTEGER
        assert confidence == 0.6
    # And a unique integer says it might be an identifier (PQ-3).
    assert types["PassengerId"] == (LogicalType.INTEGER, 0.7)


@pytest.mark.golden
def test_tips_types(tmp_path: Path) -> None:
    """The one bundled file with a real word-boolean column."""
    kinds = {name: kind for name, (kind, _) in _types(tmp_path, "tips.csv").items()}

    assert kinds["smoker"] is LogicalType.BOOLEAN
    assert kinds["total_bill"] is LogicalType.DECIMAL
    assert kinds["day"] is LogicalType.CATEGORICAL


@pytest.mark.golden
def test_hotel_bookings_infers_without_choking_on_scale(tmp_path: Path) -> None:
    """32 columns, 119k rows, one pass — the shape a real upload has."""
    types = _types(tmp_path, "hotel_bookings.csv")

    assert len(types) == 32
    assert types["hotel"][0] is LogicalType.CATEGORICAL
    assert types["arrival_date_year"][0] is LogicalType.INTEGER
    assert types["adr"][0] is LogicalType.DECIMAL


@pytest.mark.golden
@pytest.mark.invariant
def test_the_same_file_always_infers_the_same_schema(tmp_path: Path) -> None:
    """INV-6 through the whole chain, not just the decision function.

    ``schema_contract_id`` enters every fingerprint (§9.4). If inference could
    vary between runs of the same file, two identical analyses would miss cache
    for a reason invisible to everyone involved.
    """
    runs = [
        tuple(sorted(_types(tmp_path / f"run{i}", "messy_sales.csv").items())) for i in range(3)
    ]
    assert len(set(runs)) == 1
