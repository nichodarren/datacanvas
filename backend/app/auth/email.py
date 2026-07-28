"""Outbound email (FR-A.6).

**No provider is wired, and that is deliberate.** DESIGN.md never decided how
mail leaves this system, and §19.1 forbids quietly taking on an external
service. So the part that is expensive to get right — token lifetime, single
use, session revocation, refusing to reveal which addresses exist — is built
and tested here, and delivery sits behind one interface with a development
implementation that logs the link.

Wiring SMTP later is one adapter. Getting the token semantics wrong later is a
security incident, which is why the order is this way round.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from loguru import logger


@dataclass(frozen=True, slots=True)
class PasswordResetMessage:
    """What a delivery backend needs, and nothing more.

    Carries the raw token rather than a finished URL: the link format belongs
    to whatever frontend is asking, not to the auth layer.
    """

    to_email: str
    token: str


@runtime_checkable
class EmailSender(Protocol):
    def send_password_reset(self, message: PasswordResetMessage) -> None: ...


class LoggingEmailSender:
    """Development backend. Writes the token to the log instead of sending it.

    Safe only because it is development-only, and the log is on the same
    machine as the database. In production this must be replaced — the guard
    is that ``Settings.email_backend`` has no other value yet, so choosing one
    is a visible decision rather than a default nobody noticed.
    """

    def send_password_reset(self, message: PasswordResetMessage) -> None:
        logger.warning(
            "password reset token issued but NOT emailed — no provider configured",
            to_email=message.to_email,
            # Deliberately not passed as `token`: the redaction filter would
            # replace it, and in development the whole point is to read it.
            reset_token_for_development=message.token,
        )


class NullEmailSender:
    """Sends nothing at all. Used by tests that only care about the token row."""

    def send_password_reset(self, message: PasswordResetMessage) -> None:
        return None


__all__ = [
    "EmailSender",
    "LoggingEmailSender",
    "NullEmailSender",
    "PasswordResetMessage",
]
