"""Identity and tenancy entities (DESIGN.md §9.2, FR-A).

Pure data plus the rules that belong to the data itself. No I/O, no framework
types, no clock: anything that needs "now" receives it as an argument, so every
rule here is testable without freezing time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from ._checks import ensure_aware, ensure_non_empty
from .enums import PrivacyMode, UserStatus
from .errors import InvariantViolation
from .ids import PasswordResetTokenId, SessionId, UserId

# Session lifetime (§13.2). Absolute expiry is stored per session so that
# shortening the policy later cannot silently extend sessions already issued.
SESSION_IDLE_TTL = timedelta(days=7)
SESSION_ABSOLUTE_TTL = timedelta(days=30)

#: Password reset window (FR-A.6). Short on purpose: the token arrives in a
#: mailbox, and a mailbox is exactly the thing that may already be compromised
#: when somebody resets a password.
PASSWORD_RESET_TTL = timedelta(hours=1)


def normalize_email(raw: str) -> str:
    """Casefold and trim an email for storage and lookup.

    Without this, ``Rina@example.com`` and ``rina@example.com`` become two
    accounts, and the uniqueness constraint that was supposed to prevent it
    happily allows both.
    """
    normalized = raw.strip().casefold()
    ensure_non_empty(normalized, "email")
    if "@" not in normalized:
        raise InvariantViolation(f"email must contain '@', got {raw!r}")
    return normalized


@dataclass(frozen=True, slots=True)
class User:
    id: UserId
    email: str
    password_hash: str
    created_at: datetime
    status: UserStatus = UserStatus.ACTIVE

    def __post_init__(self) -> None:
        ensure_aware(self.created_at, "created_at")
        if self.email != normalize_email(self.email):
            raise InvariantViolation(f"email must be stored normalized, got {self.email!r}")

    @property
    def can_authenticate(self) -> bool:
        return self.status is UserStatus.ACTIVE


@dataclass(frozen=True, slots=True)
class Session:
    """One row per device (§9.2, FR-A.2).

    ``token_hash`` is SHA-256 of the opaque token, never argon2id — see §13.2
    for why that difference is deliberate rather than an inconsistency.
    """

    id: SessionId
    user_id: UserId
    token_hash: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None
    user_agent: str | None = None
    ip_created: str | None = None

    def __post_init__(self) -> None:
        ensure_aware(self.created_at, "created_at")
        ensure_aware(self.last_seen_at, "last_seen_at")
        ensure_aware(self.expires_at, "expires_at")
        if self.revoked_at is not None:
            ensure_aware(self.revoked_at, "revoked_at")
        ensure_non_empty(self.token_hash, "token_hash")

    @property
    def is_revoked(self) -> bool:
        return self.revoked_at is not None

    def is_expired_at(self, now: datetime, idle_ttl: timedelta = SESSION_IDLE_TTL) -> bool:
        """Absolute expiry or idle timeout, whichever comes first (§13.2)."""
        ensure_aware(now, "now")
        return now >= self.expires_at or now - self.last_seen_at >= idle_ttl

    def is_valid_at(self, now: datetime, idle_ttl: timedelta = SESSION_IDLE_TTL) -> bool:
        return not self.is_revoked and not self.is_expired_at(now, idle_ttl)


@dataclass(frozen=True, slots=True)
class PasswordResetToken:
    """A one-shot permission to choose a new password (FR-A.6).

    Hashed with SHA-256 like a session token and for the same reason (§13.2):
    it is high-entropy, it must be findable by hash, and a leaked database dump
    must not hand out working reset links.
    """

    id: PasswordResetTokenId
    user_id: UserId
    token_hash: str
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None = None
    requested_ip: str | None = None

    def __post_init__(self) -> None:
        ensure_aware(self.created_at, "created_at")
        ensure_aware(self.expires_at, "expires_at")
        if self.used_at is not None:
            ensure_aware(self.used_at, "used_at")
        ensure_non_empty(self.token_hash, "token_hash")

    @property
    def is_used(self) -> bool:
        return self.used_at is not None

    def is_valid_at(self, now: datetime) -> bool:
        """Single use, and time-limited.

        Both halves matter. Without single use, a reset link sitting in a
        mailbox stays a working key to the account for as long as the mailbox
        exists.
        """
        ensure_aware(now, "now")
        return not self.is_used and now < self.expires_at


@dataclass(frozen=True, slots=True)
class UserPolicy:
    """Policy governing everything the account owns (§9.2, §13.5).

    This was ``WorkspacePolicy`` until D-039. The boundary it governs moved from
    the workspace to the account; the settings did not change, and neither did
    the reason they exist — the Privacy Gate (§13.5) reads ``llm_privacy_mode``
    before anything leaves for an LLM in Phase 5.

    Kept rather than deleted along with the workspace, because deleting it would
    have left a Phase 5 requirement with nowhere to read from and nothing to say
    so until Phase 5.
    """

    user_id: UserId
    llm_privacy_mode: PrivacyMode = PrivacyMode.BALANCED
    llm_monthly_token_budget: int | None = None
    allowed_providers: tuple[str, ...] = ()
    retention_versions: int | None = None

    def __post_init__(self) -> None:
        if self.llm_monthly_token_budget is not None and self.llm_monthly_token_budget < 0:
            raise InvariantViolation("llm_monthly_token_budget must not be negative")
        if self.retention_versions is not None and self.retention_versions < 1:
            raise InvariantViolation("retention_versions must be at least 1")


__all__ = [
    "PASSWORD_RESET_TTL",
    "SESSION_ABSOLUTE_TTL",
    "SESSION_IDLE_TTL",
    "PasswordResetToken",
    "Session",
    "User",
    "UserPolicy",
    "normalize_email",
]
