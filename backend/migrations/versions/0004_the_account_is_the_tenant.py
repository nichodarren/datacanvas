"""The account is the tenant: organization, workspace, membership and project go.

DESIGN.md §15 loses FR-A.5. That is a **scope change**, taken deliberately by the
owner and justified in §0.6 — §0.3 rule 3 treats scope changes most strictly, and
this is one.

## What this actually changes, and what it does not

It is tempting to read this as "remove two grouping levels". It is not. Workspace
was the **tenancy boundary** — the only thing in the system that answered *whose
data is this*. Every authorization decision resolved to
``Principal.role_in(workspace_id)``, and every path on disk began
``workspaces/{id}/``.

So the boundary does not disappear; it moves to ``app_user.id``. The guarantees
that hung off it are all still here, keyed differently:

* ``dataset.owner_id`` replaces the ``dataset -> project -> workspace`` chain,
  so ownership is one join rather than three.
* ``storage://users/{owner_id}/...`` replaces ``storage://workspaces/{id}/...``,
  so §10.5's second line of defence — a traversal that gets past authorization
  still lands inside the tenant it started in — is untouched in kind.
* The cross-tenant sweep still runs, against ids in the path rather than against
  a workspace id in the path.

## Why the data is dropped rather than migrated

``dataset_version.parquet_uri`` holds the old ``workspaces/{id}/`` path, and
``dataset_version`` is **INV-2: never updated after commit**, enforced by a
``BEFORE UPDATE`` trigger from migration 0001. Rewriting those URIs in place
would mean dropping that trigger for the duration of a migration — punching a
hole in the invariant this project guards hardest, to relocate ten rows of test
data on one developer's machine.

The owner chose the wipe. It is stated here rather than discovered later: **this
migration destroys every dataset, version, schema contract and source file.**

``audit_event`` survives. Its rows are dropped a column, not deleted: ``ALTER
TABLE ... DROP COLUMN`` is DDL and does not fire the row-level append-only
trigger, so §13.7's *"the log outlives what it describes"* holds through this
change too — which is exactly the case it was written for.

## Why ``user_policy`` is created rather than ``workspace_policy`` deleted

``llm_privacy_mode`` is read by the Privacy Gate (§13.5) in Phase 5. Dropping the
table without moving the column would leave a Phase 5 requirement with nowhere to
read from, and it would be discovered in Phase 5. One row per user, same default,
same check constraints.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"

DEFAULT_ORGANIZATION_ID = "00000000-0000-4000-8000-000000000000"


def upgrade() -> None:
    # --- the data ---------------------------------------------------------
    # Order matters even with ON DELETE CASCADE: the append-only trigger on
    # `dataset_version` refuses UPDATE, not DELETE, so cascading deletes are
    # fine — but doing them explicitly, deepest first, means a failure here
    # names the table it failed on rather than a constraint five levels up.
    for table in ("schema_contract", "source_file", "dataset_version", "dataset"):
        op.execute(sa.text(f"DELETE FROM {table}"))

    # --- dataset belongs to a user ---------------------------------------
    op.add_column("dataset", sa.Column("owner_id", UUID, nullable=True))
    # Nullable first, then filled, then tightened — the standard three-step,
    # which here is trivially satisfied because the table was just emptied. It
    # is written out anyway: a migration that only works on an empty table is a
    # migration that fails the first time it meets a populated one.
    op.execute(
        sa.text(
            "UPDATE dataset SET owner_id = ("
            "  SELECT m.user_id FROM project p"
            "  JOIN membership m ON m.workspace_id = p.workspace_id AND m.role = 'owner'"
            "  WHERE p.id = dataset.project_id LIMIT 1"
            ") WHERE owner_id IS NULL"
        )
    )
    op.execute(sa.text("DELETE FROM dataset WHERE owner_id IS NULL"))
    op.alter_column("dataset", "owner_id", nullable=False)
    op.create_foreign_key(
        "fk_dataset_owner_id", "dataset", "app_user", ["owner_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_dataset_owner_id", "dataset", ["owner_id"])

    op.drop_index("ix_dataset_project_id", table_name="dataset")
    op.drop_constraint("fk_dataset_project_id", "dataset", type_="foreignkey")
    op.drop_column("dataset", "project_id")

    # --- the policy moves before its table is dropped ---------------------
    op.create_table(
        "user_policy",
        sa.Column(
            "user_id",
            UUID,
            sa.ForeignKey("app_user.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("llm_privacy_mode", sa.Text, nullable=False, server_default="balanced"),
        sa.Column("llm_monthly_token_budget", sa.BigInteger, nullable=True),
        sa.Column("allowed_providers", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("retention_versions", sa.Integer, nullable=True),
        sa.CheckConstraint(
            # The vocabulary is `PrivacyMode` in app/domain/enums.py. Written as
            # a literal because a migration must replay the schema as it was,
            # and importing the enum would let a later rename rewrite history.
            "llm_privacy_mode IN ('strict', 'balanced', 'full', 'local')",
            # The naming convention in tables.py prefixes this with
            # `ck_<table>_`, so the name given here must be the bare one or the
            # two sides end up with `ck_user_policy_ck_llm_privacy_mode`.
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
    # One row per user who had a workspace policy, carrying its settings across.
    # The owner of a personal workspace is the user it belonged to, and this
    # migration is the last moment that mapping exists.
    op.execute(
        sa.text(
            "INSERT INTO user_policy ("
            "  user_id, llm_privacy_mode, llm_monthly_token_budget,"
            "  allowed_providers, retention_versions"
            ") SELECT DISTINCT ON (m.user_id)"
            "  m.user_id, wp.llm_privacy_mode, wp.llm_monthly_token_budget,"
            "  wp.allowed_providers, wp.retention_versions"
            " FROM workspace_policy wp"
            " JOIN membership m ON m.workspace_id = wp.workspace_id AND m.role = 'owner'"
            " ORDER BY m.user_id, m.created_at"
        )
    )
    op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON user_policy TO {APP_ROLE}"))

    # --- the audit log keeps its rows and loses a column ------------------
    # DDL, so the append-only trigger does not fire. §13.7's promise that the
    # log outlives what it describes is precisely this case.
    #
    # The index is dropped by name first. Postgres would remove it anyway when
    # the column goes, but silently — and a migration whose rendered SQL does
    # not say what it did is a migration nothing downstream can compare against.
    op.drop_index("ix_audit_event_workspace_id_at", table_name="audit_event")
    op.drop_column("audit_event", "workspace_id")

    # --- and the tenancy tables go ---------------------------------------
    op.drop_table("project")
    op.drop_table("membership")
    op.drop_table("workspace_policy")
    op.drop_table("workspace")
    op.drop_table("organization")


def downgrade() -> None:
    """Restores the shape, and cannot restore the contents.

    Stated rather than papered over: the datasets `upgrade()` deleted are gone,
    and the workspace each surviving row belonged to is not recorded anywhere
    after this migration runs. So this rebuilds the tables and gives every user
    a fresh personal workspace — the same thing registration does — and does not
    pretend to reconstruct a history it does not have.
    """
    op.create_table(
        "organization",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.execute(
        sa.text(
            f"INSERT INTO organization (id, name) VALUES ('{DEFAULT_ORGANIZATION_ID}', 'Default')"
        )
    )

    op.create_table(
        "workspace",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "organization_id",
            UUID,
            sa.ForeignKey("organization.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "created_by", UUID, sa.ForeignKey("app_user.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "workspace_policy",
        sa.Column(
            "workspace_id",
            UUID,
            sa.ForeignKey("workspace.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("llm_privacy_mode", sa.Text, nullable=False, server_default="balanced"),
        sa.Column("llm_monthly_token_budget", sa.BigInteger, nullable=True),
        sa.Column("allowed_providers", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("retention_versions", sa.Integer, nullable=True),
        sa.CheckConstraint(
            # The vocabulary is `PrivacyMode` in app/domain/enums.py. Written as
            # a literal because a migration must replay the schema as it was,
            # and importing the enum would let a later rename rewrite history.
            "llm_privacy_mode IN ('strict', 'balanced', 'full', 'local')",
            # The naming convention in tables.py prefixes this with
            # `ck_<table>_`, so the name given here must be the bare one or the
            # two sides end up with `ck_user_policy_ck_llm_privacy_mode`.
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
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "user_id", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
        sa.Column(
            "invited_by", UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
        ),
        sa.UniqueConstraint("user_id", "workspace_id", name="uq_membership_user_id_workspace_id"),
        sa.CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="ck_role"),
    )
    op.create_table(
        "project",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "workspace_id", UUID, sa.ForeignKey("workspace.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_project_workspace_id", "project", ["workspace_id"])

    for table in ("workspace", "workspace_policy", "membership", "project", "organization"):
        op.execute(sa.text(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}"))

    # A personal workspace, an owner membership and one project per user — the
    # same three rows registration creates, because that is the only defensible
    # reconstruction available.
    op.execute(
        sa.text(
            "INSERT INTO workspace (id, organization_id, name, created_by, is_personal)"
            f" SELECT gen_random_uuid(), '{DEFAULT_ORGANIZATION_ID}', email, id, true"
            " FROM app_user"
        )
    )
    op.execute(
        sa.text(
            "INSERT INTO membership (id, user_id, workspace_id, role)"
            " SELECT gen_random_uuid(), w.created_by, w.id, 'owner' FROM workspace w"
        )
    )
    op.execute(sa.text("INSERT INTO workspace_policy (workspace_id) SELECT id FROM workspace"))
    op.execute(
        sa.text(
            "INSERT INTO project (id, workspace_id, name)"
            " SELECT gen_random_uuid(), id, 'First project' FROM workspace"
        )
    )

    op.add_column("audit_event", sa.Column("workspace_id", UUID, nullable=True))
    op.create_index("ix_audit_event_workspace_id_at", "audit_event", ["workspace_id", "at"])

    op.drop_index("ix_dataset_owner_id", table_name="dataset")
    op.drop_constraint("fk_dataset_owner_id", "dataset", type_="foreignkey")
    op.add_column("dataset", sa.Column("project_id", UUID, nullable=True))
    op.execute(
        sa.text(
            "UPDATE dataset SET project_id = ("
            "  SELECT p.id FROM project p"
            "  JOIN workspace w ON w.id = p.workspace_id"
            "  WHERE w.created_by = dataset.owner_id LIMIT 1"
            ")"
        )
    )
    op.execute(sa.text("DELETE FROM dataset WHERE project_id IS NULL"))
    op.alter_column("dataset", "project_id", nullable=False)
    op.create_foreign_key(
        "fk_dataset_project_id", "dataset", "project", ["project_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index("ix_dataset_project_id", "dataset", ["project_id"])
    op.drop_column("dataset", "owner_id")

    op.drop_table("user_policy")
