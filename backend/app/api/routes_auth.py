"""Authentication routes (FR-A.1, FR-A.2).

Every route here is listed in ``app.api.manifest``; adding one without a
manifest entry fails the route-manifest test (§13.3.1 L1).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.api.dependencies import Auth, CurrentPrincipal
from app.api.schemas import (
    LoginRequest,
    LogoutAllResponse,
    MeResponse,
    ProjectResponse,
    RegisterRequest,
    RegisterResponse,
    UserResponse,
    WorkspaceResponse,
)
from app.auth.service import EmailAlreadyRegistered, InvalidCredentials, TooManyAttempts
from app.auth.tokens import COOKIE_NAME
from app.domain.identity import SESSION_ABSOLUTE_TTL

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
        workspace=WorkspaceResponse(
            id=result.workspace.id,
            name=result.workspace.name,
            is_personal=result.workspace.is_personal,
            created_at=result.workspace.created_at,
            role="owner",
        ),
        project=ProjectResponse(
            id=result.project.id,
            workspace_id=result.project.workspace_id,
            name=result.project.name,
            description=result.project.description,
            created_at=result.project.created_at,
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


@router.get("/auth/me")
async def me(auth: Auth, principal: CurrentPrincipal) -> MeResponse:
    user = await auth.users.get(principal.user_id)
    if user is None:  # pragma: no cover — a valid principal implies a live user
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown user")

    workspaces = await auth.workspaces.list_for_user(principal.user_id)
    return MeResponse(
        user=UserResponse(id=user.id, email=user.email, created_at=user.created_at),
        workspaces=[
            WorkspaceResponse(
                id=workspace.id,
                name=workspace.name,
                is_personal=workspace.is_personal,
                created_at=workspace.created_at,
                role=str(principal.memberships[workspace.id]),
            )
            for workspace in workspaces
        ],
    )


__all__ = ["router"]
