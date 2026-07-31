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

#: Spelled out rather than derived from the enum, for the same reason the role
#: literals below are: the wire format must not shift because somebody renames
#: a Python member. The obvious cost is drift, so it is not left to memory —
#: ``test_api_schemas.py`` fails if these stop matching §9.2's vocabulary.
LogicalTypeName = Literal[
    "integer",
    "decimal",
    "boolean",
    "categorical",
    "text",
    "date",
    "datetime",
    "duration",
    "unsupported",
]
ColumnRoleName = Literal["identifier", "measure", "dimension", "timestamp", "ignored"]


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
    #: The name of the Dataset this version belongs to.
    #:
    #: Sent because the version page had nothing on it that said *which dataset
    #: am I looking at*. The heading there used to read "Dataset version N" and
    #: was removed with the version badge (§14.2, 2026-07-31); the dataset's own
    #: identity went with it as a side effect nobody intended, leaving a page
    #: that was a grid and a brand link.
    #:
    #: This is **not** the version badge coming back. P4 — *always know which
    #: version you are looking at* — stays unmet in the UI on purpose until
    #: Phase 3, where it returns attached to results rather than to a header.
    dataset_name: str
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


class DatasetSummaryResponse(BaseModel):
    """A dataset card: enough to pick one without opening any of them.

    ``columns_needing_attention`` used to be here, counting columns whose
    detection confidence fell below a shared threshold. It went when the grid
    stopped marking those columns — a count that points at something invisible
    is a warning the reader cannot act on.
    """

    id: uuid.UUID
    name: str
    created_at: datetime
    version_count: int
    latest_version_id: uuid.UUID | None
    version_no: int | None
    row_count: int | None
    column_count: int | None
    schema_version_no: int | None


class SampleDatasetResponse(BaseModel):
    """One offer on the empty state (FR-B.5)."""

    key: str
    name: str
    description: str


class LoadSampleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=64)


class ColumnSpecResponse(BaseModel):
    """One column's interpretation (§9.2).

    ``detection_reason`` travels with ``detection_confidence`` for a reason:
    FR-B.3 requires the detection be shown **for correction**, and a bare 0.5
    gives a person nothing to disagree with.
    """

    name: str
    ordinal: int
    physical_type: str
    logical_type: str
    role: str | None
    null_markers: list[str]
    detection_confidence: float
    detection_reason: str
    overridden: bool


class SchemaContractResponse(BaseModel):
    """A versioned interpretation of a DatasetVersion (FR-C.3, INV-3)."""

    id: uuid.UUID
    dataset_version_id: uuid.UUID
    version_no: int
    columns: list[ColumnSpecResponse]
    created_at: datetime
    derived_from: uuid.UUID | None


class RowPageResponse(BaseModel):
    """One server-side page of the grid (FR-D.1, FR-D.2).

    Cells are strings because the normalized Parquet holds strings — the table
    is stored as text and interpreted by the SchemaContract (D-029). Sending
    typed JSON would let the grid form a second opinion about the type, quietly
    competing with the one the user can actually see and correct.
    """

    columns: list[str]
    rows: list[list[str | None]]
    offset: int
    limit: int
    total_rows: int


class ColumnOverrideRequest(BaseModel):
    """One column correction (FR-C.2).

    Only interpretation is changeable. ``name``, ``ordinal`` and
    ``physical_type`` are facts about the file rather than opinions about it,
    so they are absent here by design.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    logical_type: LogicalTypeName | None = None
    role: ColumnRoleName | None = None
    null_markers: list[str] | None = None
    format_hint: str | None = None


class SchemaOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnOverrideRequest] = Field(min_length=1)


class DatasetWithVersionResponse(BaseModel):
    """The result of a committed upload."""

    dataset: DatasetResponse
    version: DatasetVersionResponse
    schema_contract: SchemaContractResponse
    original_filename: str


class LogoutAllResponse(BaseModel):
    revoked_sessions: int


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Bounded above only, like login: a length rule on the *current* password
    # would report something about what is stored.
    current_password: str = Field(max_length=MAX_PASSWORD_LENGTH)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class ChangePasswordResponse(BaseModel):
    #: Other sessions ended by the change. Returned so the UI can say what
    #: happened rather than leaving the user to wonder whether it did.
    revoked_sessions: int


class SessionResponse(BaseModel):
    """One live session, as its owner sees it (OWASP Session Management).

    Carries no token and no hash — only what identifies a session to the person
    who created it. ``ip_created`` and ``user_agent`` are the user's own data
    shown back to them, which is why they may appear here and may never appear
    in `audit_event.metadata` (§13.7.1).
    """

    id: uuid.UUID
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip_created: str | None
    user_agent: str | None
    #: True for the session making the request. The UI must never offer to
    #: revoke this one as if it were remote — that is what "Sign out" is.
    is_current: bool


__all__ = [
    "AddMemberRequest",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
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
    "SessionResponse",
    "UserResponse",
    "WorkspaceResponse",
]
