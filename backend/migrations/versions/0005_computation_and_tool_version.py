"""The first two execution tables: `tool_version` and `computation`.

§20 says the execution tables belong to Phase 3 and that tables created before
anything uses them rot. This migration creates **two** of the five, and only
because `describe_dataset` uses both on the day they land.

`step`, `artifact`, `finding` and `conversation_turn` are deliberately still
absent. They belong to the Step executor, which does not exist, and creating
them now would be the rot §20 warns about.

## Why `computation` exists before `step`

INV-5 — *every number displayed comes from a referenceable Computation* — is
about the number, not about the DAG. The Profile tab shows numbers today. It
does not compose steps, branch, or run anything a user assembled, so it needs
the identity half of the execution model and none of the orchestration half.

When `step` arrives it will reference `computation`, not replace it: §9.2 already
has one Computation per Step, and this table is that table.

## Why the fingerprint is unique and the id is not the key

`fingerprint` carries a UNIQUE constraint because that is the whole caching
mechanism — the same question asked twice must find the first answer, and the
database is a better place to enforce that than a lookup somebody might forget.
The surrogate `id` stays because a 64-character hash is a poor foreign key and
because §9.2 names `computation_id` as the thing a result cites.

## Append-only, like the audit log and for a related reason

A Computation records what a tool returned for a given fingerprint. Updating one
would mean the same fingerprint answering differently at two points in time,
which is INV-6 broken in storage rather than in code. So the trigger refuses
UPDATE — DELETE stays allowed, because a cache must be evictable and NFR-PRIV.3
requires data to be really removable.

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"


def upgrade() -> None:
    op.create_table(
        "tool_version",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("tool_name", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("registered_at", TS, nullable=False),
        # INV-4: the version rises whenever a tool's output could change, so a
        # given (name, version) must describe exactly one behaviour forever.
        sa.UniqueConstraint("tool_name", "version", name="uq_tool_version_tool_name_version"),
        sa.CheckConstraint("version >= 1", name="version_starts_at_one"),
    )

    op.create_table(
        "computation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("fingerprint", sa.Text, nullable=False),
        sa.Column("tool_name", sa.Text, nullable=False),
        sa.Column("tool_version", sa.Integer, nullable=False),
        sa.Column("args", pg.JSONB, nullable=False),
        sa.Column(
            "dataset_version_id",
            UUID,
            sa.ForeignKey("dataset_version.id", ondelete="CASCADE"),
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
        # The cache, enforced by the database rather than by whoever writes the
        # next lookup.
        sa.UniqueConstraint("fingerprint", name="uq_computation_fingerprint"),
        sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
        sa.CheckConstraint("tool_version >= 1", name="tool_version_starts_at_one"),
        sa.Index("ix_computation_dataset_version_id", "dataset_version_id"),
    )

    # ON DELETE CASCADE above is what keeps FR-B.6 working: deleting a dataset
    # takes its versions, and its versions must take the computations derived
    # from them. A cached result that outlived its data is a number about
    # nothing that nobody can check.
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION computation_is_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'computation is immutable: the same fingerprint must always '
                'describe the same result (INV-6). Delete and recompute instead.';
        END;
        $$ LANGUAGE plpgsql;
        """)
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_computation_immutable BEFORE UPDATE ON computation"
            " FOR EACH ROW EXECUTE FUNCTION computation_is_immutable()"
        )
    )

    for table in ("tool_version", "computation"):
        op.execute(sa.text(f"GRANT SELECT, INSERT, DELETE ON {table} TO {APP_ROLE}"))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_computation_immutable ON computation"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS computation_is_immutable()"))
    op.drop_table("computation")
    op.drop_table("tool_version")
