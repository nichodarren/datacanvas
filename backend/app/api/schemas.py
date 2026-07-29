"""Request and response models.

Separate from the domain on purpose. The wire format changes for reasons that
have nothing to do with the rules — a field the UI wants, a name that reads
better — and letting those reasons reach ``domain/`` is how a domain model
starts drifting toward whatever the current screen needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # No length bounds here beyond the upper one: rejecting a short password at
    # login would tell an attacker something about the stored password.
    password: str = Field(max_length=MAX_PASSWORD_LENGTH)


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    created_at: datetime


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_personal: bool
    created_at: datetime
    #: The caller's role in this workspace, not the workspace's own property.
    role: str


class ProjectResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime


class CreateProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)


class MemberResponse(BaseModel):
    user_id: uuid.UUID
    email: str
    role: str
    created_at: datetime
    invited_by: uuid.UUID | None


class AddMemberRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    # Literal rather than the enum itself: the wire format should not shift
    # because somebody renames a Python member.
    role: Literal["owner", "editor", "viewer"] = "editor"


class ChangeRoleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["owner", "editor", "viewer"]


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class MeResponse(BaseModel):
    user: UserResponse
    workspaces: list[WorkspaceResponse]


class RegisterResponse(BaseModel):
    user: UserResponse
    workspace: WorkspaceResponse
    project: ProjectResponse


class DatasetVersionResponse(BaseModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    version_no: int
    content_hash: str
    row_count: int
    column_count: int
    byte_size: int
    ingested_at: datetime
    #: Whether the bytes are actually present in the object store. Reaching this
    #: field at all means the caller passed through data_access.open().
    data_present: bool


class DialectResponse(BaseModel):
    """How a delimited file will be read (FR-B.3), for the user to correct."""

    delimiter: str
    encoding: str
    has_header: bool
    confidence: float


class IngestPreviewResponse(BaseModel):
    """What the pre-commit preview returns (D-025).

    Deliberately has **no identifier**. Nothing was kept, so there is nothing to
    redeem later — and a field here implying otherwise would be the first step
    back toward the staging area D-025 rejected.

    Also no logical types: FR-B.3 requires inference to scan the whole file, and
    a prefix is not the whole file. Types arrive with the SchemaContract, after
    commit.
    """

    format: str
    dialect: DialectResponse | None
    columns: list[str]
    sample_rows: list[list[str]]
    partial: bool
    warnings: list[str]


class DatasetResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    created_at: datetime


class DatasetWithVersionResponse(BaseModel):
    """The result of a committed upload."""

    dataset: DatasetResponse
    version: DatasetVersionResponse
    columns: list[str]
    original_filename: str


class LogoutAllResponse(BaseModel):
    revoked_sessions: int


__all__ = [
    "AddMemberRequest",
    "ChangeRoleRequest",
    "CreateProjectRequest",
    "DatasetVersionResponse",
    "LoginRequest",
    "LogoutAllResponse",
    "MeResponse",
    "MemberResponse",
    "PasswordResetConfirmRequest",
    "PasswordResetRequest",
    "ProjectResponse",
    "RegisterRequest",
    "RegisterResponse",
    "UserResponse",
    "WorkspaceResponse",
]
