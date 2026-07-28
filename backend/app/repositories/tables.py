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

from app.domain.enums import ColumnRole, LogicalType, PrivacyMode, Role, UserStatus
from app.domain.ids import OrganizationId

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

#: The single default organization (§9.2: prepared, not implemented). Seeded by
#: migration 0001 with this exact id, so registration can attach a workspace to
#: it without a lookup. The migration hardcodes the literal rather than importing
#: this constant — migration history must not change when application code does.
DEFAULT_ORGANIZATION_ID = OrganizationId(uuid.UUID("00000000-0000-4000-8000-000000000000"))

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)


def _enum_check(column: str, values: type[StrEnum], *, name: str) -> sa.CheckConstraint:
    allowed = ", ".join(f"'{member.value}'" for member in values)
    return sa.CheckConstraint(f"{column} IN ({allowed})", name=name)


def _id() -> sa.Column[uuid.UUID]:
    return sa.Column("id", UUID, primary_key=True)


# --------------------------------------------------------------- identity ----

# `organization` exists and is always the single default row (§9.2, NFR-EXT.5).
# Adding a tenancy column after a product has data is the most painful migration
# a SaaS gets to do, so the column exists before the feature does.
organization = sa.Table(
    "organization",
    metadata,
    _id(),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False),
)

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

workspace = sa.Table(
    "workspace",
    metadata,
    _id(),
    sa.Column(
        "organization_id",
        UUID,
        sa.ForeignKey("organization.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column(
        "created_by", UUID, sa.ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("is_personal", sa.Boolean, nullable=False, server_default=sa.false()),
)

workspace_policy = sa.Table(
    "workspace_policy",
    metadata,
    sa.Column(
        "workspace_id",
        UUID,
        sa.ForeignKey("workspace.id", ondelete="CASCADE"),
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

membership = sa.Table(
    "membership",
    metadata,
    _id(),
    sa.Column("user_id", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
    sa.Column(
        "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("role", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Column("invited_by", UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
    # One role per user per workspace. Two rows would make "what may they do?"
    # a question with two answers.
    sa.UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_id_workspace_id"),
    _enum_check("role", Role, name="role"),
)

project = sa.Table(
    "project",
    metadata,
    _id(),
    sa.Column(
        "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
    ),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("description", sa.Text, nullable=True),
    sa.Column("created_at", TS, nullable=False),
    sa.Index("ix_project_workspace_id", "workspace_id"),
)


# ------------------------------------------------------------------- data ----

dataset = sa.Table(
    "dataset",
    metadata,
    _id(),
    sa.Column("project_id", UUID, sa.ForeignKey("project.id", ondelete="CASCADE"), nullable=False),
    sa.Column("name", sa.Text, nullable=False),
    sa.Column("created_at", TS, nullable=False),
    sa.Index("ix_dataset_project_id", "project_id"),
)

# INV-2: never updated after commit. A BEFORE UPDATE trigger enforces that in
# migration 0001 — the frozen dataclass in domain/ only covers this process.
dataset_version = sa.Table(
    "dataset_version",
    metadata,
    _id(),
    sa.Column("dataset_id", UUID, sa.ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False),
    sa.Column("version_no", sa.Integer, nullable=False),
    sa.Column("content_hash", sa.Text, nullable=False),
    sa.Column("parquet_uri", sa.Text, nullable=False),
    sa.Column("row_count", sa.BigInteger, nullable=False),
    sa.Column("column_count", sa.Integer, nullable=False),
    sa.Column("byte_size", sa.BigInteger, nullable=False),
    sa.Column("ingested_at", TS, nullable=False),
    sa.Column(
        "ingested_by", UUID, sa.ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("ingest_options", pg.JSONB, nullable=False, server_default="{}"),
    sa.UniqueConstraint(
        "dataset_id", "version_no", name="uq_dataset_version_dataset_id_version_no"
    ),
    sa.CheckConstraint("version_no >= 1", name="version_no_positive"),
    sa.CheckConstraint(
        "row_count >= 0 AND column_count >= 0 AND byte_size >= 0",
        name="counts_non_negative",
    ),
    # Same file uploaded twice = same hash = storage dedup (§9.2).
    sa.Index("ix_dataset_version_content_hash", "content_hash"),
)

source_file = sa.Table(
    "source_file",
    metadata,
    _id(),
    sa.Column(
        "dataset_version_id",
        UUID,
        sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
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
        "dataset_version_id",
        UUID,
        sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
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
        "dataset_version_id", "version_no", name="uq_schema_contract_dataset_version_id_version_no"
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


# ------------------------------------------------------------------ audit ----

# Append-only, enforced by trigger and by grant (§13.7). Both nullable columns
# are nullable on purpose: a failed login has no workspace and often no
# identifiable user, and that is exactly the event worth keeping.
audit_event = sa.Table(
    "audit_event",
    metadata,
    _id(),
    sa.Column("action", sa.Text, nullable=False),
    sa.Column("at", TS, nullable=False),
    sa.Column(
        "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column(
        "actor_user_id", UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    ),
    sa.Column("target_type", sa.Text, nullable=True),
    sa.Column("target_id", UUID, nullable=True),
    # TEXT rather than INET: test clients and proxies produce values that are not
    # valid addresses, and an audit write must never fail because of its own
    # metadata.
    sa.Column("ip", sa.Text, nullable=True),
    sa.Column("metadata", pg.JSONB, nullable=False, server_default="{}"),
    sa.Index("ix_audit_event_workspace_id_at", "workspace_id", "at"),
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
IMMUTABLE_TABLES = ("dataset_version", "schema_contract")

#: Table that may never be UPDATEd or DELETEd (§13.7).
APPEND_ONLY_TABLES = ("audit_event",)

#: Logical types and column roles are validated in `schema_contract.columns`
#: (JSONB) by the schema layer rather than by a CHECK — a constraint cannot see
#: inside a JSONB array. Re-exported so that layer has one source for the list.
SUPPORTED_LOGICAL_TYPES = tuple(t.value for t in LogicalType)
SUPPORTED_COLUMN_ROLES = tuple(r.value for r in ColumnRole)


__all__ = [
    "APPEND_ONLY_TABLES",
    "APP_ROLE",
    "DEFAULT_ORGANIZATION_ID",
    "IMMUTABLE_TABLES",
    "NAMING_CONVENTION",
    "SUPPORTED_COLUMN_ROLES",
    "SUPPORTED_LOGICAL_TYPES",
    "app_user",
    "audit_event",
    "dataset",
    "dataset_version",
    "login_attempt",
    "membership",
    "metadata",
    "organization",
    "project",
    "schema_contract",
    "source_file",
    "user_session",
    "workspace",
    "workspace_policy",
]
