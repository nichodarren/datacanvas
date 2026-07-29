"""Audit repository (DESIGN.md §13.7).

Insert only. There are no update or delete methods here, and that is not what
enforces append-only — the database does (§13.7). The absence of the methods
just means nobody writes code that Postgres will reject at runtime.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.audit import AuditAction, AuditEvent
from app.domain.errors import InvariantViolation
from app.domain.ids import AuditEventId, UserId, WorkspaceId
from app.repositories.tables import audit_event

#: Keys allowed in `metadata` (§13.7.1). An allowlist rather than a blocklist:
#: the point is that a new caller has to think about it, and the failure mode of
#: a blocklist is that the one thing nobody listed is the one that leaks.
ALLOWED_METADATA_KEYS = frozenset(
    {
        "tool_name",
        "tool_version",
        "computation_id",
        "schema_contract_id",
        "column_ordinal",
        "row_count",
        "byte_size",
        "duration_ms",
        "failure_code",
        "reason",
        "prompt_sha256",
        "session_id",
        "role",
        "previous_role",
        "target_user_id",
        "revoked_count",
        "user_agent",
        # --- Phase 2, ingest ------------------------------------------------
        # Added when the first ingest event was refused by the check above,
        # which is the allowlist doing its job. Each one is an id, a count, a
        # hash, or a value from a closed vocabulary — never a filename, never a
        # column name (K1, §13.5.1), never anything read out of the file.
        "dataset_id",
        "version_no",
        "column_count",
        "content_hash",
        "format",
    }
)


class AuditRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def record(
        self,
        *,
        action: AuditAction,
        now: datetime,
        workspace_id: WorkspaceId | None = None,
        actor_user_id: UserId | None = None,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        ip: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> AuditEvent:
        """Append one event.

        ``metadata`` is checked against :data:`ALLOWED_METADATA_KEYS` before it
        goes anywhere. §13.7.1 forbids data values and free user text in this
        column, because the row can never be deleted — and a rule that is only
        written in a document will be broken by the third caller.
        """
        payload = dict(metadata or {})
        rejected = sorted(set(payload) - ALLOWED_METADATA_KEYS)
        if rejected:
            raise InvariantViolation(
                f"audit metadata keys not allowed: {rejected}. §13.7.1 — the audit log is "
                f"append-only and can never be deleted, so it must never hold data values "
                f"or free user text. Store a hash, or an id that resolves elsewhere."
            )

        event = AuditEvent(
            id=AuditEventId(uuid.uuid4()),
            action=action,
            at=now,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            target_type=target_type,
            target_id=target_id,
            ip=ip,
            metadata=payload,
        )
        await self._c.execute(
            sa.insert(audit_event).values(
                id=event.id,
                action=event.action.value,
                at=event.at,
                workspace_id=event.workspace_id,
                actor_user_id=event.actor_user_id,
                target_type=event.target_type,
                target_id=event.target_id,
                ip=event.ip,
                metadata=payload,
            )
        )
        return event

    async def count(self) -> int:
        value = await self._c.scalar(sa.select(sa.func.count()).select_from(audit_event))
        return int(value or 0)


__all__ = ["ALLOWED_METADATA_KEYS", "AuditRepository"]
