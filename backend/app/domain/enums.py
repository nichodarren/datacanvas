"""Closed vocabularies of the domain.

``StrEnum`` so that the stored representation is the readable value: a database
dump, a log line, and an audit export all say ``"editor"`` rather than ``2``.
Numeric enum values are the kind of thing that gets renumbered once and then
silently reinterprets years of history.
"""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


@unique
class Role(StrEnum):
    """Workspace roles (FR-A.5, §13.3).

    Ordered by capability: every ``owner`` can do what an ``editor`` can, and
    every ``editor`` what a ``viewer`` can. ``at_least`` is the only place that
    ordering is written down, so authorization checks cannot disagree about it.
    """

    OWNER = "owner"
    EDITOR = "editor"
    VIEWER = "viewer"

    @property
    def rank(self) -> int:
        return _ROLE_RANK[self]

    def at_least(self, required: Role) -> bool:
        """True when this role carries at least the authority of ``required``."""
        return self.rank >= required.rank

    @property
    def can_write(self) -> bool:
        """Create/modify/delete data and analyses. ``viewer`` is read-only."""
        return self.at_least(Role.EDITOR)


_ROLE_RANK: dict[Role, int] = {Role.VIEWER: 0, Role.EDITOR: 1, Role.OWNER: 2}


@unique
class PrivacyMode(StrEnum):
    """LLM egress policy per workspace (§13.5.2). Default is ``balanced`` (OQ-4)."""

    STRICT = "strict"
    BALANCED = "balanced"
    FULL = "full"
    LOCAL = "local"


@unique
class LogicalType(StrEnum):
    """Logical column types supported by the MVP (FR-C).

    ``categorical`` is separate from ``text`` on purpose: the logical type
    decides which tools are offered and how a profile renders (§FR-C rationale).
    """

    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    CATEGORICAL = "categorical"
    TEXT = "text"
    DATE = "date"
    DATETIME = "datetime"
    DURATION = "duration"
    UNSUPPORTED = "unsupported"


@unique
class ColumnRole(StrEnum):
    """Semantic role of a column (FR-C.5)."""

    IDENTIFIER = "identifier"
    MEASURE = "measure"
    DIMENSION = "dimension"
    TIMESTAMP = "timestamp"
    IGNORED = "ignored"


@unique
class RouteClass(StrEnum):
    """Tenancy classification every HTTP route must declare (§13.3.1 L1).

    Lives in the domain because it is a security concept, not a web framework
    concept. There is deliberately no default value: a route whose author did
    not think about tenancy must fail the manifest test, not inherit a guess.
    """

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    TENANT_SCOPED = "tenant_scoped"


__all__ = [
    "ColumnRole",
    "LogicalType",
    "PrivacyMode",
    "Role",
    "RouteClass",
    "UserStatus",
]
