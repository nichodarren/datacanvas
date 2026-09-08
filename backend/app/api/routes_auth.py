"""Authentication routes (FR-A.1, FR-A.2).

Every route here is listed in ``app.api.manifest``; adding one without a
manifest entry fails the route-manifest test (§13.3.1 L1).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.dependencies import Auth, CurrentPrincipal
from app.api.schemas import (
    ChangePasswordRequest,
    ChangePasswordResponse,
    LoginRequest,
    LogoutAllResponse,
    MeResponse,
    RegisterRequest,
    RegisterResponse,
    SessionResponse,
    UserResponse,
)
from app.auth.service import EmailAlreadyRegistered, InvalidCredentials, TooManyAttempts
from app.auth.tokens import COOKIE_NAME
from app.domain.identity import SESSION_ABSOLUTE_TTL
from app.domain.ids import SessionId

router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    """httpOnly + Secure + SameSite=Lax (§13.2).

    ``SameSite=Lax`` also covers CSRF for this API: a cross-site POST does not
    carry the cookie, so there is nothing to forge with.

    ``secure`` is off only when serving plain HTTP locally — a Secure cookie
    over http:// is silently dropped, and the resulting "login does nothing"
    costs an afternoon to diagnose.
    """
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=int(SESSION_ABSOLUTE_TTL.total_seconds()),
        path="/",
    )


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, request: Request, response: Response, auth: Auth
) -> RegisterResponse:
    try:
        result = await auth.register(
            email=payload.email,
            password=payload.password,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc

    _set_session_cookie(response, result.token, secure=request.app.state.secure_cookies)
    return RegisterResponse(
        user=UserResponse(
            id=result.user.id, email=result.user.email, created_at=result.user.created_at
        ),
    )


@router.post("/auth/login")
async def login(
    payload: LoginRequest, request: Request, response: Response, auth: Auth
) -> UserResponse:
    try:
        result = await auth.login(
            email=payload.email,
            password=payload.password,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    except TooManyAttempts as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts"
        ) from exc
    except InvalidCredentials as exc:
        # Same message for wrong password, unknown address and disabled
        # account. Anything more specific is an account-enumeration oracle.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        ) from exc

    _set_session_cookie(response, result.token, secure=request.app.state.secure_cookies)
    return UserResponse(
        id=result.user.id, email=result.user.email, created_at=result.user.created_at
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request, response: Response, auth: Auth, principal: CurrentPrincipal
) -> None:
    await auth.logout(principal.session_id, ip=_client_ip(request))
    response.delete_cookie(COOKIE_NAME, path="/")


@router.post("/auth/logout-all")
async def logout_all(
    request: Request, response: Response, auth: Auth, principal: CurrentPrincipal
) -> LogoutAllResponse:
    """FR-A.2. Revokes this session too — "everywhere" has to include here."""
    revoked = await auth.logout_everywhere(principal.user_id, ip=_client_ip(request))
    response.delete_cookie(COOKIE_NAME, path="/")
    return LogoutAllResponse(revoked_sessions=revoked)


@router.get("/auth/sessions")
async def list_sessions(auth: Auth, principal: CurrentPrincipal) -> list[SessionResponse]:
    """Every live session of the caller (OWASP Session Management).

    Scoped to the principal with no id in the path, so there is no parameter an
    attacker could point at somebody else. That is deliberate: the safest
    version of this endpoint is one that cannot be asked the wrong question.
    """
    sessions = await auth.list_sessions(principal.user_id)
    return [
        SessionResponse(
            id=session.id,
            created_at=session.created_at,
            last_seen_at=session.last_seen_at,
            expires_at=session.expires_at,
            ip_created=session.ip_created,
            user_agent=session.user_agent,
            is_current=session.id == principal.session_id,
        )
        for session in sessions
    ]


@router.delete("/auth/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_session(
    session_id: uuid.UUID, request: Request, auth: Auth, principal: CurrentPrincipal
) -> None:
    """End one remote session. 404 covers "not yours" as well as "not there".

    §13.3.1 L2: an authorization failure and a missing row must be
    indistinguishable, or the response becomes an oracle for which session ids
    exist.
    """
    revoked = await auth.revoke_session(
        principal.user_id, SessionId(session_id), ip=_client_ip(request)
    )
    if not revoked:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="session not found")


@router.post("/auth/password")
async def change_password(
    payload: ChangePasswordRequest, request: Request, auth: Auth, principal: CurrentPrincipal
) -> ChangePasswordResponse:
    """Rotate the password from inside a live session.

    401 rather than 403 for a wrong current password: it is the same failure
    login reports, and it should read the same way everywhere.
    """
    try:
        revoked = await auth.change_password(
            user_id=principal.user_id,
            session_id=principal.session_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
            ip=_client_ip(request),
        )
    except InvalidCredentials as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials"
        ) from exc
    return ChangePasswordResponse(revoked_sessions=revoked)


@router.get("/auth/me")
async def me(auth: Auth, principal: CurrentPrincipal) -> MeResponse:
    user = await auth.users.get(principal.user_id)
    if user is None:  # pragma: no cover — a valid principal implies a live user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")

    return MeResponse(
        user=UserResponse(id=user.id, email=user.email, created_at=user.created_at),
    )


__all__ = ["router"]
