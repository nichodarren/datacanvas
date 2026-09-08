"""Pure domain layer.

Rule (DESIGN.md §10.6): this package imports nothing from ``api/``,
``repositories/`` or ``ai/``, and performs no I/O. Enforced by
``tests/unit/test_domain_boundaries.py``, not by agreement — business rules
tangled with I/O are the fastest way to make a system untestable.
"""

from __future__ import annotations

from .audit import AuditAction, AuditEvent
from .data import ColumnSpec, Dataset, SchemaContract, SourceFile
from .enums import LogicalType, PrivacyMode, RouteClass, UserStatus
from .errors import AuthorizationError, DomainError, InvariantViolation
from .identity import (
    PASSWORD_RESET_TTL,
    SESSION_ABSOLUTE_TTL,
    SESSION_IDLE_TTL,
    PasswordResetToken,
    Session,
    User,
    UserPolicy,
    normalize_email,
)
from .principal import Principal

__all__ = [
    "PASSWORD_RESET_TTL",
    "SESSION_ABSOLUTE_TTL",
    "SESSION_IDLE_TTL",
    "AuditAction",
    "AuditEvent",
    "AuthorizationError",
    "ColumnSpec",
    "Dataset",
    "DomainError",
    "InvariantViolation",
    "LogicalType",
    "PasswordResetToken",
    "Principal",
    "PrivacyMode",
    "RouteClass",
    "SchemaContract",
    "Session",
    "SourceFile",
    "User",
    "UserPolicy",
    "UserStatus",
    "normalize_email",
]
