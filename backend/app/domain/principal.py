"""The authenticated caller (DESIGN.md §13.2 design hook, §13.3).

Everything downstream of authentication speaks ``Principal`` and nothing else.
Adding OIDC/SSO later means adding another way to produce one of these — not
touching a single authorization check.

Pure by construction: a Principal is a snapshot taken at request start. It does
no lookups, so an authorization decision cannot quietly depend on a database
round-trip in the middle of a request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .enums import Role
from .errors import AuthorizationError
from .ids import SessionId, UserId, WorkspaceId


@dataclass(frozen=True, slots=True)
class Principal:
    """A user, the session they are using, and their role in each workspace."""

    user_id: UserId
    session_id: SessionId
    memberships: Mapping[WorkspaceId, Role]

    def __post_init__(self) -> None:
        # Freeze the mapping too. A frozen dataclass wrapping a mutable dict is
        # immutable in appearance only, and this particular dict decides who
        # can read whose data.
        object.__setattr__(self, "memberships", MappingProxyType(dict(self.memberships)))

    def role_in(self, workspace_id: WorkspaceId) -> Role | None:
        return self.memberships.get(workspace_id)

    def is_member_of(self, workspace_id: WorkspaceId) -> bool:
        return workspace_id in self.memberships

    def require_role(self, workspace_id: WorkspaceId, minimum: Role) -> Role:
        """Return the caller's role, or raise if it is absent or insufficient.

        Non-membership and insufficient role raise the *same* error on purpose:
        the distinction tells the caller whether the workspace exists, and that
        is itself a leak (§13.3.1 L2).
        """
        role = self.role_in(workspace_id)
        if role is None or not role.at_least(minimum):
            raise AuthorizationError(
                f"principal {self.user_id} may not act as {minimum} in workspace {workspace_id}"
            )
        return role


__all__ = ["Principal"]
