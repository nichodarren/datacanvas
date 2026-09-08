"""Table definitions — SQLAlchemy Core metadata, no ORM (D-021).

This module is the only place that knows what the database looks like.
``domain/`` never imports it; repositories map rows to domain objects by hand.
That mapping is boilerplate, and it is the price of keeping the domain layer
free of I/O — an explicit mapping fails loudly, an ORM one fails quietly.

Two rules kept deliberately:

- **JSONB is the only Postgres-specific type we lean on** (§10.3). Lists are
  stored as JSONB rather than ``ARRAY`` for that reason, even where ``ARRAY``
  would read better.
- **Enums are TEXT + CHECK, not native ``CREATE TYPE``.** Adding a value to a
  native enum is a migration; adding one here is a changed constraint. The
  readable value ends up in every dump and log either way.
"""

from __future__ import annotations

import uuid
from enum import StrEnum

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from app.domain.enums import LogicalType, PrivacyMode, UserStatus

# Explicit constraint names. Without this, Postgres invents them and a future
# migration that needs to drop one has to look it up in a live database first.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)

#: Privilege group the production login role belongs to. Created by migration
#: 0001 together with the grants that make `audit_event` append-only (§13.7).
APP_ROLE = "datacanvas_app"

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)


def _enum_check(column: str, values: type[StrEnum], *, name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{member.value}'" for member in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _id() -> sa.Column[uuid.UUID]:
    return sa.Column("id", UUID, primary_key=True)


# --------------------------------------------------------------- identity ----

# `organization` was here, always the single default row, on the argument that
# adding a tenancy column after a product has data is the most painful migration
# a SaaS gets to do. D-039 removed it along with `workspace`, which was its only
# child — the argument was sound and the level it prepared for is one this
# product decided not to have. If it ever returns, it returns as a parent of
# `app_user`, which is a different shape from the one that was here.

# Named `app_user` rather than `user`: `user` is a reserved word in Postgres, so
# every hand-written query and every psql session would need it quoted.
app_user = sa.Table(
    "app_user",
    metadata,
    _id(),
    sa.Column("email", sa.Text, nullable=False, unique=True),
    sa.Column("password_hash", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=UserStatus.ACTIVE.value),
    _enum_check("status", UserStatus, name="status"),
)

# One row per device (FR-A.2). Revocation sets `revoked_at`; it never deletes,
# because a row that vanished cannot explain anything during an investigation.
user_session = sa.Table(
    "user_session",
    metadata,
    _id(),
    sa.Column("user_id", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    # SHA-256 of the opaque token, hex — never argon2id. §13.2 explains why that
    # difference is deliberate: this column has to be indexable and cheap.
    sa.Column("token_hash", sa.Text, nullable=False, unique=True),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("last_seen_at", TS, nullable=False),
    sa.Column("expires_at", TS, nullable=False),
    sa.Column("revoked_at", TS, nullable=True),
    sa.Column("user_agent", sa.Text, nullable=True),
    sa.Column("ip_created", sa.Text, nullable=True),
    sa.Index("ix_user_session_user_id_revoked_at", "user_id", "revoked_at"),
)

# One row per account (§9.2, §13.5). This was `workspace_policy`; the boundary
# it governs moved to the account with D-039 and the columns came with it
# unchanged. Kept rather than dropped because the Privacy Gate reads
# `llm_privacy_mode` in Phase 5, and deleting it here would have made that a
# Phase 5 discovery.
user_policy = sa.Table(
    "user_policy",
    metadata,
    sa.Column(
        "user_id",
        UUID,
        sa.ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    sa.Column(
        "llm_privacy_mode",
        sa.Text,
        nullable=False,
        server_default=PrivacyMode.BALANCED.value,  # OQ-4
    ),
    sa.Column("llm_monthly_token_budget", sa.BigInteger, nullable=True),
    # JSONB rather than ARRAY — see the module docstring.
    sa.Column("allowed_providers", pg.JSONB, nullable=False, server_default="[]"),
    sa.Column("retention_versions", sa.Integer, nullable=True),
    _enum_check("llm_privacy_mode", PrivacyMode, name="llm_privacy_mode"),
    sa.CheckConstraint(
        "llm_monthly_token_budget IS NULL OR llm_monthly_token_budget >= 0",
        name="token_budget_non_negative",
    ),
    sa.CheckConstraint(
        "retention_versions IS NULL OR retention_versions >= 1",
        name="retention_at_least_one",
    ),
)


# One-shot password reset permissions (FR-A.6). Same hashing choice as sessions
# and for the same reason (§13.2): high entropy, must be findable by hash.
password_reset_token = sa.Table(
    "password_reset_token",
    metadata,
    _id(),
    sa.Column("user_id", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    sa.Column("token_hash", sa.Text, nullable=False, unique=True),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("expires_at", TS, nullable=False),
    sa.Column("used_at", TS, nullable=True),
    sa.Column("requested_ip", sa.Text, nullable=True),
    sa.Index("ix_password_reset_token_user_id_used_at", "user_id", "used_at"),
)


# ------------------------------------------------------------------- data ----

# INV-2: never updated after commit. A BEFORE UPDATE trigger enforces that in
# migration 0006 — the frozen dataclass in domain/ only covers this process.
#
# `dataset_version` was a second table here until D-043. Its columns are the ones
# below `name`, and the trigger that guarded it now guards this. What went is the
# *second* version; what stayed is that there is never a second value for the
# first one — because §9.4 builds every fingerprint out of the identity of the
# data it read, and INV-6 holds only while that identity means one set of bytes
# forever.
dataset = sa.Table(
    "dataset",
    metadata,
    _id(),
    sa.Column("owner_id", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("parquet_uri", sa.Text, nullable=False),
    sa.Column("row_count", sa.BigInteger, nullable=False),
    sa.Column("column_count", sa.Integer, nullable=False),
    sa.Column("byte_size", sa.BigInteger, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("ingest_options", pg.JSONB, nullable=False, server_default="{}"),
    sa.CheckConstraint(
        "row_count >= 0 AND column_count >= 0 AND byte_size >= 0",
        name="counts_non_negative",
    ),
    sa.Index("ix_dataset_owner_id", "owner_id"),
    # Indexed to answer "has this exact table been ingested before?" — a
    # question worth answering in the UI. **Not** a dedup key: D-026 withdrew
    # that claim, because the hash is a property of the Parquet writer as much
    # as of the data.
    sa.Index("ix_dataset_content_hash", "content_hash"),
)

# `ingested_by` went with the merge (D-043). It existed when a workspace had
# members and the uploader could differ from the owner; since D-039 made the
# account the tenant they are the same person, so the column was `owner_id`
# under another name. Its `ON DELETE RESTRICT` is what made an account with data
# undeletable — that debt closes here, not by weakening a rule but by removing a
# duplicate. Who did what is still in `audit_event`, which outlives its subject.

source_file = sa.Table(
    "source_file",
    metadata,
    _id(),
    sa.Column(
        "dataset_id",
        UUID,
        sa.ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Shown to the user; never used to build a storage path (§13.6).
    sa.Column("original_filename", sa.Text, nullable=False),
    sa.Column("mime_detected", sa.Text, nullable=False),
    sa.Column("byte_size", sa.BigInteger, nullable=False),
    sa.Column("storage_uri", sa.Text, nullable=False),
)

# INV-3: never updated; a correction is a new version pointing at its parent.
schema_contract = sa.Table(
    "schema_contract",
    metadata,
    _id(),
    sa.Column(
        "dataset_id",
        UUID,
        sa.ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("version_no", sa.Integer, nullable=False),
    sa.Column("columns", pg.JSONB, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("created_by", UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    sa.Column(
        "derived_from",
        UUID,
        sa.ForeignKey("schema_contract.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    sa.UniqueConstraint(
        "dataset_id", "version_no", name="uq_schema_contract_dataset_id_version_no"
    ),
    sa.CheckConstraint("version_no >= 1", name="version_no_positive"),
    # Version 1 is pure auto-detection and derives from nothing; every later
    # version must say what it corrects. Mirrors the domain rule, one layer down.
    sa.CheckConstraint(
        "(version_no = 1 AND derived_from IS NULL)"
        " OR (version_no > 1 AND derived_from IS NOT NULL)",
        name="derivation_matches_version",
    ),
)


# -------------------------------------------------------------- execution ----

# Two of the five execution tables, created by migration 0005 because
# `describe_dataset` uses both. `step`, `artifact`, `finding` and
# `conversation_turn` are deliberately still absent: they belong to the Step
# executor, and §20 says a table created before anything uses it rots.
tool_version = sa.Table(
    "tool_version",
    metadata,
    _id(),
    sa.Column("tool_name", sa.Text, nullable=False),
    sa.Column("version", sa.Integer, nullable=False),
    sa.Column("summary", sa.Text, nullable=False),
    sa.Column("registered_at", TS, nullable=False),
    # INV-4: the version rises whenever output could change, so one
    # (name, version) must describe one behaviour forever.
    sa.UniqueConstraint("tool_name", "version", name="uq_tool_version_tool_name_version"),
    sa.CheckConstraint("version >= 1", name="version_starts_at_one"),
)

# INV-2's sibling: never UPDATEd, enforced by trigger. The same fingerprint
# answering differently at two points in time is INV-6 broken in storage.
computation = sa.Table(
    "computation",
    metadata,
    _id(),
    sa.Column("fingerprint", sa.Text, nullable=False),
    sa.Column("tool_name", sa.Text, nullable=False),
    sa.Column("tool_version", sa.Integer, nullable=False),
    sa.Column("args", pg.JSONB, nullable=False),
    sa.Column(
        "dataset_id",
        UUID,
        sa.ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "schema_contract_id",
        UUID,
        sa.ForeignKey("schema_contract.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("parents", pg.JSONB, nullable=False, server_default="[]"),
    sa.Column("result", pg.JSONB, nullable=False),
    sa.Column("computed_at", TS, nullable=False),
    sa.Column(
        "computed_by", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("duration_ms", sa.Integer, nullable=False),
    # The cache itself. Enforced here rather than by whoever writes the next
    # lookup: asking the same question twice must find the first answer.
    sa.UniqueConstraint("fingerprint", name="uq_computation_fingerprint"),
    sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
    sa.CheckConstraint("tool_version >= 1", name="tool_version_starts_at_one"),
    sa.Index("ix_computation_dataset_id", "dataset_id"),
)


# --------------------------------------------------------- conversation ----

# What was asked and what came back, for **display** — never for the model
# (§12.4). One row per turn rather than per message: a log entry is a handle on
# the computations it produced, and `role`/`content` would put the question in
# one row and its results in another with nothing joining them.
#
# Not append-only, and that is the point. §13.7.1 keeps only `sha256(prompt)`
# in the audit log precisely so the sentence itself can live somewhere it can
# be deleted (NFR-PRIV.3, §13.5.4).
conversation_turn = sa.Table(
    "conversation_turn",
    metadata,
    _id(),
    sa.Column(
        "dataset_id",
        UUID,
        sa.ForeignKey("dataset.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column(
        "schema_contract_id",
        UUID,
        sa.ForeignKey("schema_contract.id", ondelete="CASCADE"),
        nullable=False,
    ),
    sa.Column("asked_by", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    sa.Column("asked_at", TS, nullable=False),
    sa.Column("question", sa.Text, nullable=False),
    sa.Column("narrative", sa.Text, nullable=True),
    sa.Column("grounded", sa.Boolean, nullable=False),
    sa.Column("stopped", sa.Text, nullable=True),
    # `[{ref, tool, args}, …]` — the link a log entry follows to its cards.
    sa.Column("steps", pg.JSONB, nullable=False, server_default="[]"),
    sa.Column("complaints", pg.JSONB, nullable=False, server_default="[]"),
    sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
    # Which rung answered, and which model it ran. Two columns because they
    # answer different questions: the rung is an account (§12.8 bills per one)
    # and the model is what shaped the answer.
    sa.Column("provider", sa.Text, nullable=False, server_default=""),
    sa.Column("model", sa.Text, nullable=False, server_default=""),
    sa.CheckConstraint("tokens >= 0", name="tokens_non_negative"),
    sa.CheckConstraint("length(question) > 0", name="question_is_not_empty"),
    sa.Index("ix_conversation_turn_dataset_asked", "dataset_id", "asked_at"),
)


# ------------------------------------------------------------------ audit ----

# Append-only, enforced by trigger and by grant (§13.7). `actor_user_id` is
# nullable on purpose: a failed login often has no identifiable user, and that
# is exactly the event worth keeping.
audit_event = sa.Table(
    "audit_event",
    metadata,
    _id(),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("at", TS, nullable=False),
    # No foreign keys, on purpose (migration 0003). The audit log has to
    # outlive the data it describes, and a reference would prevent exactly
    # that: SET NULL is an UPDATE, and the append-only trigger refuses it, so
    # a referenced workspace could never be deleted at all. This column
    # records who, as of then; resolving it now is best-effort.
    #
    # `workspace_id` sat beside it until D-039. The account is the tenant now,
    # so *where this happened* and *who did it* are one fact, and the column
    # was a second copy of the one below.
    sa.Column("actor_user_id", UUID, nullable=True),
    sa.Column("target_type", sa.Text, nullable=True),
    sa.Column("target_id", UUID, nullable=True),
    # TEXT rather than INET: test clients and proxies produce values that are not
    # valid addresses, and an audit write must never fail because of its own
    # metadata.
    sa.Column("ip", sa.Text, nullable=True),
    sa.Column("metadata", pg.JSONB, nullable=False, server_default="{}"),
    sa.Index("ix_audit_event_actor_user_id_at", "actor_user_id", "at"),
)

# Login throttling lives in Postgres, not Redis (§13.2, §19.2). At A-2 scale a
# table with an index is enough, and it removes a service we would otherwise
# have to operate for one counter.
login_attempt = sa.Table(
    "login_attempt",
    metadata,
    _id(),
    sa.Column("email", sa.Text, nullable=False),
    sa.Column("ip", sa.Text, nullable=True),
    sa.Column("at", TS, nullable=False),
    sa.Column("succeeded", sa.Boolean, nullable=False),
    sa.Index("ix_login_attempt_email_at", "email", "at"),
    sa.Index("ix_login_attempt_ip_at", "ip", "at"),
)


#: Tables whose rows may never be UPDATEd (INV-2, INV-3).
IMMUTABLE_TABLES = ("dataset", "schema_contract", "computation")

#: Table that may never be UPDATEd or DELETEd (§13.7).
APPEND_ONLY_TABLES = ("audit_event",)

#: Logical types are validated in `schema_contract.columns` (JSONB) by the
#: schema layer rather than by a CHECK — a constraint cannot see inside a JSONB
#: array. Re-exported so that layer has one source for the list.
SUPPORTED_LOGICAL_TYPES = tuple(t.value for t in LogicalType)


__all__ = [
    "APPEND_ONLY_TABLES",
    "APP_ROLE",
    "IMMUTABLE_TABLES",
    "NAMING_CONVENTION",
    "SUPPORTED_LOGICAL_TYPES",
    "app_user",
    "audit_event",
    "computation",
    "dataset",
    "login_attempt",
    "metadata",
    "password_reset_token",
    "schema_contract",
    "source_file",
    "tool_version",
    "user_policy",
    "user_session",
]
