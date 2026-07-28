"""Workspace membership management (FR-A.5).

Lives in ``authz/`` because deciding who holds which role *is* authorization —
the same decision ``Principal`` later reads. Putting it beside the feature that
happens to call it would give the rule a second home.

Two rules carry most of the weight:

- **Only an owner may change membership.** Everyone else gets the same 404 a
  stranger gets (§13.3.1 L2).
- **The last owner cannot be demoted or removed.** A workspace with no owner is
  a workspace nobody can administer, and no endpoint exists to repair it — so
  the operation that would create that state is refused rather than regretted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncConnection

from app.clock import Clock, system_clock
from app.domain.audit import AuditAction
from app.domain.enums import Role
from app.domain.errors import AuthorizationError, DomainError
from app.domain.identity import Membership, normalize_email
from app.domain.ids import UserId, WorkspaceId
from app.domain.principal import Principal
from app.repositories.audit import AuditRepository
from app.repositories.identity import MembershipRepository, UserRepository


class MembershipDenied(AuthorizationError):
    """Not an owner, or the workspace/member does not exist. Rendered as 404."""


class NoSuchAccount(DomainError):
    """The address has no account here.

    Distinct from :class:`MembershipDenied` on purpose, and it is worth being
    honest about the trade-off: telling a workspace owner that an address is
    not registered does reveal registration status. The alternatives are worse
    — a silent no-op leaves the owner staring at a member list that did not
    change, with no idea whether they mistyped. The exposure is limited to an
    authenticated owner acting inside their own workspace, and that is the
    price of a usable invite flow without email delivery.
    """


class LastOwnerProtected(DomainError):
    """The change would leave the workspace with no owner."""


class AlreadyAMember(DomainError):
    pass


@dataclass(frozen=True, slots=True)
class MemberView:
    membership: Membership
    email: str


class MembershipService:
    def __init__(
        self,
        connection: AsyncConnection,
        *,
        clock: Clock = system_clock,
    ) -> None:
        self._c = connection
        self._now = clock
        self.memberships = MembershipRepository(connection)
        self.users = UserRepository(connection)
        self.audit = AuditRepository(connection)

    async def list_members(
        self, principal: Principal, workspace_id: WorkspaceId
    ) -> list[MemberView]:
        """Any member may see who else is in the workspace.

        Reading the list is not a privileged act: you already know you share a
        workspace with these people, and hiding it makes the product feel
        arbitrary rather than secure.
        """
        self._require_member(principal, workspace_id)
        rows = await self.memberships.list_for_workspace(workspace_id)
        return [MemberView(membership=m, email=email) for m, email in rows]

    async def add_member(
        self,
        principal: Principal,
        workspace_id: WorkspaceId,
        *,
        email: str,
        role: Role,
        ip: str | None = None,
    ) -> MemberView:
        """Grant an existing account access to this workspace.

        Only existing accounts, because inviting a stranger would mean sending
        mail, and no provider is wired (see ``app.auth.email``). The gap is
        narrow and stated rather than hidden: the person signs up first, then
        gets added.
        """
        self._require_owner(principal, workspace_id)
        now = self._now()

        target = await self.users.get_by_email(normalize_email(email))
        if target is None:
            raise NoSuchAccount(email)

        if await self.memberships.get(target.id, workspace_id) is not None:
            raise AlreadyAMember(email)

        membership = await self.memberships.grant(
            user_id=target.id,
            workspace_id=workspace_id,
            role=role,
            now=now,
            invited_by=principal.user_id,
        )
        await self._record(
            AuditAction.MEMBERSHIP_GRANTED,
            now,
            principal,
            workspace_id,
            target.id,
            ip,
            {"role": role.value},
        )
        return MemberView(membership=membership, email=target.email)

    async def change_role(
        self,
        principal: Principal,
        workspace_id: WorkspaceId,
        *,
        user_id: UserId,
        role: Role,
        ip: str | None = None,
    ) -> MemberView:
        self._require_owner(principal, workspace_id)
        now = self._now()

        existing = await self.memberships.get(user_id, workspace_id)
        if existing is None:
            raise MembershipDenied(str(user_id))
        if existing.role is role:
            return await self._view(existing)

        await self._guard_last_owner(workspace_id, existing, leaving=role is not Role.OWNER)

        await self.memberships.set_role(user_id, workspace_id, role)
        await self._record(
            AuditAction.MEMBERSHIP_ROLE_CHANGED,
            now,
            principal,
            workspace_id,
            user_id,
            ip,
            {"role": role.value, "previous_role": existing.role.value},
        )
        updated = await self.memberships.get(user_id, workspace_id)
        assert updated is not None  # just written, inside the same transaction
        return await self._view(updated)

    async def remove_member(
        self,
        principal: Principal,
        workspace_id: WorkspaceId,
        *,
        user_id: UserId,
        ip: str | None = None,
    ) -> None:
        self._require_owner(principal, workspace_id)
        now = self._now()

        existing = await self.memberships.get(user_id, workspace_id)
        if existing is None:
            raise MembershipDenied(str(user_id))

        await self._guard_last_owner(workspace_id, existing, leaving=True)

        await self.memberships.revoke(user_id, workspace_id)
        await self._record(
            AuditAction.MEMBERSHIP_REVOKED, now, principal, workspace_id, user_id, ip, {}
        )

    # ------------------------------------------------------------ internal --

    def _require_member(self, principal: Principal, workspace_id: WorkspaceId) -> Role:
        role = principal.role_in(workspace_id)
        if role is None:
            raise MembershipDenied(str(workspace_id))
        return role

    def _require_owner(self, principal: Principal, workspace_id: WorkspaceId) -> None:
        role = principal.role_in(workspace_id)
        if role is None or role is not Role.OWNER:
            raise MembershipDenied(str(workspace_id))

    async def _guard_last_owner(
        self, workspace_id: WorkspaceId, existing: Membership, *, leaving: bool
    ) -> None:
        """Refuse the change that would leave nobody able to administer this workspace.

        Applies to owners removing *themselves* too. Self-service lockout is
        still lockout, and there is no support tool to undo it.
        """
        if not leaving or existing.role is not Role.OWNER:
            return
        if await self.memberships.count_owners(workspace_id) <= 1:
            raise LastOwnerProtected(str(workspace_id))

    async def _view(self, membership: Membership) -> MemberView:
        user = await self.users.get(membership.user_id)
        assert user is not None  # a membership without a user cannot exist (FK)
        return MemberView(membership=membership, email=user.email)

    async def _record(
        self,
        action: AuditAction,
        now: datetime,
        principal: Principal,
        workspace_id: WorkspaceId,
        target_user_id: UserId,
        ip: str | None,
        metadata: dict[str, object],
    ) -> None:
        await self.audit.record(
            action=action,
            now=now,
            workspace_id=workspace_id,
            actor_user_id=principal.user_id,
            target_type="membership",
            target_id=target_user_id,
            ip=ip,
            metadata={**metadata, "target_user_id": str(target_user_id)},
        )


__all__ = [
    "AlreadyAMember",
    "LastOwnerProtected",
    "MemberView",
    "MembershipDenied",
    "MembershipService",
    "NoSuchAccount",
]
