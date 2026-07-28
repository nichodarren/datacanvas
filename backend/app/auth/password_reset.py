"""Password reset (FR-A.6).

Kept out of ``AuthService`` because it answers a different question — *how does
somebody who has lost access get back in* — and because it has its own failure
rules. Registration and login share almost nothing with it beyond the hasher.

Three properties carry the security of this flow, and each has a test:

1. **Requesting a reset never reveals whether an address is registered.** The
   endpoint answers the same way either way.
2. **A token is single use and short lived.** A reset link sitting in a mailbox
   must stop being a key to the account.
3. **A completed reset revokes every session.** Resetting a password is what
   somebody does when they believe they were compromised; leaving the
   attacker's session alive would defeat the act entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth.email import EmailSender, PasswordResetMessage
from app.auth.passwords import PasswordHasher
from app.auth.tokens import generate_token, hash_token
from app.clock import Clock, system_clock
from app.domain.audit import AuditAction
from app.domain.errors import DomainError
from app.domain.identity import PASSWORD_RESET_TTL, normalize_email
from app.repositories.audit import AuditRepository
from app.repositories.identity import (
    PasswordResetRepository,
    SessionRepository,
    UserRepository,
)

#: Cap on outstanding requests per account, so the endpoint cannot be turned
#: into a way to flood somebody's inbox.
RESET_REQUEST_WINDOW = timedelta(hours=1)
MAX_RESET_REQUESTS = 5


class InvalidResetToken(DomainError):
    """Unknown, expired, or already used.

    One error for all three. A caller holding a bad token learns nothing about
    why, and a caller holding a good one does not need to be told.
    """


@dataclass(frozen=True, slots=True)
class ResetOutcome:
    """What happened, for the audit trail — never for the response body."""

    issued: bool
    reason: str


class PasswordResetService:
    def __init__(
        self,
        connection: AsyncConnection,
        *,
        email_sender: EmailSender,
        hasher: PasswordHasher | None = None,
        clock: Clock = system_clock,
    ) -> None:
        self._c = connection
        self._email = email_sender
        self._hasher = hasher or PasswordHasher()
        self._now = clock
        self.users = UserRepository(connection)
        self.sessions = SessionRepository(connection)
        self.tokens = PasswordResetRepository(connection)
        self.audit = AuditRepository(connection)

    async def request(self, *, email: str, ip: str | None = None) -> ResetOutcome:
        """Issue a reset token if the address belongs to an account.

        Returns quietly either way. The caller must answer identically for a
        known and an unknown address — anything else turns this endpoint into
        a way to test whether somebody has an account here.
        """
        now = self._now()
        normalized = normalize_email(email)
        user = await self.users.get_by_email(normalized)

        if user is None or not user.can_authenticate:
            await self.audit.record(
                action=AuditAction.PASSWORD_RESET_REQUESTED,
                now=now,
                ip=ip,
                metadata={"failure_code": "no_such_account"},
            )
            return ResetOutcome(issued=False, reason="no_such_account")

        recent = await self.tokens.count_recent(user_id=user.id, since=now - RESET_REQUEST_WINDOW)
        if recent >= MAX_RESET_REQUESTS:
            await self.audit.record(
                action=AuditAction.PASSWORD_RESET_REQUESTED,
                now=now,
                actor_user_id=user.id,
                ip=ip,
                metadata={"failure_code": "rate_limited"},
            )
            return ResetOutcome(issued=False, reason="rate_limited")

        # Every earlier unused token dies now. Without this, each reset mail
        # ever sent stays a live key until its own expiry.
        await self.tokens.invalidate_outstanding(user.id, now)

        raw = generate_token()
        await self.tokens.create(
            user_id=user.id,
            token_hash=hash_token(raw),
            now=now,
            expires_at=now + PASSWORD_RESET_TTL,
            ip=ip,
        )
        self._email.send_password_reset(PasswordResetMessage(to_email=user.email, token=raw))

        await self.audit.record(
            action=AuditAction.PASSWORD_RESET_REQUESTED,
            now=now,
            actor_user_id=user.id,
            target_type="user",
            target_id=user.id,
            ip=ip,
        )
        return ResetOutcome(issued=True, reason="issued")

    async def confirm(self, *, token: str, new_password: str, ip: str | None = None) -> None:
        """Consume a token and set a new password.

        Order matters here. The token is consumed *before* the password
        changes, so a failure between the two leaves the account untouched and
        the link spent — the safe direction to fail in.
        """
        now = self._now()
        self._hasher.check_policy(new_password)

        stored = await self.tokens.get_by_token_hash(hash_token(token))
        if stored is None or not stored.is_valid_at(now):
            raise InvalidResetToken

        # The UPDATE is the real check: `used_at IS NULL` in its WHERE clause
        # means two simultaneous confirmations race here and exactly one wins.
        if await self.tokens.mark_used(stored.id, now) != 1:
            raise InvalidResetToken

        await self.users.update_password_hash(stored.user_id, self._hasher.hash(new_password))

        # A reset is what somebody does when they think they were breached.
        # Leaving existing sessions alive would leave the intruder logged in.
        revoked = await self.sessions.revoke_all_for_user(stored.user_id, now)

        await self.audit.record(
            action=AuditAction.PASSWORD_RESET_COMPLETED,
            now=now,
            actor_user_id=stored.user_id,
            target_type="user",
            target_id=stored.user_id,
            ip=ip,
            metadata={"revoked_count": revoked},
        )


__all__ = [
    "MAX_RESET_REQUESTS",
    "RESET_REQUEST_WINDOW",
    "InvalidResetToken",
    "PasswordResetService",
    "ResetOutcome",
]
