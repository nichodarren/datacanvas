"""The analytics engine (§10.2), including its half of INV-7 (§13.3.1 L3).

Two things are proved here that are easy to assume instead.

* **Pagination is stable.** FR-D.1 promises a user can page through millions of
  rows. That promise is only kept while the engine returns rows in file order;
  if DuckDB is free to reorder parallel scan results, rows repeat and rows
  disappear as the user pages — silently, and only on files big enough to be
  scanned in parallel, which is to say only on real data.
* **The engine will not read a path.** A ``DataHandle`` is proof of
  authorization; a string is not.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import pytest

from app.authz import data_access
from app.authz.data_access import DataHandle
from app.domain.data import DatasetVersion
from app.domain.ids import DatasetId, DatasetVersionId, SessionId, UserId, WorkspaceId
from app.domain.principal import Principal
from app.storage.engine import MAX_PAGE_SIZE, DuckDBEngine, EngineError
from app.storage.object_store import FilesystemObjectStore
from app.storage.uri import dataset_version_data_uri

WS = WorkspaceId(uuid.UUID("00000000-0000-4000-8000-00000000ee01"))
DS = DatasetId(uuid.UUID("00000000-0000-4000-8000-00000000ee02"))
DV = DatasetVersionId(uuid.UUID("00000000-0000-4000-8000-00000000ee03"))
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

ROWS = 3_000


def _handle(tmp_path: Path, frame: pl.DataFrame) -> DataHandle:
    """Build a handle without a database.

    This reaches for ``data_access._GRANT`` deliberately. The module says a
    determined caller can do exactly this, and a test is a determined caller —
    the guarantee INV-7 offers is that the *accidental* path fails, and
    ``test_authz_boundaries.py`` is what holds that line. Going through Postgres
    to unit-test row ordering would test the database instead.
    """
    store = FilesystemObjectStore(tmp_path)
    uri = dataset_version_data_uri(WS, DS, DV)
    store.write(uri, b"")
    frame.write_parquet(store.local_path(uri))

    version = DatasetVersion(
        id=DV,
        dataset_id=DS,
        version_no=1,
        content_hash="a" * 64,
        parquet_uri=str(uri),
        row_count=frame.height,
        column_count=frame.width,
        byte_size=1,
        ingested_at=T0,
        ingested_by=UserId(uuid.uuid4()),
    )
    principal = Principal(
        user_id=UserId(uuid.uuid4()), session_id=SessionId(uuid.uuid4()), memberships={}
    )
    return DataHandle(
        principal=principal,
        workspace_id=WS,
        version=version,
        uri=uri,
        _store=store,
        _grant=data_access._GRANT,
    )


@pytest.fixture
def engine() -> DuckDBEngine:
    return DuckDBEngine()


@pytest.fixture
def handle(tmp_path: Path) -> DataHandle:
    frame = pl.DataFrame(
        {
            "id": range(ROWS),
            "label": [f"row-{i}" for i in range(ROWS)],
            "amount": [i * 1.5 for i in range(ROWS)],
        }
    )
    return _handle(tmp_path, frame)


def test_columns_reports_file_order_and_physical_types(
    engine: DuckDBEngine, handle: DataHandle
) -> None:
    columns = engine.columns(handle)

    assert [c.name for c in columns] == ["id", "label", "amount"]
    assert [c.ordinal for c in columns] == [0, 1, 2]
    # The exact spelling belongs to DuckDB; what matters is that a physical type
    # is reported at all and that it is not our logical vocabulary (FR-C.1).
    assert all(c.physical_type for c in columns)
    assert "VARCHAR" in columns[1].physical_type.upper()


def test_row_count_matches_the_file(engine: DuckDBEngine, handle: DataHandle) -> None:
    assert engine.row_count(handle) == ROWS


def test_page_returns_the_requested_window_in_file_order(
    engine: DuckDBEngine, handle: DataHandle
) -> None:
    page = engine.page(handle, offset=100, limit=5)

    assert page.columns == ("id", "label", "amount")
    assert [row[0] for row in page.rows] == [100, 101, 102, 103, 104]
    assert page.offset == 100
    assert page.limit == 5


def test_paging_covers_every_row_exactly_once(engine: DuckDBEngine, handle: DataHandle) -> None:
    """The property FR-D.1 actually promises, stated as a whole-table sweep.

    Asserting on one page cannot catch a reordering bug: any single page still
    looks plausible. Walking the whole table can — a row returned twice and a
    row never returned are the same defect seen from two sides.
    """
    seen: list[object] = []
    for offset in range(0, ROWS, 250):
        seen.extend(row[0] for row in engine.page(handle, offset=offset, limit=250).rows)

    assert seen == list(range(ROWS))


def test_paging_is_stable_across_repeated_reads(engine: DuckDBEngine, handle: DataHandle) -> None:
    """Same request, same rows — every time, not usually.

    This is the guard on ``preserve_insertion_order``. If a future DuckDB
    changes that default, this fails here rather than as a user complaint that
    a row "moved" while they were reading it.
    """
    windows = {
        tuple(row[0] for row in engine.page(handle, offset=1_500, limit=20).rows) for _ in range(20)
    }
    assert len(windows) == 1


def test_page_rejects_a_window_it_cannot_serve(engine: DuckDBEngine, handle: DataHandle) -> None:
    with pytest.raises(EngineError):
        engine.page(handle, offset=-1, limit=10)
    with pytest.raises(EngineError):
        engine.page(handle, offset=0, limit=0)
    with pytest.raises(EngineError, match=str(MAX_PAGE_SIZE)):
        engine.page(handle, offset=0, limit=MAX_PAGE_SIZE + 1)


def test_page_past_the_end_is_empty_rather_than_an_error(
    engine: DuckDBEngine, handle: DataHandle
) -> None:
    """Paging one step too far is normal navigation, not a failure."""
    page = engine.page(handle, offset=ROWS + 10, limit=10)
    assert page.rows == ()
    assert page.columns == ("id", "label", "amount")


@pytest.mark.invariant
@pytest.mark.parametrize(
    "impostor",
    [
        pytest.param("storage://workspaces/x/data.parquet", id="storage-uri"),
        pytest.param("data.parquet", id="relative-path"),
        pytest.param(Path("data.parquet"), id="pathlib-path"),
        pytest.param(None, id="none"),
    ],
)
def test_engine_refuses_anything_that_is_not_a_data_handle(
    engine: DuckDBEngine, impostor: object
) -> None:
    """INV-7 L3: authorization is the only way in, at runtime as well as in mypy.

    A path that happens to be readable is not permission to read it.
    """
    for call in (
        lambda: engine.columns(impostor),  # type: ignore[arg-type]
        lambda: engine.row_count(impostor),  # type: ignore[arg-type]
        lambda: engine.page(impostor, offset=0, limit=10),  # type: ignore[arg-type]
    ):
        with pytest.raises(EngineError, match="DataHandle"):
            call()


@pytest.mark.invariant
def test_insertion_order_is_preserved_on_every_cursor(engine: DuckDBEngine) -> None:
    """The setting pagination rests on, checked where queries actually run.

    Setting it on the parent connection is not enough on its own — a cursor is
    a separate connection sharing one database, so this asserts the engine
    configures the object it really uses.
    """
    cursor = engine._cursor()
    row = cursor.execute("SELECT current_setting('preserve_insertion_order')").fetchone()
    assert row is not None
    assert str(row[0]).lower() in {"true", "1"}
