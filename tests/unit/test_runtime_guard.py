"""The event loop guard (``app.runtime``).

Written after the Fase 1 gate review found the application unusable under
uvicorn while all 236 tests passed. pytest supplies its own loop, so nothing in
the suite ever ran on the loop production would have used.

The lesson is more general than psycopg: **a test that injects its own runtime
proves nothing about the runtime the process actually gets.** These tests cover
the guard; the smoke check that the server really boots is in the README's run
instructions, because only launching it can prove that.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from app.runtime import assert_compatible_event_loop, selector_event_loop


def test_the_factory_returns_a_selector_loop() -> None:
    loop = selector_event_loop()
    try:
        assert "Proactor" not in type(loop).__name__
    finally:
        loop.close()


def test_the_guard_passes_on_a_selector_loop() -> None:
    async def check() -> None:
        assert_compatible_event_loop()

    asyncio.run(check(), loop_factory=selector_event_loop)


@pytest.mark.skipif(
    not hasattr(asyncio, "ProactorEventLoop"), reason="ProactorEventLoop is Windows-only"
)
def test_the_guard_refuses_a_proactor_loop() -> None:
    """The case that shipped broken.

    Without this the failure surfaces as a 500 per request, with a traceback
    naming psycopg and nothing about how the process was launched.
    """

    async def check() -> None:
        assert_compatible_event_loop()

    with pytest.raises(RuntimeError, match="ProactorEventLoop"):
        asyncio.run(check(), loop_factory=asyncio.ProactorEventLoop)


def test_uvicorn_would_choose_the_broken_loop_on_windows() -> None:
    """Pins the fact that made the fix necessary.

    uvicorn does not consult the event loop policy — it passes its own
    ``loop_factory``, and on Windows that factory is ``ProactorEventLoop``. If
    a future version stops doing that, this test fails and ``app.__main__`` can
    be simplified. Until then it documents why owning the loop is the only
    working answer.
    """
    from uvicorn.loops.asyncio import asyncio_loop_factory

    factory = asyncio_loop_factory(use_subprocess=False)
    if sys.platform == "win32":
        assert factory is asyncio.ProactorEventLoop
    else:
        assert factory is asyncio.SelectorEventLoop
