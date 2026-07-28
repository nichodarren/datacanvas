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


@pytest.mark.skipif(sys.platform != "win32", reason="ProactorEventLoop is Windows-only")
def test_the_guard_refuses_a_proactor_loop() -> None:
    """The case that shipped broken.

    Without this the failure surfaces as a 500 per request, with a traceback
    naming psycopg and nothing about how the process was launched.

    **Why the loop class is fetched by name.** mypy checks the code as every
    platform sees it, not just the one it runs on, and
    ``asyncio.ProactorEventLoop`` does not exist on Linux — so a direct
    reference fails CI while passing locally on Windows. Two obvious repairs
    both make it worse: an early ``sys.platform`` skip trades the error for
    ``unreachable`` (the skip is unconditional on Linux, and correctly flagged),
    and a ``type: ignore`` becomes an *unused* ignore on Windows, which strict
    mode also rejects. Getting it by name is the honest answer: there is nothing
    for a type checker to verify about a symbol that is absent from the platform
    it is checking.

    Found by the first CI run this project ever had — the Linux-only direction
    R-17 warned would stay invisible until deploy.
    """
    # B009 is suppressed because a constant attribute name is exactly the point.
    proactor_loop = getattr(asyncio, "ProactorEventLoop")  # noqa: B009

    async def check() -> None:
        assert_compatible_event_loop()

    with pytest.raises(RuntimeError, match="ProactorEventLoop"):
        asyncio.run(check(), loop_factory=proactor_loop)


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
