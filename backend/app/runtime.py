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


#: Pass this wherever a loop factory is accepted. Where a framework builds the
#: loop out of our reach (uvicorn, for instance), that entry point has to deal
#: with it locally — which is a problem to solve when the entry point exists,
#: with evidence, rather than now with a guess.
LOOP_FACTORY: Callable[[], asyncio.AbstractEventLoop] = selector_event_loop


__all__ = ["LOOP_FACTORY", "selector_event_loop"]
