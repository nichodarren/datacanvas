"""Time, as a dependency.

``domain/`` never reads the clock — a rule enforced by a test — so "now" has to
enter the system somewhere. It enters here, as something injectable, which is
what lets a test place an event at a chosen instant instead of sleeping.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

#: Anything that answers "what time is it?" with an aware datetime.
Clock = Callable[[], datetime]


def system_clock() -> datetime:
    """The real clock, always in UTC.

    UTC, not local time: a session that expires an hour early every October is
    the kind of bug that takes a year to reproduce.
    """
    return datetime.now(UTC)


def fixed_clock(instant: datetime) -> Clock:
    """A clock frozen at ``instant``, for tests."""
    if instant.tzinfo is None:
        raise ValueError("fixed_clock requires an aware datetime")
    return lambda: instant


__all__ = ["Clock", "fixed_clock", "system_clock"]
