"""Password reset (FR-A.6).

This file used to be ``routes_members.py`` and carried FR-A.5's four member
routes alongside these two. D-039 removed FR-A.5, and rather than leave the
password-reset routes in a module named after a feature that no longer exists,
the module was renamed to what is left in it.

Both routes are public by necessity: whoever needs them has lost their password.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.api.dependencies import PasswordReset
from app.api.schemas import PasswordResetConfirmRequest, PasswordResetRequest
from app.auth.password_reset import InvalidResetToken

router = APIRouter(tags=["auth"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.post("/auth/password-reset", status_code=status.HTTP_202_ACCEPTED)
async def request_password_reset(
    payload: PasswordResetRequest, request: Request, service: PasswordReset
) -> None:
    """Always 202, whether or not the address has an account.

    The status code, the body and the timing must not depend on that — any
    difference turns this endpoint into a way to test who has an account here.
    """
    await service.request(email=payload.email, ip=_client_ip(request))


@router.post("/auth/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm_password_reset(
    payload: PasswordResetConfirmRequest, request: Request, service: PasswordReset
) -> None:
    try:
        await service.confirm(
            token=payload.token,
            new_password=payload.password,
            ip=_client_ip(request),
        )
    except InvalidResetToken as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="invalid or expired token"
        ) from exc


__all__ = ["router"]
