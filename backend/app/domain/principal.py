"""The authenticated caller (DESIGN.md §13.2 design hook, §13.3).

Everything downstream of authentication speaks ``Principal`` and nothing else.
Adding OIDC/SSO later means adding another way to produce one of these — not
touching a single authorization check.

Pure by construction: a Principal is a snapshot taken at request start. It does
no lookups, so an authorization decision cannot quietly depend on a database
round-trip in the middle of a request.

## What D-039 took out of here, and why the guarantee survives

This used to carry ``memberships: Mapping[WorkspaceId, Role]`` and three methods
over it — ``role_in``, ``is_member_of``, ``require_role``. Removing FR-A.5
removed the question they answered: with one owner per account there is no role
to hold and no membership to look up.

What replaces them is not a weaker check, it is a shorter one. Authorization is
now ``resource.owner_id == principal.user_id`` — a single equality, resolved in
the same query that finds the resource. The property §13.3 actually asks for is
that the check *cannot be skipped*, and that is enforced where it always was:
``data_access.open_dataset()`` is still the only thing that can produce
a ``DataHandle``, and a ``DataHandle`` is still the only thing that can read
bytes.

The one guarantee genuinely gone is the ability to grant someone else access at
all. That is the scope change, not a regression in enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import AuthorizationError
from .ids import SessionId, UserId


@dataclass(frozen=True, slots=True)
class Principal:
    """A user and the session they are using. Nothing else decides access."""

    user_id: UserId
    session_id: SessionId

    def owns(self, owner_id: UserId) -> bool:
        """Whether the caller is the owner recorded on a resource."""
        return owner_id == self.user_id

    def require_owner(self, owner_id: UserId) -> None:
        """Raise unless the caller owns the resource.

        The error says nothing about whether the resource exists. Callers render
        it as 404 rather than 403 for the same reason they always did: a 403
        confirms the resource is real, and that confirmation is itself the leak
        (§13.3.1 L2).
        """
        if not self.owns(owner_id):
            raise AuthorizationError(f"principal {self.user_id} does not own this resource")


__all__ = ["Principal"]
