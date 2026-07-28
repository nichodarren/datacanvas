"""Workspace member routes (FR-A.5) and password reset (FR-A.6).

The member routes are tenant-scoped, so the cross-tenant sweep picks them up
from the manifest automatically — no test had to be written for them by hand,
which is the property §13.3.1 L2 was designed for.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, status

from app.api.dependencies import Connection, CurrentPrincipal, PasswordReset
from app.api.schemas import (
    AddMemberRequest,
    ChangeRoleRequest,
    MemberResponse,
    PasswordResetConfirmRequest,
    PasswordResetRequest,
)
from app.auth.password_reset import InvalidResetToken
from app.authz.members import (
    AlreadyAMember,
    LastOwnerProtected,
    MembershipService,
    MemberView,
    NoSuchAccount,
)
from app.domain.enums import Role
from app.domain.ids import UserId, WorkspaceId

router = APIRouter(tags=["members"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _to_response(view: MemberView) -> MemberResponse:
    return MemberResponse(
        user_id=view.membership.user_id,
        email=view.email,
        role=str(view.membership.role),
        created_at=view.membership.created_at,
        invited_by=view.membership.invited_by,
    )


@router.get("/workspaces/{workspace_id}/members")
async def list_members(
    workspace_id: uuid.UUID, connection: Connection, principal: CurrentPrincipal
) -> list[MemberResponse]:
    service = MembershipService(connection)
    views = await service.list_members(principal, WorkspaceId(workspace_id))
    return [_to_response(view) for view in views]


@router.post("/workspaces/{workspace_id}/members", status_code=status.HTTP_201_CREATED)
async def add_member(
    workspace_id: uuid.UUID,
    payload: AddMemberRequest,
    request: Request,
    connection: Connection,
    principal: CurrentPrincipal,
) -> MemberResponse:
    service = MembershipService(connection)
    try:
        view = await service.add_member(
            principal,
            WorkspaceId(workspace_id),
            email=payload.email,
            role=Role(payload.role),
            ip=_client_ip(request),
        )
    except NoSuchAccount as exc:
        # 404 with a body that says *what* is missing. Distinct from the bare
        # 404 an outsider gets: this caller is already an owner here, so the
        # only thing being disclosed is that an address has no account — see
        # the trade-off recorded on NoSuchAccount.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="no account with that email"
        ) from exc
    except AlreadyAMember as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="already a member"
        ) from exc
    return _to_response(view)


@router.patch("/workspaces/{workspace_id}/members/{member_user_id}")
async def change_member_role(
    workspace_id: uuid.UUID,
    member_user_id: uuid.UUID,
    payload: ChangeRoleRequest,
    request: Request,
    connection: Connection,
    principal: CurrentPrincipal,
) -> MemberResponse:
    service = MembershipService(connection)
    try:
        view = await service.change_role(
            principal,
            WorkspaceId(workspace_id),
            user_id=UserId(member_user_id),
            role=Role(payload.role),
            ip=_client_ip(request),
        )
    except LastOwnerProtected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a workspace must keep at least one owner",
        ) from exc
    return _to_response(view)


@router.delete(
    "/workspaces/{workspace_id}/members/{member_user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_member(
    workspace_id: uuid.UUID,
    member_user_id: uuid.UUID,
    request: Request,
    connection: Connection,
    principal: CurrentPrincipal,
) -> None:
    service = MembershipService(connection)
    try:
        await service.remove_member(
            principal,
            WorkspaceId(workspace_id),
            user_id=UserId(member_user_id),
            ip=_client_ip(request),
        )
    except LastOwnerProtected as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="a workspace must keep at least one owner",
        ) from exc


# ------------------------------------------------------- password reset ----


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
