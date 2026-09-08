"""Typed identifiers.

Every entity id is a distinct type over ``UUID``. This costs nothing at runtime
and buys a real guarantee in a codebase whose central security property is
"the right principal reaches the right tenant": passing a ``DatasetId`` where
a ``UserId`` is expected stops being a runtime bug and becomes a type error.

``OrganizationId``, ``WorkspaceId``, ``MembershipId`` and ``ProjectId`` were
removed by D-039 along with the entities they named. ``UserId`` is now the
tenant key, which is the only thing this module's argument ever depended on.

DESIGN.md §13.3 rejects discipline as a security mechanism. This is the same
argument applied one layer down.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID

UserId = NewType("UserId", UUID)
SessionId = NewType("SessionId", UUID)

DatasetId = NewType("DatasetId", UUID)
SourceFileId = NewType("SourceFileId", UUID)
SchemaContractId = NewType("SchemaContractId", UUID)

PasswordResetTokenId = NewType("PasswordResetTokenId", UUID)

AuditEventId = NewType("AuditEventId", UUID)

__all__ = [
    "AuditEventId",
    "DatasetId",
    "PasswordResetTokenId",
    "SchemaContractId",
    "SessionId",
    "SourceFileId",
    "UserId",
]
