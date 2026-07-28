"""INV-2, INV-3 and §13.7, proved against a real Postgres.

The unit tests assert that the domain objects are frozen and that migration 0001
contains the right DDL. Neither proves the database refuses anything — a frozen
dataclass says nothing about what a stray ``UPDATE`` can do, and DDL that was
never executed is a plan, not a guarantee. These tests issue the statements.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection

from app.repositories.tables import (
    APP_ROLE,
    DEFAULT_ORGANIZATION_ID,
    app_user,
    audit_event,
    dataset,
    dataset_version,
    organization,
    project,
    schema_contract,
    workspace,
)

pytestmark = pytest.mark.asyncio(loop_scope="session")


async def _seed_dataset_version(db: AsyncConnection) -> uuid.UUID:
    """The shortest path from an empty schema to one dataset_version row."""
    now = sa.func.now()
    user_id, workspace_id, project_id, dataset_id, version_id = (uuid.uuid4() for _ in range(5))

    await db.execute(
        sa.insert(app_user).values(
            id=user_id, email=f"{user_id}@example.com", password_hash="x", created_at=now
        )
    )
    await db.execute(
        sa.insert(workspace).values(
            id=workspace_id,
            organization_id=DEFAULT_ORGANIZATION_ID,
            name="W",
            created_at=now,
            created_by=user_id,
        )
    )
    await db.execute(
        sa.insert(project).values(
            id=project_id, workspace_id=workspace_id, name="P", created_at=now
        )
    )
    await db.execute(
        sa.insert(dataset).values(id=dataset_id, project_id=project_id, name="D", created_at=now)
    )
    await db.execute(
        sa.insert(dataset_version).values(
            id=version_id,
            dataset_id=dataset_id,
            version_no=1,
            content_hash="a" * 64,
            parquet_uri="storage://w/d/v/data.parquet",
            row_count=891,
            column_count=12,
            byte_size=1024,
            ingested_at=now,
            ingested_by=user_id,
        )
    )
    return version_id


# -------------------------------------------------------- INV-2 / INV-3 ----


@pytest.mark.invariant
async def test_dataset_version_cannot_be_updated(db: AsyncConnection) -> None:
    """INV-2 in storage, not just in the dataclass."""
    version_id = await _seed_dataset_version(db)

    with pytest.raises(DBAPIError) as raised:
        async with db.begin_nested():
            await db.execute(
                sa.update(dataset_version)
                .where(dataset_version.c.id == version_id)
                .values(row_count=0)
            )
    assert "immutable" in str(raised.value)


@pytest.mark.invariant
async def test_dataset_version_can_still_be_deleted(db: AsyncConnection) -> None:
    """FR-B.6 requires real deletion, so the trigger must block UPDATE only.

    An invariant enforced more broadly than it was written is a different
    invariant, and this one would quietly break the delete requirement.
    """
    version_id = await _seed_dataset_version(db)

    await db.execute(sa.delete(dataset_version).where(dataset_version.c.id == version_id))
    remaining = await db.scalar(
        sa.select(sa.func.count())
        .select_from(dataset_version)
        .where(dataset_version.c.id == version_id)
    )
    assert remaining == 0


@pytest.mark.invariant
async def test_schema_contract_cannot_be_updated(db: AsyncConnection) -> None:
    """INV-3: a correction is a new version, never an edit."""
    version_id = await _seed_dataset_version(db)
    contract_id = uuid.uuid4()
    await db.execute(
        sa.insert(schema_contract).values(
            id=contract_id,
            dataset_version_id=version_id,
            version_no=1,
            columns=[{"name": "id", "ordinal": 0, "logical_type": "integer"}],
            created_at=sa.func.now(),
        )
    )

    with pytest.raises(DBAPIError) as raised:
        async with db.begin_nested():
            await db.execute(
                sa.update(schema_contract)
                .where(schema_contract.c.id == contract_id)
                .values(version_no=2)
            )
    assert "immutable" in str(raised.value)


@pytest.mark.invariant
async def test_schema_contract_version_one_must_not_derive_from_anything(
    db: AsyncConnection,
) -> None:
    """The domain rule again, one layer down, where no code path can route around it."""
    version_id = await _seed_dataset_version(db)
    parent = uuid.uuid4()
    await db.execute(
        sa.insert(schema_contract).values(
            id=parent,
            dataset_version_id=version_id,
            version_no=1,
            columns=[],
            created_at=sa.func.now(),
        )
    )

    with pytest.raises(DBAPIError):
        async with db.begin_nested():
            await db.execute(
                sa.insert(schema_contract).values(
                    id=uuid.uuid4(),
                    dataset_version_id=version_id,
                    version_no=1,
                    columns=[],
                    created_at=sa.func.now(),
                    derived_from=parent,
                )
            )


# ------------------------------------------------------------ audit log ----


@pytest.mark.invariant
async def test_audit_event_cannot_be_updated(db: AsyncConnection) -> None:
    event_id = uuid.uuid4()
    await db.execute(
        sa.insert(audit_event).values(id=event_id, action="auth.login_succeeded", at=sa.func.now())
    )

    with pytest.raises(DBAPIError) as raised:
        async with db.begin_nested():
            await db.execute(
                sa.update(audit_event).where(audit_event.c.id == event_id).values(action="tampered")
            )
    assert "append-only" in str(raised.value)


@pytest.mark.invariant
async def test_audit_event_cannot_be_deleted(db: AsyncConnection) -> None:
    """An audit log that the application can prune is not an audit log."""
    event_id = uuid.uuid4()
    await db.execute(
        sa.insert(audit_event).values(id=event_id, action="auth.logout", at=sa.func.now())
    )

    with pytest.raises(DBAPIError) as raised:
        async with db.begin_nested():
            await db.execute(sa.delete(audit_event).where(audit_event.c.id == event_id))
    assert "append-only" in str(raised.value)


async def test_audit_event_accepts_events_without_workspace_or_actor(db: AsyncConnection) -> None:
    """A failed login has neither, and it is the event most worth keeping."""
    await db.execute(
        sa.insert(audit_event).values(
            id=uuid.uuid4(),
            action="auth.login_failed",
            at=sa.func.now(),
            metadata={"email": "unknown@example.com"},
        )
    )


# ---------------------------------------------------------------- grants ----


@pytest.mark.invariant
async def test_application_role_has_no_update_or_delete_on_audit_event(
    db: AsyncConnection,
) -> None:
    """Second line of defence for §13.7, in case a later migration drops the trigger."""
    granted = set(
        (
            await db.execute(
                sa.text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = :role AND table_name = 'audit_event'"
                ),
                {"role": APP_ROLE},
            )
        )
        .scalars()
        .all()
    )
    assert granted == {"SELECT", "INSERT"}


@pytest.mark.invariant
@pytest.mark.parametrize("table", ["dataset_version", "schema_contract"])
async def test_application_role_has_no_update_on_immutable_tables(
    db: AsyncConnection, table: str
) -> None:
    granted = set(
        (
            await db.execute(
                sa.text(
                    "SELECT privilege_type FROM information_schema.role_table_grants"
                    " WHERE grantee = :role AND table_name = :table"
                ),
                {"role": APP_ROLE, "table": table},
            )
        )
        .scalars()
        .all()
    )
    assert "UPDATE" not in granted
    assert {"SELECT", "INSERT", "DELETE"} <= granted


# ----------------------------------------------------------------- seed ----


async def test_default_organization_exists(db: AsyncConnection) -> None:
    """Registration attaches every workspace to it without a lookup."""
    name = await db.scalar(
        sa.select(organization.c.name).where(organization.c.id == DEFAULT_ORGANIZATION_ID)
    )
    assert name == "Default"
