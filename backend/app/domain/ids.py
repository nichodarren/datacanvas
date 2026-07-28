"""Typed identifiers.

Every entity id is a distinct type over ``UUID``. This costs nothing at runtime
and buys a real guarantee in a codebase whose central security property is
"the right principal reaches the right tenant": passing a ``WorkspaceId`` where
a ``UserId`` is expected stops being a runtime bug and becomes a type error.

DESIGN.md §13.3 rejects discipline as a security mechanism. This is the same
argument applied one layer down.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID

OrganizationId = NewType("OrganizationId", UUID)
UserId = NewType("UserId", UUID)
SessionId = NewType("SessionId", UUID)
WorkspaceId = NewType("WorkspaceId", UUID)
MembershipId = NewType("MembershipId", UUID)
ProjectId = NewType("ProjectId", UUID)

DatasetId = NewType("DatasetId", UUID)
DatasetVersionId = NewType("DatasetVersionId", UUID)
SourceFileId = NewType("SourceFileId", UUID)
SchemaContractId = NewType("SchemaContractId", UUID)

PasswordResetTokenId = NewType("PasswordResetTokenId", UUID)

AuditEventId = NewType("AuditEventId", UUID)

__all__ = [
    "AuditEventId",
    "DatasetId",
    "DatasetVersionId",
    "MembershipId",
    "OrganizationId",
    "PasswordResetTokenId",
    "ProjectId",
    "SchemaContractId",
    "SessionId",
    "SourceFileId",
    "UserId",
    "WorkspaceId",
]
