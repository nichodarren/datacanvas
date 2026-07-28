"""Application assembly.

Thin by design (§10.6): this module wires dependencies and installs middleware.
Anything resembling a rule belongs in ``domain/``, ``auth/`` or ``authz/``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

from app.api import routes_auth, routes_members, routes_workspaces
from app.auth.email import EmailSender, LoggingEmailSender
from app.auth.passwords import PasswordHasher
from app.clock import Clock, system_clock
from app.config import Settings, get_settings
from app.domain.errors import AuthorizationError, InvariantViolation
from app.observability import configure_logging, correlation_id, new_correlation_id
from app.repositories.connection import Database
from app.storage.object_store import FilesystemObjectStore, ObjectStore

CORRELATION_HEADER = "X-Correlation-ID"

health_router = APIRouter(tags=["ops"])


@health_router.get("/health")
async def health() -> dict[str, str]:
    """Liveness only. Deliberately does not touch the database.

    A health check that fails when Postgres blips takes the whole service out
    of rotation for something a retry would have fixed.
    """
    return {"status": "ok"}


def create_app(
    *,
    settings: Settings | None = None,
    database: Database | None = None,
    store: ObjectStore | None = None,
    hasher: PasswordHasher | None = None,
    email_sender: EmailSender | None = None,
    clock: Clock = system_clock,
    secure_cookies: bool | None = None,
) -> FastAPI:
    """Build the application.

    Every collaborator can be supplied, which is what lets the test suite run
    the real app with a fixed clock and cheap password parameters instead of a
    parallel wiring that might not match.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved.log_level)
        application.state.database = database or Database(resolved.database_url)
        application.state.store = store or FilesystemObjectStore(Path(resolved.storage_root))
        application.state.hasher = hasher or PasswordHasher()
        # No provider is wired (see app.auth.email). The development sender
        # logs a loud warning with the token, so "reset mail never arrived" is
        # answered by the logs rather than by guesswork.
        application.state.email_sender = email_sender or LoggingEmailSender()
        application.state.clock = clock
        application.state.settings = resolved
        # Secure cookies are dropped silently over plain http, which turns
        # local development into "login does nothing" for an afternoon.
        application.state.secure_cookies = (
            secure_cookies if secure_cookies is not None else resolved.storage_backend == "s3"
        )
        try:
            yield
        finally:
            if database is None:
                await application.state.database.dispose()

    application = FastAPI(
        title="DataCanvas API",
        version="0.1.0",
        lifespan=lifespan,
        # Redirects turn a POST into a GET on some clients and silently drop
        # the body. Better to 404 on a wrong path than to half-succeed.
        redirect_slashes=False,
    )

    @application.middleware("http")
    async def correlate(request: Request, call_next):  # type: ignore[no-untyped-def]
        token = correlation_id.set(request.headers.get(CORRELATION_HEADER) or new_correlation_id())
        try:
            response: Response = await call_next(request)
        finally:
            current = correlation_id.get()
            correlation_id.reset(token)
        response.headers[CORRELATION_HEADER] = current
        return response

    @application.exception_handler(AuthorizationError)
    async def _authorization_denied(request: Request, exc: AuthorizationError) -> JSONResponse:
        """Every authorization failure renders as 404 (§13.3.1 L2).

        A 403 says "this exists but is not yours", which is exactly the fact
        tenant isolation is supposed to withhold. Logged at warning so the
        denial is still visible to us.
        """
        logger.warning("authorization denied", path=request.url.path)
        return JSONResponse(status_code=404, content={"detail": "not found"})

    @application.exception_handler(InvariantViolation)
    async def _invariant_violated(request: Request, exc: InvariantViolation) -> JSONResponse:
        """A broken invariant is our bug, not the caller's input.

        500, and the message stays server-side: it names internal rules.
        """
        logger.error("invariant violated", path=request.url.path, error=str(exc))
        return JSONResponse(status_code=500, content={"detail": "internal error"})

    application.include_router(health_router)
    application.include_router(routes_auth.router)
    application.include_router(routes_workspaces.router)
    application.include_router(routes_members.router)
    return application


__all__ = ["CORRELATION_HEADER", "create_app"]
