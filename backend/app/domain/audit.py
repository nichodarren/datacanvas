"""Audit events (DESIGN.md §13.7).

One event stream serves two needs — compliance (FR-J.4) and user-facing
traceability (FR-H). Deliberately not two systems.

Append-only is enforced in Postgres (trigger + restricted grant), not here.
This module only describes the shape of what gets appended.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum, unique
from uuid import UUID

from ._checks import ensure_aware
from .ids import AuditEventId, UserId


@unique
class AuditAction(StrEnum):
    """Actions worth recording. Grows per phase; §13.7 lists the full target set.

    Phase 1 covers identity and tenancy. Dataset, schema, step execution,
    copilot usage and export arrive with the phases that introduce them.
    """

    USER_REGISTERED = "user.registered"
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    LOGOUT = "auth.logout"
    LOGOUT_ALL = "auth.logout_all"
    # S105 flags these as hardcoded passwords because of the member names.
    # They are audit action labels; nothing secret is involved.
    PASSWORD_RESET_REQUESTED = "auth.password_reset_requested"  # noqa: S105
    PASSWORD_RESET_COMPLETED = "auth.password_reset_completed"  # noqa: S105
    # Distinct from a reset: this one is performed by someone who *could*
    # already authenticate. An investigation needs to tell those apart — a
    # reset says "I lost access", a change says "I had access and rotated it".
    PASSWORD_CHANGED = "auth.password_changed"  # noqa: S105
    #: One session ended from the account page, as opposed to the caller's own
    #: logout. §13.7 wants revocation recorded; who revoked what is the point.
    SESSION_REVOKED = "auth.session_revoked"
    # §13.7 requires dataset creation and deletion. Note what is *not* here and
    # cannot be: the filename, the column names, or anything read from the file.
    # §13.7.1 forbids data in `metadata`, and column names count as sensitive
    # (K1, §13.5.1) — so these events carry ids, counts and a content hash.
    DATASET_CREATED = "dataset.created"
    DATASET_DELETED = "dataset.deleted"
    # §13.7 lists "perubahan skema" explicitly. The event records the contract
    # ids and the column ordinals that moved — never a column *name*, which is
    # sensitive (K1) and would be undeletable here (§13.7.1).
    SCHEMA_CONTRACT_CREATED = "schema.contract_created"
    # `workspace.created`, `project.created` and the three `membership.*`
    # actions were removed by D-039 with the entities they described. The
    # vocabulary shrinks; the rows that already used those values are untouched,
    # because §13.7's log is append-only and describes a past this enum no
    # longer has to be able to produce.
    AUTHORIZATION_DENIED = "authz.denied"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """A single appended fact.

    ``actor_user_id`` is optional, and that is not an oversight: a failed login
    often has no identifiable user — a wrong email address is exactly the case
    worth recording. Requiring it would force either a fake value or a silently
    dropped event, and a log that drops the interesting events is worse than no
    log.

    ``workspace_id`` was removed by D-039. The account is the tenant now, so
    *where this happened* and *who did it* are the same fact, and ``actor_user_id``
    already carried it.
    """

    id: AuditEventId
    action: AuditAction
    at: datetime
    actor_user_id: UserId | None = None
    target_type: str | None = None
    target_id: UUID | None = None
    ip: str | None = None
    metadata: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ensure_aware(self.at, "at")


__all__ = ["AuditAction", "AuditEvent"]
