"""Identity repositories.

"Tenancy" left the title with D-039: the tenant is the account, so there is no
separate set of rows describing who owns what.

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

from app.domain.enums import PrivacyMode, UserStatus
from app.domain.identity import (
    PasswordResetToken,
    Session,
    User,
    UserPolicy,
    normalize_email,
)
from app.domain.ids import PasswordResetTokenId, SessionId, UserId
from app.repositories.tables import (
    app_user,
    login_attempt,
    password_reset_token,
    user_policy,
    user_session,
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

    async def list_active_for_user(self, user_id: UserId, now: datetime) -> list[Session]:
        """The sessions a user can actually be shown and act on.

        OWASP's Session Management guidance asks that a user be able to inspect
        their live sessions — address, client, when it started, when it was last
        used — and end any of them remotely. Every column that needs is already
        on the table; this is the query that was missing.

        Expired rows are filtered here rather than in the caller because a
        session that cannot authenticate is not a session the user has any way
        to reason about. Showing one would invite them to "revoke" something
        that was already dead and learn nothing from the result.
        """
        rows = await self._c.execute(
            sa.select(user_session)
            .where(
                user_session.c.user_id == user_id,
                user_session.c.revoked_at.is_(None),
                user_session.c.expires_at > now,
            )
            .order_by(user_session.c.last_seen_at.desc())
        )
        return [_to_session(row) for row in rows]

    async def revoke_one_for_user(
        self, session_id: SessionId, user_id: UserId, now: datetime
    ) -> bool:
        """Revoke a single session **that belongs to this user**.

        The ``user_id`` in the WHERE clause is the entire security of this
        method, and it is not defence in depth — it is the only defence. A
        session id is a plain UUID that appears in the caller's own listing, so
        without it any authenticated user could end anyone else's session by
        guessing or replaying an id. Filtering in Python after the fetch would
        be equivalent only as long as nobody ever reorders the code.

        Returns whether anything was revoked, so the route can answer 404 for
        "not yours" and "not there" alike (§13.3.1 L2).
        """
        result = await self._c.execute(
            sa.update(user_session)
            .where(
                user_session.c.id == session_id,
                user_session.c.user_id == user_id,
                user_session.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount > 0

    async def revoke_others_for_user(self, user_id: UserId, keep: SessionId, now: datetime) -> int:
        """Every live session except the one making the request.

        Used by a password change. OWASP treats that as a security boundary
        event: every other session must be invalidated, because the whole point
        of changing a password is usually that someone else may know the old
        one. Keeping the caller signed in is the one deliberate exception — a
        change that logs you out of the tab you just used reads as a failure.
        """
        result = await self._c.execute(
            sa.update(user_session)
            .where(
                user_session.c.user_id == user_id,
                user_session.c.id != keep,
                user_session.c.revoked_at.is_(None),
            )
            .values(revoked_at=now)
        )
        return result.rowcount


class UserPolicyRepository:
    """One row per account (§9.2, §13.5).

    This was ``WorkspaceRepository.get_policy`` plus the half of ``create``
    that made a policy row. It is its own repository now because it is the only
    thing left of that file's tenancy half, and folding it into
    ``UserRepository`` would put "who you are" and "what you are allowed to send
    to an LLM" behind the same object — two questions with different reasons to
    change.
    """

    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, *, user_id: UserId) -> UserPolicy:
        """The defaults, written explicitly.

        Every column has a server default, so this could insert nothing but the
        id. It does not: a row whose values live only in the DDL is a row nobody
        can read the policy of without opening a migration.
        """
        await self._c.execute(
            sa.insert(user_policy).values(
                user_id=user_id,
                llm_privacy_mode=PrivacyMode.BALANCED.value,
                allowed_providers=[],
            )
        )
        return UserPolicy(user_id=user_id)

    async def get(self, user_id: UserId) -> UserPolicy | None:
        row = (
            await self._c.execute(sa.select(user_policy).where(user_policy.c.user_id == user_id))
        ).one_or_none()
        if row is None:
            return None
        return UserPolicy(
            user_id=UserId(row.user_id),
            llm_privacy_mode=PrivacyMode(row.llm_privacy_mode),
            llm_monthly_token_budget=row.llm_monthly_token_budget,
            allowed_providers=tuple(row.allowed_providers),
            retention_versions=row.retention_versions,
        )


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
    "PasswordResetRepository",
    "SessionRepository",
    "UserPolicyRepository",
    "UserRepository",
]
