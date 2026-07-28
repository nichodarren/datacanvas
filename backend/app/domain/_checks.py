"""Small guards shared by domain entities."""

from __future__ import annotations

from datetime import datetime

from .errors import InvariantViolation


def ensure_aware(value: datetime, field: str) -> None:
    """Reject naive datetimes at the domain boundary.

    A naive datetime that reaches a session expiry comparison raises
    ``TypeError`` inside the authentication path — the worst possible place to
    discover the problem. Rejecting it on construction turns a production
    incident into a failing constructor.
    """
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvariantViolation(f"{field} must be timezone-aware, got naive {value!r}")


def ensure_non_empty(value: str, field: str) -> None:
    if not value.strip():
        raise InvariantViolation(f"{field} must not be blank")


__all__ = ["ensure_aware", "ensure_non_empty"]
