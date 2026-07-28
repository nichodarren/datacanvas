"""Foundation: identity, tenancy, data identity, audit.

The scope of this migration is fixed by DESIGN.md §20 Fase 1: identity and
tenancy, the data-identity tables that `data_access.open()` needs something to
open, and the audit log. Execution tables (step, computation, artifact, finding,
conversation_turn) arrive in Fase 3 — tables created before anything uses them
rot.

Written out by hand rather than generated from the metadata. A migration must
replay the schema *as it was*, and `metadata.create_all()` inside a migration
replays the schema *as it is now* — which stops being the same thing the moment
the next change lands.

Revision ID: 0001
Revises:
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"

# Kept as a literal on purpose: see DEFAULT_ORGANIZATION_ID in
# app/repositories/tables.py. A test asserts the two agree.
DEFAULT_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000000"

# Tables the application may read and write freely.
_MUTABLE_TABLES = (
    "organization",
    "app_user",
    "user_session",
    "workspace",
    "workspace_policy",
    "membership",
    "project",
    "dataset",
    "source_file",
    "login_attempt",
)
# INV-2 / INV-3: insert and delete, never update.
_IMMUTABLE_TABLES = ("dataset_version", "schema_contract")


def upgrade() -> None:
    _create_identity_tables()
    _create_data_tables()
    _create_audit_tables()
    _install_immutability_guards()
    _install_application_role()
    _seed_default_organization()


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE}")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE}")

    op.execute("DROP TRIGGER IF EXISTS trg_audit_event_append_only ON audit_event")
    for table in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {table}")
    op.execute("DROP FUNCTION IF EXISTS datacanvas_reject_update()")
    op.execute("DROP FUNCTION IF EXISTS datacanvas_reject_change()")

    for table in (
        "login_attempt",
        "audit_event",
        "schema_contract",
        "source_file",
        "dataset_version",
        "dataset",
        "project",
        "membership",
        "workspace_policy",
        "workspace",
        "user_session",
        "app_user",
        "organization",
    ):
        op.drop_table(table)

    # The role is intentionally NOT dropped: it may own grants in other
    # databases on the same cluster, and dropping it there is not this
    # migration's business.


# --------------------------------------------------------------- identity ----


def _create_identity_tables() -> None:
    op.create_table(
        "organization",
        sa.Column("id", UUID, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_organization"),
    )

    # `app_user`, not `user`: `user` is reserved in Postgres and every
    # hand-written query would need it quoted.
    op.create_table(
        "app_user",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="active"),
        sa.PrimaryKeyConstraint("id", name="pk_app_user"),
        sa.UniqueConstraint("email", name="uq_app_user_email"),
        sa.CheckConstraint("status IN ('active', 'disabled')", name="status"),
    )

    op.create_table(
        "user_session",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        # SHA-256 hex of the opaque token, never argon2id (§13.2).
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("last_seen_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("ip_created", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_user_session"),
        sa.UniqueConstraint("token_hash", name="uq_user_session_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_user_session_user_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_user_session_user_id_revoked_at", "user_session", ["user_id", "revoked_at"])

    op.create_table(
        "workspace",
        sa.Column("id", UUID, nullable=False),
        sa.Column("organization_id", UUID, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id", name="pk_workspace"),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organization.id"],
            name="fk_workspace_organization_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["app_user.id"], name="fk_workspace_created_by", ondelete="RESTRICT"
        ),
    )

    op.create_table(
        "workspace_policy",
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("llm_privacy_mode", sa.Text, nullable=False, server_default="balanced"),
        sa.Column("llm_monthly_token_budget", sa.BigInteger, nullable=True),
        sa.Column("allowed_providers", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("retention_versions", sa.Integer, nullable=True),
        sa.PrimaryKeyConstraint("workspace_id", name="pk_workspace_policy"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name="fk_workspace_policy_workspace_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "llm_privacy_mode IN ('strict', 'balanced', 'full', 'local')",
            name="llm_privacy_mode",
        ),
        sa.CheckConstraint(
            "llm_monthly_token_budget IS NULL OR llm_monthly_token_budget >= 0",
            name="token_budget_non_negative",
        ),
        sa.CheckConstraint(
            "retention_versions IS NULL OR retention_versions >= 1",
            name="retention_at_least_one",
        ),
    )

    op.create_table(
        "membership",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("invited_by", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_membership"),
        # One role per user per workspace: two rows would make "what may they
        # do?" a question with two answers.
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_id_workspace_id"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_user.id"], name="fk_membership_user_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name="fk_membership_workspace_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["invited_by"], ["app_user.id"], name="fk_membership_invited_by", ondelete="SET NULL"
        ),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="role"),
    )

    op.create_table(
        "project",
        sa.Column("id", UUID, nullable=False),
        sa.Column("workspace_id", UUID, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_project"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspace.id"], name="fk_project_workspace_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_project_workspace_id", "project", ["workspace_id"])


# ------------------------------------------------------------------- data ----


def _create_data_tables() -> None:
    op.create_table(
        "dataset",
        sa.Column("id", UUID, nullable=False),
        sa.Column("project_id", UUID, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_dataset"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["project.id"], name="fk_dataset_project_id", ondelete="CASCADE"
        ),
    )
    op.create_index("ix_dataset_project_id", "dataset", ["project_id"])

    op.create_table(
        "dataset_version",
        sa.Column("id", UUID, nullable=False),
        sa.Column("dataset_id", UUID, nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("parquet_uri", sa.Text, nullable=False),
        sa.Column("row_count", sa.BigInteger, nullable=False),
        sa.Column("column_count", sa.Integer, nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("ingested_at", TS, nullable=False),
        sa.Column("ingested_by", UUID, nullable=False),
        sa.Column("ingest_options", pg.JSONB, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id", name="pk_dataset_version"),
        sa.UniqueConstraint(
            "dataset_id", "version_no", name="uq_dataset_version_dataset_id_version_no"
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"], ["dataset.id"], name="fk_dataset_version_dataset_id", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["ingested_by"],
            ["app_user.id"],
            name="fk_dataset_version_ingested_by",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version_no >= 1", name="version_no_positive"),
        sa.CheckConstraint(
            "row_count >= 0 AND column_count >= 0 AND byte_size >= 0",
            name="counts_non_negative",
        ),
    )
    op.create_index("ix_dataset_version_content_hash", "dataset_version", ["content_hash"])

    op.create_table(
        "source_file",
        sa.Column("id", UUID, nullable=False),
        sa.Column("dataset_version_id", UUID, nullable=False),
        sa.Column("original_filename", sa.Text, nullable=False),
        sa.Column("mime_detected", sa.Text, nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("storage_uri", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_source_file"),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_source_file_dataset_version_id",
            ondelete="CASCADE",
        ),
    )

    op.create_table(
        "schema_contract",
        sa.Column("id", UUID, nullable=False),
        sa.Column("dataset_version_id", UUID, nullable=False),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("columns", pg.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("created_by", UUID, nullable=True),
        sa.Column("derived_from", UUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_schema_contract"),
        sa.UniqueConstraint(
            "dataset_version_id",
            "version_no",
            name="uq_schema_contract_dataset_version_id_version_no",
        ),
        sa.ForeignKeyConstraint(
            ["dataset_version_id"],
            ["dataset_version.id"],
            name="fk_schema_contract_dataset_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["app_user.id"],
            name="fk_schema_contract_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["derived_from"],
            ["schema_contract.id"],
            name="fk_schema_contract_derived_from",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("version_no >= 1", name="version_no_positive"),
        # Version 1 is pure auto-detection; every later version must record what
        # it corrects, or "why is this column text now?" becomes unanswerable.
        sa.CheckConstraint(
            "(version_no = 1 AND derived_from IS NULL)"
            " OR (version_no > 1 AND derived_from IS NOT NULL)",
            name="derivation_matches_version",
        ),
    )


# ------------------------------------------------------------------ audit ----


def _create_audit_tables() -> None:
    op.create_table(
        "audit_event",
        sa.Column("id", UUID, nullable=False),
        sa.Column("action", sa.Text, nullable=False),
        sa.Column("at", TS, nullable=False),
        # Both nullable on purpose: a failed login has no workspace and often no
        # identifiable user, and that is precisely the event worth keeping.
        sa.Column("workspace_id", UUID, nullable=True),
        sa.Column("actor_user_id", UUID, nullable=True),
        sa.Column("target_type", sa.Text, nullable=True),
        sa.Column("target_id", UUID, nullable=True),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("metadata", pg.JSONB, nullable=False, server_default="{}"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_event"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspace.id"],
            name="fk_audit_event_workspace_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["app_user.id"],
            name="fk_audit_event_actor_user_id",
            ondelete="SET NULL",
        ),
    )
    op.create_index("ix_audit_event_workspace_id_at", "audit_event", ["workspace_id", "at"])
    op.create_index("ix_audit_event_actor_user_id_at", "audit_event", ["actor_user_id", "at"])

    # Login throttling in Postgres rather than Redis (§13.2, §19.2): one fewer
    # service to operate, for one counter, at fewer than 50 users.
    op.create_table(
        "login_attempt",
        sa.Column("id", UUID, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("ip", sa.Text, nullable=True),
        sa.Column("at", TS, nullable=False),
        sa.Column("succeeded", sa.Boolean, nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_login_attempt"),
    )
    op.create_index("ix_login_attempt_email_at", "login_attempt", ["email", "at"])
    op.create_index("ix_login_attempt_ip_at", "login_attempt", ["ip", "at"])


# ------------------------------------------------- immutability & grants ----


def _install_immutability_guards() -> None:
    """INV-2, INV-3 and §13.7, enforced where no application code can route around it.

    A repository that simply offers no update method is discipline, and §13.3
    already rejected discipline as a mechanism. These triggers fire for every
    role, including the one running migrations.
    """
    op.execute(
        """
        CREATE OR REPLACE FUNCTION datacanvas_reject_update() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'relation % is immutable: corrections create a new version '
                '(DESIGN.md INV-2/INV-3)', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION datacanvas_reject_change() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'relation % is append-only (DESIGN.md §13.7)', TG_TABLE_NAME
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )

    for table in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_immutable BEFORE UPDATE ON {table} "
            f"FOR EACH ROW EXECUTE FUNCTION datacanvas_reject_update()"
        )

    # Deletion stays allowed for the immutable tables — FR-B.6 requires real
    # deletion — and is blocked for the audit log, which must outlive the data
    # it describes.
    op.execute(
        "CREATE TRIGGER trg_audit_event_append_only BEFORE UPDATE OR DELETE ON audit_event "
        "FOR EACH ROW EXECUTE FUNCTION datacanvas_reject_change()"
    )


def _install_application_role() -> None:
    """Second line of defence for §13.7, and the reason to do it now.

    Separating the application's privileges from the schema owner's is a first
    migration decision or none at all: doing it once a deployment is running
    means rotating production credentials and hoping nobody is forgotten.

    NOLOGIN — this is a privilege group. The production login role is granted
    membership in it; in development the owner connects directly, and the
    triggers still apply.
    """
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")

    for table in _MUTABLE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")

    for table in _IMMUTABLE_TABLES:
        op.execute(f"GRANT SELECT, INSERT, DELETE ON {table} TO {APP_ROLE}")

    op.execute(f"GRANT SELECT, INSERT ON audit_event TO {APP_ROLE}")


def _seed_default_organization() -> None:
    """§9.2: the organization column exists, the feature does not.

    Every workspace points at this row until multi-org becomes real. Adding a
    tenancy column after a product has data is the migration nobody enjoys.
    """
    op.execute(
        f"""
        INSERT INTO organization (id, name, created_at)
        VALUES ('{DEFAULT_ORGANIZATION_ID}', 'Default', now())
        ON CONFLICT (id) DO NOTHING
        """
    )
