"""Request-scoped wiring.

The API layer stays thin (§10.6): it resolves a Principal, opens a transaction,
and hands both to a service. Rules live in ``auth/``, ``authz/`` and ``domain/``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncConnection

from app.auth.email import EmailSender
from app.auth.password_reset import PasswordResetService
from app.auth.passwords import PasswordHasher
from app.auth.service import AuthService
from app.auth.tokens import COOKIE_NAME
from app.clock import Clock
from app.domain.principal import Principal
from app.repositories.connection import Database
from app.storage.object_store import ObjectStore


def get_database(request: Request) -> Database:
    database: Database = request.app.state.database
    return database


def get_store(request: Request) -> ObjectStore:
    store: ObjectStore = request.app.state.store
    return store


def get_hasher(request: Request) -> PasswordHasher:
    hasher: PasswordHasher = request.app.state.hasher
    return hasher


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


async def get_connection(
    database: Annotated[Database, Depends(get_database)],
) -> AsyncIterator[AsyncConnection]:
    """One transaction per request.

    A handler that half-succeeds leaves a user with a workspace and no
    membership — and nothing to notice it by.
    """
    async with database.transaction() as connection:
        yield connection


def get_auth_service(
    connection: Annotated[AsyncConnection, Depends(get_connection)],
    database: Annotated[Database, Depends(get_database)],
    hasher: Annotated[PasswordHasher, Depends(get_hasher)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> AuthService:
    return AuthService(connection, database=database, hasher=hasher, clock=clock)


async def get_email_sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender


def get_password_reset_service(
    connection: Annotated[AsyncConnection, Depends(get_connection)],
    sender: Annotated[EmailSender, Depends(get_email_sender)],
    hasher: Annotated[PasswordHasher, Depends(get_hasher)],
    clock: Annotated[Clock, Depends(get_clock)],
) -> PasswordResetService:
    return PasswordResetService(connection, email_sender=sender, hasher=hasher, clock=clock)


async def get_optional_principal(
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> Principal | None:
    return await auth.authenticate(request.cookies.get(COOKIE_NAME, ""))


async def require_principal(
    principal: Annotated[Principal | None, Depends(get_optional_principal)],
) -> Principal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    return principal


CurrentPrincipal = Annotated[Principal, Depends(require_principal)]
Connection = Annotated[AsyncConnection, Depends(get_connection)]
Auth = Annotated[AuthService, Depends(get_auth_service)]
Store = Annotated[ObjectStore, Depends(get_store)]
PasswordReset = Annotated[PasswordResetService, Depends(get_password_reset_service)]


__all__ = [
    "Auth",
    "Connection",
    "CurrentPrincipal",
    "PasswordReset",
    "Store",
    "get_auth_service",
    "get_clock",
    "get_connection",
    "get_database",
    "get_email_sender",
    "get_hasher",
    "get_optional_principal",
    "get_password_reset_service",
    "get_store",
    "require_principal",
]
