"""Pure domain layer.

Rule (DESIGN.md §10.6): this package imports nothing from ``api/``,
``repositories/`` or ``ai/``, and performs no I/O. Enforced by
``tests/unit/test_domain_boundaries.py``, not by agreement — business rules
tangled with I/O are the fastest way to make a system untestable.
"""

from __future__ import annotations

from .audit import AuditAction, AuditEvent
from .data import ColumnSpec, Dataset, DatasetVersion, SchemaContract, SourceFile
from .enums import ColumnRole, LogicalType, PrivacyMode, Role, RouteClass, UserStatus
from .errors import AuthorizationError, DomainError, InvariantViolation
from .identity import (
    SESSION_ABSOLUTE_TTL,
    SESSION_IDLE_TTL,
    Membership,
    Organization,
    Project,
    Session,
    User,
    Workspace,
    WorkspacePolicy,
    normalize_email,
)
from .principal import Principal

__all__ = [
    "SESSION_ABSOLUTE_TTL",
    "SESSION_IDLE_TTL",
    "AuditAction",
    "AuditEvent",
    "AuthorizationError",
    "ColumnRole",
    "ColumnSpec",
    "Dataset",
    "DatasetVersion",
    "DomainError",
    "InvariantViolation",
    "LogicalType",
    "Membership",
    "Organization",
    "Principal",
    "PrivacyMode",
    "Project",
    "Role",
    "RouteClass",
    "SchemaContract",
    "Session",
    "SourceFile",
    "User",
    "UserStatus",
    "Workspace",
    "WorkspacePolicy",
    "normalize_email",
]
