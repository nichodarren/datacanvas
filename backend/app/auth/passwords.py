"""Password hashing (DESIGN.md §13.2).

argon2id, with parameters at or above the current OWASP recommendation. This is
the one place in the system where being *slow* is the feature: it is what makes
a leaked hash expensive to attack.

Contrast with session tokens (``app.auth.tokens``), which are hashed with plain
SHA-256. The difference is not an inconsistency — slow hashing protects
low-entropy secrets that can be guessed, and a 256-bit random token cannot be.
"""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher as _Argon2Hasher
from argon2 import exceptions as argon2_exceptions
from argon2.low_level import Type

# OWASP: argon2id with m ≥ 19 MiB, t ≥ 2, p = 1. Chosen above the floor because
# the cost is paid once per login, not per request.
OWASP_MEMORY_COST_KIB = 65536  # 64 MiB
OWASP_TIME_COST = 3
OWASP_PARALLELISM = 4

#: Minimum length. Length beats composition rules, which mostly teach people to
#: write `Password1!` and reuse it everywhere.
MIN_PASSWORD_LENGTH = 12

#: argon2 hashes the whole input, so a very long password is a cheap way to
#: burn server CPU. The limit is far above anything a human types.
MAX_PASSWORD_LENGTH = 1024


class WeakPassword(ValueError):
    """The password does not meet the minimum policy."""


@dataclass(frozen=True, slots=True)
class VerificationResult:
    ok: bool
    #: True when the stored hash used weaker parameters than we now require.
    #: The caller re-hashes on the next successful login, so raising the cost
    #: later does not leave old accounts behind on old parameters.
    needs_rehash: bool = False


class PasswordHasher:
    """Thin wrapper over argon2-cffi, with our parameters pinned."""

    def __init__(
        self,
        *,
        memory_cost: int = OWASP_MEMORY_COST_KIB,
        time_cost: int = OWASP_TIME_COST,
        parallelism: int = OWASP_PARALLELISM,
    ) -> None:
        self._hasher = _Argon2Hasher(
            memory_cost=memory_cost,
            time_cost=time_cost,
            parallelism=parallelism,
            type=Type.ID,
        )

    @staticmethod
    def check_policy(password: str) -> None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise WeakPassword(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise WeakPassword(f"password must be at most {MAX_PASSWORD_LENGTH} characters")

    def hash(self, password: str) -> str:
        self.check_policy(password)
        return self._hasher.hash(password)

    def verify(self, password: str, stored_hash: str) -> VerificationResult:
        """Verify without leaking *why* it failed.

        Every failure returns the same result. Distinguishing "wrong password"
        from "corrupt hash" tells an attacker something about the account, and
        tells a legitimate user nothing they can act on.
        """
        try:
            self._hasher.verify(stored_hash, password)
        except (
            argon2_exceptions.VerifyMismatchError,
            argon2_exceptions.VerificationError,
            argon2_exceptions.InvalidHashError,
        ):
            return VerificationResult(ok=False)
        return VerificationResult(
            ok=True, needs_rehash=self._hasher.check_needs_rehash(stored_hash)
        )


#: Used when a login attempt names an address with no account. Verifying against
#: it costs the same as a real verification, so response time cannot be used to
#: enumerate which addresses are registered. Computed once at import.
_DUMMY_HASHER = PasswordHasher()
DUMMY_HASH = _DUMMY_HASHER.hash("dummy-password-for-timing-equalisation")


__all__ = [
    "DUMMY_HASH",
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "OWASP_MEMORY_COST_KIB",
    "OWASP_PARALLELISM",
    "OWASP_TIME_COST",
    "PasswordHasher",
    "VerificationResult",
    "WeakPassword",
]
