"""Storing Computations, and finding the one that already exists.

The cache is a ``SELECT ... WHERE fingerprint = ?`` and nothing more. That is
the point of §9.4: identity is computed from the inputs, so "have we answered
this before" is a primary-key lookup rather than a policy.

``tool_version`` is written the first time a (name, version) pair runs. It is
not a registry of what the code *can* do — ``app.tools.REGISTRY`` is that — it
is a record of what has actually produced a stored result, so a Computation can
still be explained after its tool has been rewritten twice.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.execution import Computation
from app.domain.ids import DatasetId, SchemaContractId, UserId
from app.repositories.tables import computation, tool_version


def _to_computation(row: Row[tuple[object, ...]]) -> Computation:
    return Computation(
        id=row.id,
        fingerprint=row.fingerprint,
        tool_name=row.tool_name,
        tool_version=row.tool_version,
        args=dict(row.args),
        dataset_id=DatasetId(row.dataset_id),
        schema_contract_id=SchemaContractId(row.schema_contract_id),
        parents=tuple(row.parents),
        result=dict(row.result),
        computed_at=row.computed_at,
        computed_by=UserId(row.computed_by),
        duration_ms=row.duration_ms,
    )


class ComputationRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def find(self, fingerprint: str) -> Computation | None:
        """The cache lookup, and the whole of it.

        Note what is *absent*: no expiry, no size limit, no eviction policy. A
        Computation is not stale in the way a cache entry usually is — it is the
        answer for a fingerprint, and the fingerprint changes whenever anything
        that could change the answer changes (§9.4). Adding a TTL would mean
        recomputing an identical result on a timer.
        """
        row = (
            await self._c.execute(
                sa.select(computation).where(computation.c.fingerprint == fingerprint)
            )
        ).one_or_none()
        return None if row is None else _to_computation(row)

    async def within(self, identifier: uuid.UUID, dataset_id: DatasetId) -> Computation | None:
        """One Computation by id, **and only inside the dataset that asked**.

        The dataset is part of the query rather than checked afterwards, so a
        `table` argument naming somebody else's Computation comes back as
        *not found* rather than as *forbidden* — the same shape §13.3.1 uses
        everywhere else, and for the same reason: a 403 confirms the id exists.
        """
        row = (
            await self._c.execute(
                sa.select(computation).where(
                    computation.c.id == identifier,
                    computation.c.dataset_id == dataset_id,
                )
            )
        ).one_or_none()
        return None if row is None else _to_computation(row)

    async def create(self, record: Computation) -> Computation:
        """Append one. Never updates — the table's trigger refuses it (INV-6).

        ``ON CONFLICT DO NOTHING`` on the fingerprint, because two requests can
        race: both miss the cache, both compute, both insert. The results are
        *identical* by construction — that is what a fingerprint means — so
        losing one of them costs nothing and raising would turn a harmless race
        into a 500 for whoever arrived second.
        """
        await self._c.execute(
            # , not : ON CONFLICT is a Postgres clause and
            # the generic construct does not carry it.
            pg_insert(computation)
            .values(
                id=record.id,
                fingerprint=record.fingerprint,
                tool_name=record.tool_name,
                tool_version=record.tool_version,
                args=record.args,
                dataset_id=record.dataset_id,
                schema_contract_id=record.schema_contract_id,
                parents=list(record.parents),
                result=record.result,
                computed_at=record.computed_at,
                computed_by=record.computed_by,
                duration_ms=record.duration_ms,
            )
            .on_conflict_do_nothing(index_elements=[computation.c.fingerprint])
        )
        return record


class ToolVersionRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def ensure(self, *, name: str, version: int, summary: str, now: datetime) -> None:
        """Record that this (name, version) has run, once.

        Idempotent by conflict rather than by a read-then-write: two concurrent
        first runs of the same tool would both see nothing and both insert, and
        the unique constraint is a better arbiter than a check somebody has to
        remember to hold a lock around.
        """
        await self._c.execute(
            pg_insert(tool_version)
            .values(
                id=uuid.uuid4(),
                tool_name=name,
                version=version,
                summary=summary,
                registered_at=now,
            )
            .on_conflict_do_nothing(
                index_elements=[tool_version.c.tool_name, tool_version.c.version]
            )
        )

    async def known(self) -> tuple[tuple[str, int], ...]:
        rows = await self._c.execute(
            sa.select(tool_version.c.tool_name, tool_version.c.version).order_by(
                tool_version.c.tool_name, tool_version.c.version
            )
        )
        return tuple((name, version) for name, version in rows)


__all__ = ["ComputationRepository", "ToolVersionRepository"]
