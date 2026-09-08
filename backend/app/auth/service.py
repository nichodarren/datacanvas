"""Registration, login, session lifecycle (FR-A.1 to A.4, §13.2).

The service owns the *rules*; repositories own the SQL. It receives one
connection and does all its work on it, so a registration either produces a user
and their policy row — or neither. A half-registered account is a support ticket
that cannot be resolved by looking at the code.

Registration used to create five rows: a user, a workspace, a policy, an owner
membership and a first project. D-039 leaves two. The all-or-nothing property is
the same one and matters for the same reason; there is simply less of it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth.passwords import DUMMY_HASH, PasswordHasher
from app.auth.tokens import generate_token, hash_token
from app.clock import Clock, system_clock
from app.domain.audit import AuditAction
from app.domain.errors import DomainError
from app.domain.identity import (
    SESSION_ABSOLUTE_TTL,
    SESSION_IDLE_TTL,
    Session,
    User,
    normalize_email,
)
from app.domain.ids import SessionId, UserId
from app.domain.principal import Principal
from app.repositories.audit import AuditRepository
from app.repositories.connection import Database
from app.repositories.identity import (
    LoginAttemptRepository,
    PasswordResetRepository,
    SessionRepository,
    UserPolicyRepository,
    UserRepository,
)

#: Rate limiting (§13.2). Counted per account *and* per address, so neither
#: spraying one password across many accounts nor hammering one account from
#: many addresses slips past a single counter.
LOGIN_FAILURE_WINDOW = timedelta(minutes=15)
MAX_LOGIN_FAILURES = 10

# `DEFAULT_WORKSPACE_NAME` and `DEFAULT_PROJECT_NAME` were here until D-039.
# `First project` is the string the owner pointed at on the home page and asked
# to be gone; it is worth recording that the level died with the label rather
# than the label being hidden.


class AuthError(DomainError):
    """Base for every failure in this module."""


class EmailAlreadyRegistered(AuthError):
    pass


class InvalidCredentials(AuthError):
    """Wrong password, unknown address, or disabled account.

    One error for all three, deliberately. Telling them apart turns the login
    form into an account-enumeration oracle.
    """


class TooManyAttempts(AuthError):
    pass


@dataclass(frozen=True, slots=True)
class Registration:
    user: User
    session: Session
    #: The only time the raw token exists. It is never stored and cannot be
    #: recovered — only its hash reaches the database.
    token: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    user: User
    session: Session
    token: str


class AuthService:
    def __init__(
        self,
        connection: AsyncConnection,
        *,
        database: Database,
        hasher: PasswordHasher | None = None,
        clock: Clock = system_clock,
    ) -> None:
        self._c = connection
        # Failure records are written on their own connection — see
        # `_journal_failure` for why the request transaction cannot hold them.
        self._database = database
        self._hasher = hasher or PasswordHasher()
        self._now = clock
        self.users = UserRepository(connection)
        self.sessions = SessionRepository(connection)
        self.policies = UserPolicyRepository(connection)
        self.attempts = LoginAttemptRepository(connection)
        self.resets = PasswordResetRepository(connection)
        self.audit = AuditRepository(connection)

    # ------------------------------------------------------------ register --

    async def register(
        self,
        *,
        email: str,
        password: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> Registration:
        """Create an account and everything it needs to be usable.

        FR-A.3 asked for a workspace per user and this provisioned one, plus a
        policy, an owner membership and a first project — four rows of setup
        work with exactly one sensible answer, created so the user never had to
        answer it.

        D-039 removed the question instead. What is left is the policy row,
        which is not scaffolding: the Privacy Gate (§13.5) reads it in Phase 5,
        and an account without one would fail closed at the worst moment.
        """
        now = self._now()
        normalized = normalize_email(email)
        self._hasher.check_policy(password)

        if await self.users.email_exists(normalized):
            # Registration cannot hide this the way login does — the address
            # either becomes yours or it does not, and the user has to be told
            # which. The mitigation is rate limiting, not silence.
            raise EmailAlreadyRegistered(normalized)

        user = await self.users.create(
            email=normalized, password_hash=self._hasher.hash(password), now=now
        )
        await self.policies.create(user_id=user.id)

        session, token = await self._issue_session(user.id, now, ip=ip, user_agent=user_agent)

        await self.audit.record(
            action=AuditAction.USER_REGISTERED,
            now=now,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=ip,
        )
        return Registration(user=user, session=session, token=token)

    # --------------------------------------------------------------- login --

    async def login(
        self,
        *,
        email: str,
        password: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> LoginResult:
        now = self._now()
        normalized = normalize_email(email)

        failures = await self.attempts.recent_failures(
            email=normalized, ip=ip, since=now - LOGIN_FAILURE_WINDOW
        )
        if failures >= MAX_LOGIN_FAILURES:
            await self._journal_failure(
                email=normalized, ip=ip, now=now, failure_code="rate_limited", count=False
            )
            raise TooManyAttempts(normalized)

        user = await self.users.get_by_email(normalized)

        # Verify against a dummy hash when the account does not exist, so that
        # a missing account costs the same as a wrong password. Without this,
        # response time alone reveals which addresses are registered.
        stored = user.password_hash if user else DUMMY_HASH
        result = self._hasher.verify(password, stored)

        if user is None or not result.ok or not user.can_authenticate:
            await self._journal_failure(
                email=normalized,
                ip=ip,
                now=now,
                failure_code="invalid_credentials",
                actor_user_id=user.id if user else None,
            )
            raise InvalidCredentials(normalized)

        if result.needs_rehash:
            # Parameters were raised since this password was last hashed. The
            # only moment we hold the plaintext is right now.
            await self.users.update_password_hash(user.id, self._hasher.hash(password))

        await self.attempts.record(email=normalized, ip=ip, now=now, succeeded=True)
        session, token = await self._issue_session(user.id, now, ip=ip, user_agent=user_agent)
        await self.audit.record(
            action=AuditAction.LOGIN_SUCCEEDED,
            now=now,
            actor_user_id=user.id,
            target_type="session",
            target_id=session.id,
            ip=ip,
            metadata={"session_id": str(session.id)},
        )
        return LoginResult(user=user, session=session, token=token)

    # -------------------------------------------------------------- logout --

    async def logout(self, session_id: SessionId, *, ip: str | None = None) -> None:
        now = self._now()
        await self.sessions.revoke(session_id, now)
        await self.audit.record(
            action=AuditAction.LOGOUT,
            now=now,
            target_type="session",
            target_id=session_id,
            ip=ip,
            metadata={"session_id": str(session_id)},
        )

    async def logout_everywhere(self, user_id: UserId, *, ip: str | None = None) -> int:
        """FR-A.2. The action a user takes when they think they were breached."""
        now = self._now()
        revoked = await self.sessions.revoke_all_for_user(user_id, now)
        await self.audit.record(
            action=AuditAction.LOGOUT_ALL,
            now=now,
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            ip=ip,
            metadata={"revoked_count": revoked},
        )
        return revoked

    # ------------------------------------------------------------- account --

    async def list_sessions(self, user_id: UserId) -> list[Session]:
        """Every live session, newest activity first (OWASP Session Management).

        Read-only and unaudited on purpose: looking at your own sessions is not
        an event, and recording it would bury the revocations that are.
        """
        return await self.sessions.list_active_for_user(user_id, self._now())

    async def revoke_session(
        self, user_id: UserId, session_id: SessionId, *, ip: str | None = None
    ) -> bool:
        """End one session belonging to this user. False if there was none.

        The distinction this adds over `logout_everywhere` is the whole reason
        it exists: a laptop left signed in at the office should cost you that
        laptop, not every device you own.
        """
        now = self._now()
        revoked = await self.sessions.revoke_one_for_user(session_id, user_id, now)
        if not revoked:
            return False
        await self.audit.record(
            action=AuditAction.SESSION_REVOKED,
            now=now,
            actor_user_id=user_id,
            target_type="session",
            target_id=session_id,
            ip=ip,
            metadata={"session_id": str(session_id)},
        )
        return True

    async def change_password(
        self,
        *,
        user_id: UserId,
        session_id: SessionId,
        current_password: str,
        new_password: str,
        ip: str | None = None,
    ) -> int:
        """Rotate a password from inside a live session. Returns sessions ended.

        Three decisions worth stating, because each has a plausible-looking
        alternative that is wrong:

        **The current password is required.** The caller is already
        authenticated, so it looks redundant. It is not: it is what stops a
        borrowed unlocked laptop from becoming a permanent account takeover.

        **Every other session is revoked.** OWASP treats a password change as a
        security boundary event — the usual reason to change a password is that
        someone else may know the old one, and leaving their session alive
        defeats the entire act. The caller's own session survives, because
        signing someone out of the tab they are working in reads as a failure.

        **A wrong current password raises InvalidCredentials**, the same type a
        failed login raises, and it is *not* rate limited here. The login
        counter keys on an email address from an unauthenticated caller; this
        path already required a valid session to reach, and reusing that counter
        would let anyone lock a stranger out by guessing at their own account.
        """
        now = self._now()
        user = await self.users.get(user_id)
        if user is None:  # pragma: no cover — a live session implies a live user
            raise InvalidCredentials(str(user_id))

        result = self._hasher.verify(current_password, user.password_hash)
        if not result.ok:
            await self.audit.record(
                action=AuditAction.LOGIN_FAILED,
                now=now,
                actor_user_id=user_id,
                ip=ip,
                metadata={"failure_code": "password_change_rejected"},
            )
            raise InvalidCredentials(user.email)

        await self.users.update_password_hash(user_id, self._hasher.hash(new_password))
        revoked = await self.sessions.revoke_others_for_user(user_id, session_id, now)
        # An outstanding reset link must die with the old password. Without
        # this there is a real hole: an attacker requests a reset, the victim
        # notices something wrong and changes their password, and the emailed
        # token still works — the one defensive move available to the user does
        # not close the door they were trying to shut.
        await self.resets.invalidate_outstanding(user_id, now)
        await self.audit.record(
            action=AuditAction.PASSWORD_CHANGED,
            now=now,
            actor_user_id=user_id,
            target_type="user",
            target_id=user_id,
            ip=ip,
            metadata={"revoked_count": revoked},
        )
        return revoked

    # -------------------------------------------------------- authenticate --

    async def authenticate(self, token: str) -> Principal | None:
        """Resolve a raw token into a Principal, or None.

        Returns None for every reason a token can be unusable — unknown,
        revoked, expired, idle too long, or belonging to a disabled account.
        The caller cannot act differently on any of them, and neither should an
        attacker be able to.
        """
        if not token:
            return None
        now = self._now()

        session = await self.sessions.get_by_token_hash(hash_token(token))
        if session is None or not session.is_valid_at(now, SESSION_IDLE_TTL):
            return None

        user = await self.users.get(session.user_id)
        if user is None or not user.can_authenticate:
            return None

        await self.sessions.touch(session.id, now)
        return Principal(
            user_id=user.id,
            session_id=session.id,
        )

    # ------------------------------------------------------------ internal --

    async def _journal_failure(
        self,
        *,
        email: str,
        ip: str | None,
        now: datetime,
        failure_code: str,
        actor_user_id: UserId | None = None,
        count: bool = True,
    ) -> None:
        """Record a failed login on its own connection, so it survives the 401.

        The request transaction rolls back when the route raises. That is right
        for everything the caller was trying to do, and exactly wrong for the
        record that they tried. Writing these inline was the first version, and
        it silently produced two bugs at once: the audit log never saw a failed
        login, and the brute-force counter reset on every attempt — so rate
        limiting looked implemented and protected nothing.
        """
        async with self._database.transaction() as connection:
            if count:
                await LoginAttemptRepository(connection).record(
                    email=email, ip=ip, now=now, succeeded=False
                )
            await AuditRepository(connection).record(
                action=AuditAction.LOGIN_FAILED,
                now=now,
                actor_user_id=actor_user_id,
                ip=ip,
                metadata={"failure_code": failure_code},
            )

    async def _issue_session(
        self,
        user_id: UserId,
        now: datetime,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> tuple[Session, str]:
        token = generate_token()
        session = await self.sessions.create(
            user_id=user_id,
            token_hash=hash_token(token),
            now=now,
            # Stored per session rather than read from config at check time, so
            # shortening the policy later cannot retroactively extend a session
            # that was already issued.
            expires_at=now + SESSION_ABSOLUTE_TTL,
            user_agent=user_agent,
            ip=ip,
        )
        return session, token


__all__ = [
    "LOGIN_FAILURE_WINDOW",
    "MAX_LOGIN_FAILURES",
    "AuthError",
    "AuthService",
    "EmailAlreadyRegistered",
    "InvalidCredentials",
    "LoginResult",
    "Registration",
    "TooManyAttempts",
]
