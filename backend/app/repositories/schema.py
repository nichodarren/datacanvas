"""SchemaContract persistence (§9.2, INV-3).

Versioned and never updated. A correction produces a new row pointing at its
predecessor, which is what makes "what did this analysis actually run against?"
answerable months later.

There is deliberately **no update method**. That is not the guarantee — the
guarantee is the Postgres trigger from migration 0001, which refuses an UPDATE
whoever issues it. This module simply has no reason to offer one, and a
repository that cannot express the illegal operation is one fewer place for the
illegal operation to be attempted.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import ColumnSpec, SchemaContract
from app.domain.enums import ColumnRole, LogicalType
from app.domain.ids import DatasetVersionId, SchemaContractId, UserId
from app.repositories.tables import schema_contract


def _to_json(spec: ColumnSpec) -> dict[str, Any]:
    """One column as stored. Written out by hand, like every other mapping here.

    Explicit both ways (D-021): a field added to ``ColumnSpec`` and forgotten
    here fails a round-trip test rather than silently vanishing on the way to
    the database.
    """
    return {
        "name": spec.name,
        "ordinal": spec.ordinal,
        "physical_type": spec.physical_type,
        "logical_type": spec.logical_type.value,
        "role": None if spec.role is None else spec.role.value,
        "format_hint": spec.format_hint,
        "null_markers": list(spec.null_markers),
        "detection_confidence": spec.detection_confidence,
        "detection_reason": spec.detection_reason,
        "overridden_by": None if spec.overridden_by is None else str(spec.overridden_by),
    }


def _from_json(payload: Mapping[str, Any]) -> ColumnSpec:
    overridden = payload.get("overridden_by")
    role = payload.get("role")
    return ColumnSpec(
        name=payload["name"],
        ordinal=payload["ordinal"],
        physical_type=payload["physical_type"],
        logical_type=LogicalType(payload["logical_type"]),
        role=None if role is None else ColumnRole(role),
        format_hint=payload.get("format_hint"),
        null_markers=tuple(payload.get("null_markers") or ()),
        detection_confidence=payload.get("detection_confidence", 1.0),
        detection_reason=payload.get("detection_reason", ""),
        overridden_by=None if overridden is None else UserId(uuid.UUID(overridden)),
    )


class SchemaContractRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, contract: SchemaContract) -> SchemaContract:
        """Takes a fully built contract, for the same reason versions do.

        INV-3 says a contract never changes after it exists, so there is no
        half-built one to complete later. The signature says so.
        """
        await self._c.execute(
            sa.insert(schema_contract).values(
                id=contract.id,
                dataset_version_id=contract.dataset_version_id,
                version_no=contract.version_no,
                columns=[_to_json(column) for column in contract.columns],
                created_at=contract.created_at,
                created_by=contract.created_by,
                derived_from=contract.derived_from,
            )
        )
        return contract

    async def latest_for_version(self, version_id: DatasetVersionId) -> SchemaContract | None:
        """The newest interpretation of a DatasetVersion.

        "Newest" is a convenience for the UI, never for an Analysis: §9.2 binds
        an Analysis to a *specific* contract so that correcting a schema does
        not silently change what a finished analysis means.
        """
        row = (
            await self._c.execute(
                sa.select(schema_contract)
                .where(schema_contract.c.dataset_version_id == version_id)
                .order_by(schema_contract.c.version_no.desc())
                .limit(1)
            )
        ).one_or_none()
        return None if row is None else self._to_domain(row)

    async def get(self, contract_id: SchemaContractId) -> SchemaContract | None:
        row = (
            await self._c.execute(
                sa.select(schema_contract).where(schema_contract.c.id == contract_id)
            )
        ).one_or_none()
        return None if row is None else self._to_domain(row)

    async def list_for_version(self, version_id: DatasetVersionId) -> list[SchemaContract]:
        rows = await self._c.execute(
            sa.select(schema_contract)
            .where(schema_contract.c.dataset_version_id == version_id)
            .order_by(schema_contract.c.version_no)
        )
        return [self._to_domain(row) for row in rows]

    async def next_version_no(self, version_id: DatasetVersionId) -> int:
        current = (
            await self._c.execute(
                sa.select(sa.func.max(schema_contract.c.version_no)).where(
                    schema_contract.c.dataset_version_id == version_id
                )
            )
        ).scalar()
        return int(current or 0) + 1

    @staticmethod
    def _to_domain(row: sa.Row[tuple[Any, ...]]) -> SchemaContract:
        return SchemaContract(
            id=SchemaContractId(row.id),
            dataset_version_id=DatasetVersionId(row.dataset_version_id),
            version_no=row.version_no,
            columns=tuple(_from_json(column) for column in row.columns),
            created_at=row.created_at,
            created_by=None if row.created_by is None else UserId(row.created_by),
            derived_from=(None if row.derived_from is None else SchemaContractId(row.derived_from)),
        )


def first_contract(
    *,
    dataset_version_id: DatasetVersionId,
    columns: Sequence[ColumnSpec],
    now: datetime,
) -> SchemaContract:
    """Version 1: pure auto-detection, derived from nothing (§9.2).

    ``created_by`` is deliberately ``None``. Nobody authored this — the detector
    did, and recording the uploader as its author would make a later "who chose
    this type?" answer the wrong name.
    """
    return SchemaContract(
        id=SchemaContractId(uuid.uuid4()),
        dataset_version_id=dataset_version_id,
        version_no=1,
        columns=tuple(columns),
        created_at=now,
        created_by=None,
        derived_from=None,
    )


__all__ = ["SchemaContractRepository", "first_contract"]
