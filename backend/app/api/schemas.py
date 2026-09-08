"""Request and response models.

Separate from the domain on purpose. The wire format changes for reasons that
have nothing to do with the rules — a field the UI wants, a name that reads
better — and letting those reasons reach ``domain/`` is how a domain model
starts drifting toward whatever the current screen needs.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.auth.passwords import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH

#: Spelled out rather than derived from the enum: the wire format must not
#: shift because somebody renames a Python member. The obvious cost is drift, so
#: it is not left to memory — ``test_api_schemas.py`` fails if these stop
#: matching §9.2's vocabulary.
#: The five a person may correct a column *to*. ``unsupported`` is absent on
#: purpose: it is what the system says about a column it cannot type, not
#: something anybody chooses, and accepting it here would let a caller declare a
#: perfectly readable column unreadable.
LogicalTypeName = Literal[
    "numerical",
    "categorical",
    "text",
    "date",
    "boolean",
]


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


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=512)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)


class MeResponse(BaseModel):
    """Who is signed in.

    This carried ``workspaces: list[WorkspaceResponse]`` until D-039, and every
    frontend call started by reading the first entry out of it. The account is
    the tenant now, so the answer to *which tenant am I* is *you* — there is no
    list to pick from and no first element to pick wrongly.
    """

    user: UserResponse


class RegisterResponse(BaseModel):
    """Registration used to return three rows: user, workspace, project.

    It returns one, because it now creates one.
    """

    user: UserResponse


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
    """One dataset, and the facts about the bytes it is.

    Everything below ``name`` lived on a ``DatasetVersionResponse`` until D-043.
    The version page fetched that separately and had nothing on it saying which
    dataset it belonged to, which is why ``dataset_name`` had to be added back
    to it in 2026-07-31 — a field that existed only because the two halves of
    one thing were sent as two things. It is not needed now; the name is here.
    """

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    content_hash: str
    row_count: int
    column_count: int
    byte_size: int
    created_at: datetime
    #: Whether the bytes are actually present in the object store. Reaching this
    #: field at all means the caller passed through data_access.open().
    data_present: bool


class DatasetSummaryResponse(BaseModel):
    """A dataset card: enough to pick one without opening any of them.

    ``columns_needing_attention`` used to be here, counting columns whose
    detection confidence fell below a shared threshold. It went when the grid
    stopped marking those columns — a count that points at something invisible
    is a warning the reader cannot act on.

    ``version_count``, ``latest_version_id`` and ``version_no`` went with D-043.
    The first was always 1, and the other two were how a card said which of a
    dataset's versions to open — a question with one answer for every dataset
    that has ever existed in this system.
    """

    id: uuid.UUID
    name: str
    created_at: datetime
    row_count: int
    column_count: int
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
    null_markers: list[str]
    detection_confidence: float
    detection_reason: str
    overridden: bool


class SchemaContractResponse(BaseModel):
    """A versioned interpretation of a Dataset (FR-C.3, INV-3)."""

    id: uuid.UUID
    dataset_id: uuid.UUID
    version_no: int
    columns: list[ColumnSpecResponse]
    created_at: datetime
    derived_from: uuid.UUID | None


class BinResponse(BaseModel):
    """One histogram bucket, with the edges it was cut at.

    The edges travel with the count because the card labels its axis, and a
    binning rule the client re-derives is a second copy of §11.8.6(c).
    """

    lower: float
    upper: float
    count: int


class TopValueResponse(BaseModel):
    value: str
    count: int


class ColumnProfileResponse(BaseModel):
    """One card's worth of §11.8.

    Every field after ``null_share`` is optional because ``kind`` decides which
    of them mean anything — §11.8.3. A numerical column has no ``top``; a
    categorical one has no ``median``. Sending the union rather than eight
    separate shapes keeps one response model where eight would drift apart.
    """

    name: str
    ordinal: int
    physical_type: str
    logical_type: str
    kind: str
    total: int
    present: int
    distinct: int
    null_share: float
    conforming: int | None = None

    minimum: float | None = None
    median: float | None = None
    maximum: float | None = None
    earliest: str | None = None
    latest: str | None = None
    bins: list[BinResponse] = Field(default_factory=list)
    top: list[TopValueResponse] = Field(default_factory=list)
    others_count: int = 0
    others_distinct: int = 0
    length_min: int | None = None
    length_median: float | None = None
    length_max: int | None = None
    samples: list[str] = Field(default_factory=list)
    value: str | None = None


class ColumnDetailResponse(BaseModel):
    """One column, in depth (§11.7) — and its receipt.

    Deliberately loose about the five shape blocks: exactly one of `numeric`,
    `categorical`, `text`, `date` and `boolean` is filled, chosen by the
    column's **logical** type, and all five are `None` for a column with no
    values at all. Typing each of them out would put §11.7.3's per-type table in
    a second place, and two places that must agree eventually do not — the same
    argument §11.8.3 makes for letting the server decide `kind`.

    `computation_id` and `fingerprint` carry INV-5 the same way they do for the
    overview: the id to cite this panel, the fingerprint to prove two runs were
    the same computation (§9.4).

    **It carries no `step_id`, and that is a decision.** A profile opened from
    the Profile tab produces a Computation and not a Step, so it never lands in
    the Run Log — browsing twelve columns is orientation, not analysis, and
    twelve *"I looked at a column"* entries would bury the surface FR-H calls
    the primary one. Narrowing of §11.7.6(b), at the owner's direction.
    """

    computation_id: uuid.UUID
    fingerprint: str
    tool_name: str
    tool_version: int
    computed_at: datetime
    duration_ms: int

    column: str
    logical_type: str
    physical_type: str
    narrative: str
    completeness: dict[str, Any]
    #: Completeness in file order, bucketed (§11.7.3, D-056). Landed a version
    #: after the reader did, because this model **whitelists** what crosses the
    #: wire: `asdict` had it, the tool had it, the frontend type had it, and the
    #: field was dropped here in silence — a 200 with a key missing rather than
    #: an error anywhere. Third place that has to agree about this bundle's
    #: shape, and the only one that fails quietly.
    presence: dict[str, Any]
    cardinality: dict[str, Any]
    numeric: dict[str, Any] | None
    categorical: dict[str, Any] | None
    text: dict[str, Any] | None
    date: dict[str, Any] | None
    boolean: dict[str, Any] | None


class AskRequest(BaseModel):
    """One question, in English (OQ-11).

    Bounded because it is text a stranger can post: §12.2 stage 1 puts this
    into a prompt, and an unbounded field is an unbounded bill.
    """

    question: str = Field(min_length=1, max_length=2_000)


class RanResponse(BaseModel):
    """One tool that actually ran, as the reader may cite it.

    `ref` is a `computation_id` today. §12.5's own rule names that id, so the
    citation contract is already satisfied; what is missing above it is the Run
    Log row, which arrives with `step` (D-049, D-080).
    """

    ref: str
    tool: str
    args: dict[str, Any]
    #: How the frontend renders this, without knowing the tool's name (§11.2).
    #: Six values and no more (§11.4.1) — a seventh needs a component before it
    #: needs a constant.
    output_kind: str = ""


class ComplaintResponse(BaseModel):
    """Something §12.5 refused to let pass silently.

    Sent to the client rather than swallowed, because rule 3 is explicit that a
    number without support is **flagged, not hidden** — a UI that received only
    a narrative would have nothing to flag with.
    """

    kind: str
    detail: str


class TurnSummaryResponse(BaseModel):
    """One entry in the conversation log (§12.4).

    Carries `steps` because a log entry is a **handle on its own results**:
    clicking it focuses the cards that entry produced, and `ref` is what names
    them. A list of questions alone would be a list nobody could act on.
    """

    id: uuid.UUID
    asked_at: datetime
    question: str
    narrative: str | None
    grounded: bool
    stopped: str | None
    steps: list[RanResponse]
    complaints: list[ComplaintResponse]
    #: Which model wrote the sentence, for the label beside it.
    #:
    #: The **rung** (`gemini#2`) is an account and §12.8 bills per one; the
    #: **model** is what shaped the answer. Both travel because they answer
    #: different questions and move on different schedules — a rung changes
    #: when somebody edits `.env`, a model id when a vendor retires one.
    #: Empty means it was not recorded, which is true of turns stored before
    #: this existed.
    provider: str = ""
    model: str = ""


class ArtifactResponse(BaseModel):
    """One computation, as the canvas draws it.

    Fetched **separately** from the answer rather than inlined in it, and the
    payload decides that: a report is under a kilobyte, and a scatter plot at
    the 5,000-row ceiling is about a megabyte. Inlined, a six-step turn could
    carry several megabytes and the narration would wait for all of it. Fetched
    on its own, the sentence arrives first and the cards follow.
    """

    ref: str
    tool: str
    tool_version: int
    output_kind: str
    result: dict[str, Any]


class HistoryResponse(BaseModel):
    """The log for one dataset, newest first."""

    turns: list[TurnSummaryResponse]


class AskResponse(BaseModel):
    """One turn (§12.3).

    ``grounded`` is the field a caller should branch on. A narrative can be
    present and untrustworthy at the same time — that is exactly what a failed
    citation check means — so *has text* and *may be believed* are two
    questions and this answers both.
    """

    narrative: str | None
    grounded: bool
    steps: list[RanResponse]
    complaints: list[ComplaintResponse]
    #: Why the loop stopped short. `None` means it finished on its own.
    stopped: str | None
    #: What the model was told when a proposal was refused (§12.3 step 6). A
    #: turn that went nowhere should be explainable without a debugger.
    rejections: list[str]
    #: §12.2 stage 1's decision, kept for the same reason.
    categories: list[str]
    tokens: int
    #: The mode that was actually enforced (NFR-PRIV.2: the active mode is
    #: always visible). Returned per turn rather than read from settings by the
    #: client, so what the UI shows is what the gate did.
    privacy_mode: str
    #: Which model wrote the sentence, for the label beside it.
    #:
    #: The **rung** (`gemini#2`) is an account and §12.8 bills per one; the
    #: **model** is what shaped the answer. Both travel because they answer
    #: different questions and move on different schedules — a rung changes
    #: when somebody edits `.env`, a model id when a vendor retires one.
    #: Empty means it was not recorded, which is true of turns stored before
    #: this existed.
    provider: str = ""
    model: str = ""


class DatasetProfileResponse(BaseModel):
    """The Profile tab, and its receipt.

    ``computation_id`` and ``fingerprint`` are not decoration. INV-5 says every
    number displayed comes from a Computation that can be referenced, and these
    two are how it is referenced — the id to cite it, the fingerprint to prove
    two runs were the same computation (§9.4).
    """

    computation_id: uuid.UUID
    fingerprint: str
    tool_name: str
    tool_version: int
    computed_at: datetime
    duration_ms: int
    row_count: int
    columns: list[ColumnProfileResponse]


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
    null_markers: list[str] | None = None
    format_hint: str | None = None


class SchemaOverrideRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    columns: list[ColumnOverrideRequest] = Field(min_length=1)


class CommittedResponse(BaseModel):
    """The result of a committed upload."""

    dataset: DatasetResponse
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
    "BinResponse",
    "ChangePasswordRequest",
    "ChangePasswordResponse",
    "ColumnProfileResponse",
    "DatasetProfileResponse",
    "LoginRequest",
    "LogoutAllResponse",
    "MeResponse",
    "PasswordResetConfirmRequest",
    "PasswordResetRequest",
    "RegisterRequest",
    "RegisterResponse",
    "SessionResponse",
    "TopValueResponse",
    "UserResponse",
]
