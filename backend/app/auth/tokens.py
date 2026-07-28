"""Session tokens (DESIGN.md §13.2).

Opaque, 256 bits from the OS CSPRNG, stored as a SHA-256 hex digest.

**Why SHA-256 and not argon2id, when passwords use argon2id.** Slow hashing
exists to protect secrets that can be *guessed*; a 256-bit random token cannot
be. What we need from hashing here is only that a leaked database dump is not a
pile of usable session tokens. SHA-256 gives that, stays indexable — argon2id is
salted per row, so a lookup would mean scanning the table — and costs nothing on
a check that happens on every request rather than once per login.
"""

from __future__ import annotations

import hashlib
import secrets

#: 32 bytes = 256 bits (§13.2). urlsafe_b64 of 32 bytes is 43 characters.
TOKEN_BYTES = 32

#: Name of the session cookie. httpOnly + Secure + SameSite=Lax are set where
#: the response is built; SameSite=Lax is also what covers CSRF for this API,
#: since a cross-site POST does not carry the cookie.
COOKIE_NAME = "dc_session"


def generate_token() -> str:
    """A fresh opaque session token. Never stored; only its hash is."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 hex of a token, for storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def hash_prompt(prompt: str) -> str:
    """SHA-256 hex of user text destined for the audit log (§13.7.1).

    The audit log can never be deleted, so it must never hold the sentence
    itself. A hash still answers "was this the same prompt again?" — which is
    what an audit trail actually needs.
    """
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


__all__ = ["COOKIE_NAME", "TOKEN_BYTES", "generate_token", "hash_prompt", "hash_token"]
