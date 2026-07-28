"""``data_access.open_dataset_version`` against a real database (§13.3, INV-7).

The route sweep proves the HTTP surface is closed. This proves the gate itself
is closed — including for callers that never go through HTTP, which is what the
tool executor will be in Phase 3.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.authz.data_access import DataAccessDenied, open_dataset_version
from app.domain.audit import AuditAction
from app.domain.enums import Role
from app.domain.errors import InvariantViolation
from app.domain.ids import (
    DatasetId,
    DatasetVersionId,
    SessionId,
    UserId,
    WorkspaceId,
)
from app.domain.principal import Principal
from app.repositories.audit import AuditRepository
from app.repositories.tables import (
    DEFAULT_ORGANIZATION_ID,
    app_user,
    dataset,
    dataset_version,
    project,
    workspace,
)
from app.storage.object_store import FilesystemObjectStore
from app.storage.uri import dataset_version_data_uri

pytestmark = pytest.mark.asyncio(loop_scope="session")

T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


async def _seed(
    db: AsyncConnection, store: FilesystemObjectStore
) -> tuple[WorkspaceId, DatasetVersionId]:
    user_id = UserId(uuid.uuid4())
    workspace_id = WorkspaceId(uuid.uuid4())
    project_id = uuid.uuid4()
    dataset_id = DatasetId(uuid.uuid4())
    version_id = DatasetVersionId(uuid.uuid4())
    uri = dataset_version_data_uri(workspace_id, dataset_id, version_id)

    await db.execute(
        sa.insert(app_user).values(
            id=user_id, email=f"{user_id}@example.com", password_hash="x", created_at=T0
        )
    )
    await db.execute(
        sa.insert(workspace).values(
            id=workspace_id,
            organization_id=DEFAULT_ORGANIZATION_ID,
            name="W",
            created_at=T0,
            created_by=user_id,
        )
    )
    await db.execute(
        sa.insert(project).values(id=project_id, workspace_id=workspace_id, name="P", created_at=T0)
    )
    await db.execute(
        sa.insert(dataset).values(id=dataset_id, project_id=project_id, name="D", created_at=T0)
    )
    await db.execute(
        sa.insert(dataset_version).values(
            id=version_id,
            dataset_id=dataset_id,
            version_no=1,
            content_hash="c" * 64,
            parquet_uri=str(uri),
            row_count=3,
            column_count=2,
            byte_size=9,
            ingested_at=T0,
            ingested_by=user_id,
        )
    )
    store.write(uri, b"parquet!!")
    return workspace_id, version_id


def _principal(**memberships: Role) -> Principal:
    return Principal(
        user_id=UserId(uuid.uuid4()),
        session_id=SessionId(uuid.uuid4()),
        memberships={WorkspaceId(uuid.UUID(k)): v for k, v in memberships.items()},
    )


@pytest.mark.invariant
async def test_a_member_gets_a_working_handle(db: AsyncConnection, tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    workspace_id, version_id = await _seed(db, store)

    handle = await open_dataset_version(
        _principal(**{str(workspace_id): Role.VIEWER}),
        version_id,
        connection=db,
        store=store,
    )

    assert handle.workspace_id == workspace_id
    assert handle.read() == b"parquet!!"
    assert handle.local_path().is_file()


@pytest.mark.invariant
async def test_a_non_member_is_denied(db: AsyncConnection, tmp_path: Path) -> None:
    store = FilesystemObjectStore(tmp_path)
    _, version_id = await _seed(db, store)

    with pytest.raises(DataAccessDenied):
        await open_dataset_version(_principal(), version_id, connection=db, store=store)


@pytest.mark.invariant
async def test_a_missing_version_is_denied_the_same_way(
    db: AsyncConnection, tmp_path: Path
) -> None:
    """Same exception as "not yours".

    Distinguishing them would let a caller enumerate which ids exist, one
    request at a time.
    """
    store = FilesystemObjectStore(tmp_path)
    with pytest.raises(DataAccessDenied):
        await open_dataset_version(
            _principal(), DatasetVersionId(uuid.uuid4()), connection=db, store=store
        )


@pytest.mark.invariant
async def test_a_viewer_cannot_open_with_editor_rights(db: AsyncConnection, tmp_path: Path) -> None:
    """The gate carries the role requirement, so writers cannot be let in by accident."""
    store = FilesystemObjectStore(tmp_path)
    workspace_id, version_id = await _seed(db, store)
    viewer = _principal(**{str(workspace_id): Role.VIEWER})

    with pytest.raises(DataAccessDenied):
        await open_dataset_version(
            viewer, version_id, connection=db, store=store, required_role=Role.EDITOR
        )


# ------------------------------------------------------- audit metadata ----


@pytest.mark.invariant
async def test_audit_metadata_rejects_unlisted_keys(db: AsyncConnection) -> None:
    """§13.7.1: the log can never be deleted, so it must never hold data values.

    An allowlist rather than a blocklist — with a blocklist, the one key nobody
    thought of is the one that leaks.
    """
    with pytest.raises(InvariantViolation) as raised:
        await AuditRepository(db).record(
            action=AuditAction.LOGIN_FAILED,
            now=T0,
            metadata={"prompt": "why is Budi Santoso's amount 1.250.000?"},
        )
    assert "13.7.1" in str(raised.value)


@pytest.mark.invariant
async def test_audit_metadata_accepts_a_prompt_hash(db: AsyncConnection) -> None:
    """The shape §13.7.1 prescribes: the hash, not the sentence."""
    await AuditRepository(db).record(
        action=AuditAction.LOGIN_FAILED,
        now=T0,
        metadata={"prompt_sha256": "a" * 64, "tool_name": "profile_column"},
    )
