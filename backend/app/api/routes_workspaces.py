"""Workspace, project and dataset-version routes (FR-A.3, FR-A.4).

Every tenant-scoped route here goes through :func:`_require_membership` or
through ``data_access.open_dataset_version``. Neither is optional, and the
cross-tenant sweep (§13.3.1 L2) checks that by calling each of these routes as
somebody who does not belong.

**404, never 403.** A 403 confirms the resource exists, and for a route whose
whole purpose is tenant isolation, that confirmation is the leak.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.dependencies import Connection, CurrentPrincipal, Store
from app.api.schemas import (
    CreateProjectRequest,
    DatasetVersionResponse,
    ProjectResponse,
    WorkspaceResponse,
)
from app.authz.data_access import DataAccessDenied, open_dataset_version
from app.clock import system_clock
from app.domain.audit import AuditAction
from app.domain.enums import Role
from app.domain.ids import DatasetVersionId, ProjectId, WorkspaceId
from app.domain.principal import Principal
from app.repositories.audit import AuditRepository
from app.repositories.identity import ProjectRepository, WorkspaceRepository

router = APIRouter(tags=["workspaces"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")


def _require_membership(
    principal: Principal, workspace_id: WorkspaceId, minimum: Role = Role.VIEWER
) -> Role:
    """Membership check that answers 404 rather than 403.

    Non-membership and insufficient role produce the same response, so the
    caller learns nothing about what exists.
    """
    role = principal.role_in(workspace_id)
    if role is None or not role.at_least(minimum):
        raise NOT_FOUND
    return role


@router.get("/workspaces")
async def list_workspaces(
    connection: Connection, principal: CurrentPrincipal
) -> list[WorkspaceResponse]:
    """Only the caller's own. There is no id in the path to point elsewhere."""
    workspaces = await WorkspaceRepository(connection).list_for_user(principal.user_id)
    return [
        WorkspaceResponse(
            id=workspace.id,
            name=workspace.name,
            is_personal=workspace.is_personal,
            created_at=workspace.created_at,
            role=str(principal.memberships[workspace.id]),
        )
        for workspace in workspaces
    ]


@router.get("/workspaces/{workspace_id}")
async def get_workspace(
    workspace_id: uuid.UUID, connection: Connection, principal: CurrentPrincipal
) -> WorkspaceResponse:
    scoped = WorkspaceId(workspace_id)
    role = _require_membership(principal, scoped)

    workspace = await WorkspaceRepository(connection).get(scoped)
    if workspace is None:
        raise NOT_FOUND
    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        is_personal=workspace.is_personal,
        created_at=workspace.created_at,
        role=str(role),
    )


@router.get("/workspaces/{workspace_id}/projects")
async def list_projects(
    workspace_id: uuid.UUID, connection: Connection, principal: CurrentPrincipal
) -> list[ProjectResponse]:
    scoped = WorkspaceId(workspace_id)
    _require_membership(principal, scoped)

    projects = await ProjectRepository(connection).list_for_workspace(scoped)
    return [
        ProjectResponse(
            id=item.id,
            workspace_id=item.workspace_id,
            name=item.name,
            description=item.description,
            created_at=item.created_at,
        )
        for item in projects
    ]


@router.post("/workspaces/{workspace_id}/projects", status_code=status.HTTP_201_CREATED)
async def create_project(
    workspace_id: uuid.UUID,
    payload: CreateProjectRequest,
    connection: Connection,
    principal: CurrentPrincipal,
) -> ProjectResponse:
    """Writing needs `editor`; a `viewer` gets the same 404 as a stranger (FR-A.5)."""
    scoped = WorkspaceId(workspace_id)
    _require_membership(principal, scoped, minimum=Role.EDITOR)

    now = system_clock()
    created = await ProjectRepository(connection).create(
        workspace_id=scoped, name=payload.name, description=payload.description, now=now
    )
    await AuditRepository(connection).record(
        action=AuditAction.PROJECT_CREATED,
        now=now,
        workspace_id=scoped,
        actor_user_id=principal.user_id,
        target_type="project",
        target_id=created.id,
    )
    return ProjectResponse(
        id=created.id,
        workspace_id=created.workspace_id,
        name=created.name,
        description=created.description,
        created_at=created.created_at,
    )


@router.get("/workspaces/{workspace_id}/projects/{project_id}")
async def get_project(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
) -> ProjectResponse:
    scoped = WorkspaceId(workspace_id)
    _require_membership(principal, scoped)

    found = await ProjectRepository(connection).get(ProjectId(project_id))
    # The second half matters as much as the first: without it, a member of
    # workspace A could read a project in workspace B by nesting its id under
    # their own workspace's path.
    if found is None or found.workspace_id != scoped:
        raise NOT_FOUND
    return ProjectResponse(
        id=found.id,
        workspace_id=found.workspace_id,
        name=found.name,
        description=found.description,
        created_at=found.created_at,
    )


@router.get("/workspaces/{workspace_id}/dataset-versions/{version_id}")
async def get_dataset_version(
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> DatasetVersionResponse:
    """The route that exercises INV-7 end to end.

    Note what is *absent*: no membership check written here. The handler cannot
    reach the data without a handle, and only ``open_dataset_version`` produces
    one. That is the difference between a check somebody remembered and a check
    that cannot be skipped.
    """
    try:
        handle = await open_dataset_version(
            principal,
            DatasetVersionId(version_id),
            connection=connection,
            store=store,
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    # Belt and braces: the id in the path must agree with the workspace the
    # handle was actually opened in, or the URL is lying about what it returns.
    if handle.workspace_id != WorkspaceId(workspace_id):
        raise NOT_FOUND

    version = handle.version
    return DatasetVersionResponse(
        id=version.id,
        dataset_id=version.dataset_id,
        version_no=version.version_no,
        content_hash=version.content_hash,
        row_count=version.row_count,
        column_count=version.column_count,
        byte_size=version.byte_size,
        ingested_at=version.ingested_at,
        data_present=handle.exists(),
    )


__all__ = ["router"]
