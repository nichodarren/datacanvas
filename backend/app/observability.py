"""Structured logging and request correlation (NFR-OBS).

Two rules that are easier to keep from the first line of code than to retrofit:

1. **Every log line carries a correlation id.** Without one, a failure report of
   "it broke around 3pm" cannot be turned into a trace.
2. **Secrets never reach a log** (§13.8). Enforced by a redaction filter rather
   than by remembering, because the log line that leaks a token is always one
   nobody reviewed.
"""

from __future__ import annotations

import sys
import uuid
from contextvars import ContextVar
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:  # `Record` exists in loguru's stubs, not at runtime.
    from loguru import Record

#: Set per request by the middleware; read by the log formatter.
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="-")

#: Substrings that mark a value as never-loggable. Matched case-insensitively
#: against the *key*, so a new field called `api_key_for_provider` is covered
#: without anyone adding it here.
SECRET_KEY_MARKERS = ("password", "token", "secret", "cookie", "authorization", "api_key")

REDACTED = "***redacted***"


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """Replace anything whose key looks like a secret. Recurses into nested maps."""
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if any(marker in key.lower() for marker in SECRET_KEY_MARKERS):
            cleaned[key] = REDACTED
        elif isinstance(value, dict):
            cleaned[key] = redact(value)
        else:
            cleaned[key] = value
    return cleaned


def new_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def configure_logging(level: str = "INFO", *, serialize: bool = True) -> None:
    """Install the single sink.

    ``serialize`` emits JSON, which is what a log aggregator wants. Turn it off
    locally when a human is the one reading.
    """
    logger.remove()
    logger.configure(patcher=_attach_correlation_id)
    logger.add(
        sys.stderr,
        level=level.upper(),
        serialize=serialize,
        backtrace=False,
        # diagnose=True prints local variables on exceptions — which is exactly
        # how a password ends up in a log file.
        diagnose=False,
    )


def _attach_correlation_id(record: Record) -> None:
    record["extra"]["correlation_id"] = correlation_id.get()
    if record["extra"]:
        record["extra"].update(redact(record["extra"]))


__all__ = [
    "REDACTED",
    "SECRET_KEY_MARKERS",
    "configure_logging",
    "correlation_id",
    "new_correlation_id",
    "redact",
]
