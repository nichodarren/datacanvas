"""Entry point: ``python -m app``.

Exists because of a defect found during the Fase 1 gate review. Launching with
``uvicorn app.api.app:create_app --factory`` starts fine, answers ``/health``,
and then returns 500 from every route that touches the database.

The cause is worth stating precisely, because the obvious fix does not work.
uvicorn does **not** read the event loop policy: ``Server.run()`` passes its own
``loop_factory``, and on Windows that factory is ``asyncio.ProactorEventLoop`` —
the one loop psycopg refuses to use. Setting a policy beforehand changes
nothing.

So this module runs ``Server.serve()`` inside a loop we create ourselves. That
is the whole reason it exists, and the reason there is exactly one supported
way to start the API.

The entire test suite was green while this was broken, because pytest supplies
its own loop. A test that injects its runtime says nothing about the runtime a
process actually gets.
"""

from __future__ import annotations

import asyncio

import uvicorn

from app.config import get_settings
from app.runtime import LOOP_FACTORY

HOST = "127.0.0.1"
PORT = 8000


def main() -> None:
    settings = get_settings()
    config = uvicorn.Config(
        "app.api.app:create_app",
        factory=True,
        host=HOST,
        port=PORT,
        log_level=settings.log_level.lower(),
    )
    server = uvicorn.Server(config)

    # `server.serve()`, not `server.run()`: run() would build the loop from
    # uvicorn's own factory and hand us the Proactor loop again.
    asyncio.run(server.serve(), loop_factory=LOOP_FACTORY)


if __name__ == "__main__":
    main()
