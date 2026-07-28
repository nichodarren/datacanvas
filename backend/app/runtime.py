"""Event loop selection.

psycopg's async mode cannot run on Windows' ``ProactorEventLoop``, which has
been the default there since Python 3.8. Every async entry point — Alembic, the
test suite, and later the API process — therefore has to ask for a
``SelectorEventLoop`` explicitly, or the first database call fails with
``InterfaceError`` and nothing in the traceback points at the loop.

``asyncio.SelectorEventLoop`` already resolves to the right implementation on
each platform: ``SelectSelector`` on Windows, ``epoll`` on Linux. No platform
branch is needed, and adding one would only produce code that is unreachable on
whichever platform the type checker happens to be looking at.

On Linux this is already the default, so naming it costs nothing and keeps both
platforms on the same loop. That symmetry is the point — a bug that appears only
on the developer's machine is a bug found late.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable


def selector_event_loop() -> asyncio.AbstractEventLoop:
    """A ``SelectorEventLoop``, on every platform.

    Suitable as ``loop_factory`` for ``asyncio.run`` and ``asyncio.Runner``.
    """
    return asyncio.SelectorEventLoop()


#: Pass this wherever a loop factory is accepted — ``asyncio.run``, Alembic,
#: pytest-asyncio, and ``app.__main__``. There is deliberately no "set the
#: policy" helper: uvicorn ignores policies and supplies its own loop_factory,
#: so a helper that only set a policy would look like a fix and not be one.
LOOP_FACTORY: Callable[[], asyncio.AbstractEventLoop] = selector_event_loop


def assert_compatible_event_loop() -> None:
    """Fail at startup rather than at the first query.

    Learned the hard way: the whole test suite passed while the application was
    unusable under uvicorn, because pytest supplies its own loop. Every
    database route answered 500 with a traceback that named psycopg and said
    nothing about how the process was launched.

    Honest failure over a plausible one (P6) — this turns that into a startup
    error that says what to do.
    """
    loop = asyncio.get_running_loop()
    if type(loop).__name__ == "ProactorEventLoop":
        raise RuntimeError(
            "running on ProactorEventLoop, which psycopg cannot use in async mode. "
            "Start the API with `python -m app`, which owns the loop. Note that "
            "setting an event loop policy does NOT help: uvicorn ignores the "
            "policy and passes its own loop_factory."
        )


__all__ = ["LOOP_FACTORY", "assert_compatible_event_loop", "selector_event_loop"]
