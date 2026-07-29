"""Identity and tenancy repositories.

Rows are mapped to domain objects by hand (D-021). It is repetitive, and it is
the reason ``domain/`` has no idea a database exists. An explicit mapping breaks
loudly when a column changes; an ORM one keeps working and returns something
subtly wrong.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.enums import PrivacyMode, Role, UserStatus
from app.domain.identity import (
    Membership,
    PasswordResetToken,
    Project,
    Session,
    User,
    Workspace,
    WorkspacePolicy,
    normalize_email,
)
from app.domain.ids import (
    MembershipId,
    OrganizationId,
    PasswordResetTokenId,
    ProjectId,
    SessionId,
    UserId,
    WorkspaceId,
)
from app.repositories.tables import (
    app_user,
    login_attempt,
    membership,
    password_reset_token,
    project,
    user_session,
    workspace,
    workspace_policy,
)


def _to_user(row: Row[tuple[object, ...]]) -> User:
    return User(
        id=UserId(row.id),
        email=row.email,
        password_hash=row.password_hash,
        created_at=row.created_at,
        status=UserStatus(row.status),
    )


def _to_session(row: Row[tuple[object, ...]]) -> Session:
    return Session(
        id=SessionId(row.id),
        user_id=UserId(row.user_id),
        token_hash=row.token_hash,
        created_at=row.created_at,
        last_seen_at=row.last_seen_at,
        expires_at=row.expires_at,
        revoked_at=row.revoked_at,
        user_agent=row.user_agent,
        ip_created=row.ip_created,
    )


def _to_workspace(row: Row[tuple[object, ...]]) -> Workspace:
    return Workspace(
        id=WorkspaceId(row.id),
        organization_id=OrganizationId(row.organization_id),
        name=row.name,
        created_at=row.created_at,
        created_by=UserId(row.created_by),
        is_personal=row.is_personal,
    )


def _to_membership(row: Row[tuple[object, ...]]) -> Membership:
    return Membership(
        id=MembershipId(row.id),
        user_id=UserId(row.user_id),
        workspace_id=WorkspaceId(row.workspace_id),
        role=Role(row.role),
        created_at=row.created_at,
        invited_by=UserId(row.invited_by) if row.invited_by else None,
    )


def _to_project(row: Row[tuple[object, ...]]) -> Project:
    return Project(
        id=ProjectId(row.id),
        workspace_id=WorkspaceId(row.workspace_id),
        name=row.name,
        description=row.description,
        created_at=row.created_at,
    )


class UserRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, *, email: str, password_hash: str, now: datetime) -> User:
        user = User(
            id=UserId(uuid.uuid4()),
            email=normalize_email(email),
            password_hash=password_hash,
            created_at=now,
        )
        await self._c.execute(
            sa.insert(app_user).values(
                id=user.id,
                email=user.email,
                password_hash=user.password_hash,
                created_at=user.created_at,
                status=user.status.value,
            )
        )
        return user

    async def get_by_email(self, email: str) -> User | None:
        row = (
            await self._c.execute(
                sa.select(app_user).where(app_user.c.email == normalize_email(email))
            )
        ).one_or_none()
        return _to_user(row) if row else None

    async def get(self, user_id: UserId) -> User | None:
        row = (
            await self._c.execute(sa.select(app_user).where(app_user.c.id == user_id))
        ).one_or_none()
        return _to_user(row) if row else None

    async def update_password_hash(self, user_id: UserId, password_hash: str) -> None:
        """Re-hash after the cost parameters are raised (§13.2).

        The only moment the plaintext is available is during a successful
        login, so this is called from there and nowhere else.
        """
        await self._c.execute(
            sa.update(app_user).where(app_user.c.id == user_id).values(password_hash=password_hash)
        )

    async def email_exists(self, email: str) -> bool:
        found = await self._c.scalar(
            sa.select(app_user.c.id).where(app_user.c.email == normalize_email(email))
        )
        return found is not None


class SessionRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(
        self,
        *,
        user_id: UserId,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> Session:
        session = Session(
            id=SessionId(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_created=ip,
        )
        await self._c.execute(
            sa.insert(user_session).values(
                id=session.id,
                user_id=session.user_id,
                token_hash=session.token_hash,
                created_at=session.created_at,
                last_seen_at=session.last_seen_at,
                expires_at=session.expires_at,
                user_agent=session.user_agent,
                ip_created=session.ip_created,
            )
        )
        return session

    async def get_by_token_hash(self, token_hash: str) -> Session | None:
        """Look up by hash — the reason §13.2 chose SHA-256 over argon2id."""
        row = (
            await self._c.execute(
                sa.select(user_session).where(user_session.c.token_hash == token_hash)
            )
        ).one_or_none()
        return _to_session(row) if row else None

    async def touch(self, session_id: SessionId, now: datetime) -> None:
        """Slide the idle window. Absolute expiry is untouched, by design."""
        await self._c.execute(
            sa.update(user_session).where(user_session.c.id == session_id).values(last_seen_at=now)
        )

    async def revoke(self, session_id: SessionId, now: datetime) -> None:
        # Sets revoked_at rather than deleting: a row that vanished cannot
        # explain anything during an investigation (§9.2).
        await self._c.execute(
            sa.update(user_session)
            .where(user_session.c.id == session_id, user_session.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )

    async def revoke_all_for_user(self, user_id: UserId, now: datetime) -> int:
        """FR-A.2, "log out everywhere". Returns how many sessions were live."""
        result = await self._c.execute(
            sa.update(user_session)
            .where(user_session.c.user_id == user_id, user_session.c.revoked_at.is_(None))
            .values(revoked_at=now)
        )
        return result.rowcount


class WorkspaceRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(
        self,
        *,
        organization_id: OrganizationId,
        name: str,
        created_by: UserId,
        now: datetime,
        is_personal: bool = False,
        policy: WorkspacePolicy | None = None,
    ) -> tuple[Workspace, WorkspacePolicy]:
        """A workspace without a policy is a workspace with undefined LLM egress.

        Creating both together is why this returns a pair: there is no moment,
        not even inside a transaction, when one exists without the other.
        """
        created = Workspace(
            id=WorkspaceId(uuid.uuid4()),
            organization_id=organization_id,
            name=name,
            created_at=now,
            created_by=created_by,
            is_personal=is_personal,
        )
        await self._c.execute(
            sa.insert(workspace).values(
                id=created.id,
                organization_id=created.organization_id,
                name=created.name,
                created_at=created.created_at,
                created_by=created.created_by,
                is_personal=created.is_personal,
            )
        )

        effective = policy or WorkspacePolicy(workspace_id=created.id)
        effective = WorkspacePolicy(
            workspace_id=created.id,
            llm_privacy_mode=effective.llm_privacy_mode,
            llm_monthly_token_budget=effective.llm_monthly_token_budget,
            allowed_providers=effective.allowed_providers,
            retention_versions=effective.retention_versions,
        )
        await self._c.execute(
            sa.insert(workspace_policy).values(
                workspace_id=effective.workspace_id,
                llm_privacy_mode=effective.llm_privacy_mode.value,
                llm_monthly_token_budget=effective.llm_monthly_token_budget,
                allowed_providers=list(effective.allowed_providers),
                retention_versions=effective.retention_versions,
            )
        )
        return created, effective

    async def get(self, workspace_id: WorkspaceId) -> Workspace | None:
        row = (
            await self._c.execute(sa.select(workspace).where(workspace.c.id == workspace_id))
        ).one_or_none()
        return _to_workspace(row) if row else None

    async def get_policy(self, workspace_id: WorkspaceId) -> WorkspacePolicy | None:
        row = (
            await self._c.execute(
                sa.select(workspace_policy).where(workspace_policy.c.workspace_id == workspace_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return WorkspacePolicy(
            workspace_id=WorkspaceId(row.workspace_id),
            llm_privacy_mode=PrivacyMode(row.llm_privacy_mode),
            llm_monthly_token_budget=row.llm_monthly_token_budget,
            allowed_providers=tuple(row.allowed_providers),
            retention_versions=row.retention_versions,
        )

    async def list_for_user(self, user_id: UserId) -> list[Workspace]:
        rows = await self._c.execute(
            sa.select(workspace)
            .join(membership, membership.c.workspace_id == workspace.c.id)
            .where(membership.c.user_id == user_id)
            .order_by(workspace.c.created_at)
        )
        return [_to_workspace(row) for row in rows]


class MembershipRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def grant(
        self,
        *,
        user_id: UserId,
        workspace_id: WorkspaceId,
        role: Role,
        now: datetime,
        invited_by: UserId | None = None,
    ) -> Membership:
        created = Membership(
            id=MembershipId(uuid.uuid4()),
            user_id=user_id,
            workspace_id=workspace_id,
            role=role,
            created_at=now,
            invited_by=invited_by,
        )
        await self._c.execute(
            sa.insert(membership).values(
                id=created.id,
                user_id=created.user_id,
                workspace_id=created.workspace_id,
                role=created.role.value,
                created_at=created.created_at,
                invited_by=created.invited_by,
            )
        )
        return created

    async def get(self, user_id: UserId, workspace_id: WorkspaceId) -> Membership | None:
        row = (
            await self._c.execute(
                sa.select(membership).where(
                    membership.c.user_id == user_id,
                    membership.c.workspace_id == workspace_id,
                )
            )
        ).one_or_none()
        return _to_membership(row) if row else None

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> list[tuple[Membership, str]]:
        """Members with their email addresses, oldest first.

        The email is joined in because a member list showing only UUIDs is a
        member list nobody can act on.
        """
        rows = await self._c.execute(
            sa.select(membership, app_user.c.email)
            .join(app_user, app_user.c.id == membership.c.user_id)
            .where(membership.c.workspace_id == workspace_id)
            .order_by(membership.c.created_at)
        )
        return [(_to_membership(row), row.email) for row in rows]

    async def count_owners(self, workspace_id: WorkspaceId) -> int:
        """Used to refuse the change that would leave a workspace unadministrable."""
        value = await self._c.scalar(
            sa.select(sa.func.count())
            .select_from(membership)
            .where(
                membership.c.workspace_id == workspace_id,
                membership.c.role == Role.OWNER.value,
            )
        )
        return int(value or 0)

    async def set_role(self, user_id: UserId, workspace_id: WorkspaceId, role: Role) -> None:
        await self._c.execute(
            sa.update(membership)
            .where(
                membership.c.user_id == user_id,
                membership.c.workspace_id == workspace_id,
            )
            .values(role=role.value)
        )

    async def revoke(self, user_id: UserId, workspace_id: WorkspaceId) -> None:
        """Removes access only. Nothing the member created is touched.

        Their datasets and analyses belong to the workspace, not to them.
        Deleting somebody's work because their access ended would be a
        surprising thing for a tool to decide on its own.
        """
        await self._c.execute(
            sa.delete(membership).where(
                membership.c.user_id == user_id,
                membership.c.workspace_id == workspace_id,
            )
        )

    async def roles_for_user(self, user_id: UserId) -> dict[WorkspaceId, Role]:
        """Everything a Principal needs about tenancy, in one query.

        One query on purpose: an authorization decision that fans out into
        several round-trips is one that eventually gets cached wrongly.
        """
        rows = await self._c.execute(
            sa.select(membership.c.workspace_id, membership.c.role).where(
                membership.c.user_id == user_id
            )
        )
        return {WorkspaceId(row.workspace_id): Role(row.role) for row in rows}


class PasswordResetRepository:
    """One-shot reset permissions (FR-A.6)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(
        self,
        *,
        user_id: UserId,
        token_hash: str,
        now: datetime,
        expires_at: datetime,
        ip: str | None = None,
    ) -> PasswordResetToken:
        token = PasswordResetToken(
            id=PasswordResetTokenId(uuid.uuid4()),
            user_id=user_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
            requested_ip=ip,
        )
        await self._c.execute(
            sa.insert(password_reset_token).values(
                id=token.id,
                user_id=token.user_id,
                token_hash=token.token_hash,
                created_at=token.created_at,
                expires_at=token.expires_at,
                requested_ip=token.requested_ip,
            )
        )
        return token

    async def get_by_token_hash(self, token_hash: str) -> PasswordResetToken | None:
        row = (
            await self._c.execute(
                sa.select(password_reset_token).where(
                    password_reset_token.c.token_hash == token_hash
                )
            )
        ).one_or_none()
        if row is None:
            return None
        return PasswordResetToken(
            id=PasswordResetTokenId(row.id),
            user_id=UserId(row.user_id),
            token_hash=row.token_hash,
            created_at=row.created_at,
            expires_at=row.expires_at,
            used_at=row.used_at,
            requested_ip=row.requested_ip,
        )

    async def mark_used(self, token_id: PasswordResetTokenId, now: datetime) -> int:
        """Consume the token. Returns how many rows changed.

        The ``used_at IS NULL`` clause is the concurrency guard: two
        simultaneous confirmations race on the same UPDATE and exactly one sees
        a row count of 1. Reading "is it used?" and then marking it used as two
        separate statements would let both win.
        """
        result = await self._c.execute(
            sa.update(password_reset_token)
            .where(
                password_reset_token.c.id == token_id,
                password_reset_token.c.used_at.is_(None),
            )
            .values(used_at=now)
        )
        return result.rowcount

    async def count_recent(self, *, user_id: UserId, since: datetime) -> int:
        """How many resets this account asked for lately.

        Caps inbox flooding without a second table: the requests themselves are
        the counter.
        """
        value = await self._c.scalar(
            sa.select(sa.func.count())
            .select_from(password_reset_token)
            .where(
                password_reset_token.c.user_id == user_id,
                password_reset_token.c.created_at >= since,
            )
        )
        return int(value or 0)

    async def invalidate_outstanding(self, user_id: UserId, now: datetime) -> int:
        """Burn earlier unused tokens when a new one is issued.

        Otherwise every reset mail ever sent stays a live key to the account
        until its own expiry runs out.
        """
        result = await self._c.execute(
            sa.update(password_reset_token)
            .where(
                password_reset_token.c.user_id == user_id,
                password_reset_token.c.used_at.is_(None),
            )
            .values(used_at=now)
        )
        return result.rowcount


class ProjectRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(
        self,
        *,
        workspace_id: WorkspaceId,
        name: str,
        now: datetime,
        description: str | None = None,
    ) -> Project:
        created = Project(
            id=ProjectId(uuid.uuid4()),
            workspace_id=workspace_id,
            name=name,
            description=description,
            created_at=now,
        )
        await self._c.execute(
            sa.insert(project).values(
                id=created.id,
                workspace_id=created.workspace_id,
                name=created.name,
                description=created.description,
                created_at=created.created_at,
            )
        )
        return created

    async def get(self, project_id: ProjectId) -> Project | None:
        row = (
            await self._c.execute(sa.select(project).where(project.c.id == project_id))
        ).one_or_none()
        return _to_project(row) if row else None

    async def locate(self, project_id: ProjectId) -> tuple[Project, WorkspaceId] | None:
        """The project and its workspace together, for the authorization layer.

        ``Project`` already carries ``workspace_id``, so this looks redundant —
        it is not. Returning the pair makes the shape identical to
        ``DatasetVersionRepository.locate`` and to ``DatasetRepository.locate``,
        which is what lets every authorization entry point read the same way.
        A caller that has to remember *which* of three lookups also gives them
        the workspace is a caller who will eventually remember wrong.
        """
        found = await self.get(project_id)
        return None if found is None else (found, found.workspace_id)

    async def list_for_workspace(self, workspace_id: WorkspaceId) -> list[Project]:
        rows = await self._c.execute(
            sa.select(project)
            .where(project.c.workspace_id == workspace_id)
            .order_by(project.c.created_at)
        )
        return [_to_project(row) for row in rows]


class LoginAttemptRepository:
    """Rate limiting state (§13.2). Postgres rather than Redis — see §19.2."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def record(self, *, email: str, ip: str | None, now: datetime, succeeded: bool) -> None:
        await self._c.execute(
            sa.insert(login_attempt).values(
                id=uuid.uuid4(),
                email=normalize_email(email) if "@" in email else email.strip().casefold(),
                ip=ip,
                at=now,
                succeeded=succeeded,
            )
        )

    async def recent_failures(self, *, email: str, ip: str | None, since: datetime) -> int:
        """Failures for this account **or** this address.

        Counting both closes the two obvious ways around a single counter:
        spraying one password across many accounts, and hammering one account
        from many addresses.
        """
        target = normalize_email(email) if "@" in email else email.strip().casefold()
        conditions = [login_attempt.c.email == target]
        if ip:
            conditions.append(login_attempt.c.ip == ip)
        count = await self._c.scalar(
            sa.select(sa.func.count())
            .select_from(login_attempt)
            .where(
                login_attempt.c.at >= since,
                sa.not_(login_attempt.c.succeeded),
                sa.or_(*conditions),
            )
        )
        return int(count or 0)


__all__ = [
    "LoginAttemptRepository",
    "MembershipRepository",
    "PasswordResetRepository",
    "ProjectRepository",
    "SessionRepository",
    "UserRepository",
    "WorkspaceRepository",
]
