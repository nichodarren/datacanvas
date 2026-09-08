"""A dataset is its data: `dataset_version` folded into `dataset` (D-043).

What is removed is the ability for one dataset to have a **second** version.
What is kept — and had to be — is that the bytes never change once committed.

That distinction is the whole migration. §9.4 builds every fingerprint out of
the identity of the data a tool read, and INV-6 (*same fingerprint, same
result*) holds only while that identity means one set of bytes forever. Merging
the two entities keeps that; making `dataset` writable would have ended it. So
the `BEFORE UPDATE` trigger that guarded `dataset_version` since migration 0001
now guards `dataset`, and re-uploading a file makes a new dataset rather than a
new version of one.

## Why the data survives this time

Migration 0004 deleted rows rather than migrating them, because the tenant
prefix inside `parquet_uri` had to change and `dataset_version` was immutable —
rewriting an immutable value meant disabling the very trigger the project is
most careful about.

Nothing here needs that. The columns are **copied onto a table that has no
trigger yet**, and the trigger is created afterwards. `parquet_uri` is carried
over untouched, so files written under the old
`datasets/{id}/versions/{id}/` layout stay exactly where they are and keep
working; only new uploads use the shorter path. Two shapes coexist in storage,
which is recorded as a debt rather than papered over — the alternative is
moving files to satisfy a rule about tidiness.

## The one thing this discards

A dataset with several versions keeps its **latest**, and the rest become
orphaned files. Measured before writing this: every dataset in existence has
exactly one version, so the branch never runs. It is written down because
"never runs" is a claim about today's data, not about the code.

## A debt that closes here

`dataset_version.ingested_by` was `ON DELETE RESTRICT`, which made an account
that had ever uploaded anything undeletable — the deadlock recorded against
NFR-PRIV.3. The column does not come across: since D-039 made the account the
tenant, the uploader and the owner are always the same person, so it was
`owner_id` under another name. `dataset.owner_id` cascades. Who did what is
still in `audit_event`, which holds no foreign keys precisely so that it can
outlive what it describes (D-023).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"


def upgrade() -> None:
    # --- 1. widen `dataset` -------------------------------------------------
    #
    # Nullable to begin with, because the rows that exist have no values for
    # them yet. Tightened at the end, once they do.
    op.add_column("dataset", sa.Column("content_hash", sa.Text, nullable=True))
    op.add_column("dataset", sa.Column("parquet_uri", sa.Text, nullable=True))
    op.add_column("dataset", sa.Column("row_count", sa.BigInteger, nullable=True))
    op.add_column("dataset", sa.Column("column_count", sa.Integer, nullable=True))
    op.add_column("dataset", sa.Column("byte_size", sa.BigInteger, nullable=True))
    op.add_column(
        "dataset",
        sa.Column("ingest_options", pg.JSONB, nullable=False, server_default="{}"),
    )

    # --- 2. carry the newest version onto it --------------------------------
    #
    # `DISTINCT ON` is Postgres-specific and §10.3 allows that where the
    # alternative is materially worse; a correlated subquery per column would be
    # four scans of the same table to answer one question.
    #
    # This runs while `dataset` still has no immutability trigger. That ordering
    # is the reason the data can be kept at all, and it is why the trigger is
    # created in step 5 rather than alongside the columns.
    op.execute(
        sa.text("""
        UPDATE dataset AS d
        SET content_hash = v.content_hash,
            parquet_uri  = v.parquet_uri,
            row_count    = v.row_count,
            column_count = v.column_count,
            byte_size    = v.byte_size,
            ingest_options = v.ingest_options
        FROM (
            SELECT DISTINCT ON (dataset_id)
                   dataset_id, content_hash, parquet_uri, row_count,
                   column_count, byte_size, ingest_options
            FROM dataset_version
            ORDER BY dataset_id, version_no DESC
        ) AS v
        WHERE v.dataset_id = d.id
        """)
    )

    # A dataset with no version at all cannot become a dataset that *is* its
    # data. There is nothing to carry over and nothing to point at, so the row
    # goes — it was already unopenable, and the UI drew it as `No version`.
    op.execute(sa.text("DELETE FROM dataset WHERE parquet_uri IS NULL"))

    for column, type_ in (
        ("content_hash", sa.Text),
        ("parquet_uri", sa.Text),
        ("row_count", sa.BigInteger),
        ("column_count", sa.Integer),
        ("byte_size", sa.BigInteger),
    ):
        op.alter_column("dataset", column, existing_type=type_, nullable=False)

    op.create_check_constraint(
        "counts_non_negative",
        "dataset",
        "row_count >= 0 AND column_count >= 0 AND byte_size >= 0",
    )
    op.create_index("ix_dataset_content_hash", "dataset", ["content_hash"])

    # --- 3. re-point everything that named a version ------------------------
    #
    # `source_file`, `schema_contract` and `computation` all hung off
    # `dataset_version`. Each keeps its rows: the id it holds is replaced by the
    # dataset id of the version it pointed at, so a contract corrected last week
    # still describes the same bytes it described then.
    #
    # **Two of the three are rebuilt rather than updated, and that is the
    # interesting part.** `schema_contract` and `computation` carry `BEFORE
    # UPDATE` triggers (INV-3, INV-6). The first draft of this migration ran an
    # `UPDATE` and was refused by them — correctly. The move available at that
    # point is to disable the trigger for the duration, which is the one move
    # this project does not make: a guarantee suspended during the exact
    # operation most likely to break it is not a guarantee.
    #
    # So those two are copied into a new table and swapped. `INSERT` is not
    # `UPDATE`; the trigger never fires, and it never stops being armed either.
    # `source_file` has no trigger and takes the plain path.

    op.add_column("source_file", sa.Column("dataset_id_new", UUID, nullable=True))
    op.execute(
        sa.text("""
        UPDATE source_file AS t
        SET dataset_id_new = v.dataset_id
        FROM dataset_version AS v
        WHERE v.id = t.dataset_version_id
        """)
    )
    op.execute(sa.text("DELETE FROM source_file WHERE dataset_id_new IS NULL"))
    # Dropped by name rather than left to fall with the column. A cascading
    # drop emits no DDL of its own, so a reader of the migration script — and
    # `test_migration_matches_metadata.py`, which is one — would still see the
    # constraint as standing.
    op.drop_constraint("fk_source_file_dataset_version_id", "source_file")
    op.drop_column("source_file", "dataset_version_id")
    op.alter_column("source_file", "dataset_id_new", new_column_name="dataset_id", nullable=False)
    op.create_foreign_key(
        "fk_source_file_dataset_id",
        "source_file",
        "dataset",
        ["dataset_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # A row whose version was not the newest would now point at a dataset whose
    # bytes are a different version's, so it is not carried over. A contract or
    # a cached computation describing bytes it never read is worse than its
    # absence, and §9.4 has no way to tell the difference.
    latest = """
        v.id = (
            SELECT id FROM dataset_version
            WHERE dataset_id = v.dataset_id
            ORDER BY version_no DESC LIMIT 1
        )
    """

    # Renaming a table does not rename what it owns, and the naming convention
    # derives every constraint name from the table — so the replacement would
    # collide with the original's `pk_schema_contract` before a row was copied.
    # The old names step aside first.
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_schema_contract_immutable ON schema_contract"))
    op.rename_table("schema_contract", "schema_contract_old")
    for name in (
        "pk_schema_contract",
        "uq_schema_contract_dataset_version_id_version_no",
        "ck_schema_contract_version_no_positive",
        "ck_schema_contract_derivation_matches_version",
        "fk_schema_contract_dataset_version_id",
        "fk_schema_contract_created_by",
        "fk_schema_contract_derived_from",
    ):
        op.execute(
            sa.text(f"ALTER TABLE schema_contract_old RENAME CONSTRAINT {name} TO {name}_old")
        )
    op.create_table(
        "schema_contract",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "dataset_id", UUID, sa.ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("version_no", sa.Integer, nullable=False),
        sa.Column("columns", pg.JSONB, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("created_by", UUID, sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("derived_from", UUID, sa.ForeignKey("schema_contract.id", ondelete="SET NULL")),
        sa.UniqueConstraint(
            "dataset_id", "version_no", name="uq_schema_contract_dataset_id_version_no"
        ),
        sa.CheckConstraint("version_no >= 1", name="version_no_positive"),
        # Version 1 is pure auto-detection and derives from nothing; every later
        # version must say what it corrects (INV-3, mirrored from the domain).
        sa.CheckConstraint(
            "(version_no = 1 AND derived_from IS NULL)"
            " OR (version_no > 1 AND derived_from IS NOT NULL)",
            name="derivation_matches_version",
        ),
    )
    op.execute(
        sa.text(f"""
        INSERT INTO schema_contract
            (id, dataset_id, version_no, columns, created_at, created_by, derived_from)
        SELECT c.id, v.dataset_id, c.version_no, c.columns, c.created_at, c.created_by,
               c.derived_from
        FROM schema_contract_old AS c
        JOIN dataset_version AS v ON v.id = c.dataset_version_id
        WHERE {latest}
        """)
    )
    # `schema_contract_old` cannot go yet: `computation` still has a foreign key
    # into it, and dropping the table it points at is refused. It goes after
    # `computation_old` does, below.

    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_computation_immutable ON computation"))
    op.rename_table("computation", "computation_old")
    for name in (
        "pk_computation",
        "uq_computation_fingerprint",
        "ck_computation_duration_non_negative",
        "ck_computation_tool_version_starts_at_one",
        "fk_computation_computed_by",
        "fk_computation_dataset_version_id",
        "fk_computation_schema_contract_id",
    ):
        op.execute(sa.text(f"ALTER TABLE computation_old RENAME CONSTRAINT {name} TO {name}_old"))
    op.execute(
        sa.text("ALTER INDEX ix_computation_dataset_version_id RENAME TO ix_computation_dvid_old")
    )
    op.create_table(
        "computation",
        sa.Column("id", UUID, primary_key=True),
        sa.Column("fingerprint", sa.Text, nullable=False, unique=True),
        sa.Column("tool_name", sa.Text, nullable=False),
        sa.Column("tool_version", sa.Integer, nullable=False),
        sa.Column("args", pg.JSONB, nullable=False),
        sa.Column(
            "dataset_id", UUID, sa.ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
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
        sa.CheckConstraint("duration_ms >= 0", name="duration_non_negative"),
        sa.CheckConstraint("tool_version >= 1", name="tool_version_starts_at_one"),
        sa.Index("ix_computation_dataset_id", "dataset_id"),
    )
    # Only computations whose contract survived: `schema_contract_id` is a
    # foreign key, and §9.4 folds it into the fingerprint. A result whose
    # contract is gone cannot be explained, which is the whole point of storing
    # one (INV-5).
    op.execute(
        sa.text(f"""
        INSERT INTO computation
            (id, fingerprint, tool_name, tool_version, args, dataset_id, schema_contract_id,
             parents, result, computed_at, computed_by, duration_ms)
        SELECT c.id, c.fingerprint, c.tool_name, c.tool_version, c.args, v.dataset_id,
               c.schema_contract_id, c.parents, c.result, c.computed_at, c.computed_by,
               c.duration_ms
        FROM computation_old AS c
        JOIN dataset_version AS v ON v.id = c.dataset_version_id
        JOIN schema_contract AS sc ON sc.id = c.schema_contract_id
        WHERE {latest}
        """)
    )
    op.drop_table("computation_old")
    op.drop_table("schema_contract_old")

    # Re-arm both, and re-grant. A rebuilt table is a new table: it has neither
    # the trigger nor the privileges of the one it replaced, and forgetting
    # either is silent.
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_schema_contract_immutable BEFORE UPDATE ON schema_contract"
            " FOR EACH ROW EXECUTE FUNCTION datacanvas_reject_update()"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_computation_immutable BEFORE UPDATE ON computation"
            " FOR EACH ROW EXECUTE FUNCTION computation_is_immutable()"
        )
    )
    op.execute(sa.text(f"GRANT SELECT, INSERT, DELETE ON schema_contract TO {APP_ROLE}"))
    op.execute(sa.text(f"GRANT SELECT, INSERT, DELETE ON computation TO {APP_ROLE}"))

    # --- 4. the old table goes ----------------------------------------------
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_dataset_version_immutable ON dataset_version"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS dataset_version_is_immutable()"))
    op.drop_table("dataset_version")

    # --- 5. and `dataset` inherits INV-2 ------------------------------------
    #
    # Last, deliberately: everything above is an UPDATE on `dataset`, and this
    # is what makes those impossible from here on.
    op.execute(
        sa.text("""
        CREATE OR REPLACE FUNCTION dataset_is_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION
                'dataset is immutable (INV-2): its bytes are what every '
                'fingerprint in §9.4 is built from. Create a new dataset.';
        END;
        $$ LANGUAGE plpgsql;
        """)
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER trg_dataset_immutable BEFORE UPDATE ON dataset"
            " FOR EACH ROW EXECUTE FUNCTION dataset_is_immutable()"
        )
    )

    # The app may no longer UPDATE a dataset. It never needed to; now it cannot.
    op.execute(sa.text(f"REVOKE UPDATE ON dataset FROM {APP_ROLE}"))


def downgrade() -> None:
    """Structure only. The data does not come back, and says so.

    Splitting one row into a dataset and a version again is mechanical; deciding
    which of a merged history's versions each contract belonged to is not,
    because that history was collapsed on the way in. A downgrade therefore
    restores the shape and leaves it empty rather than inventing a lineage.
    """
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_dataset_immutable ON dataset"))
    op.execute(sa.text("DROP FUNCTION IF EXISTS dataset_is_immutable()"))
    op.execute(sa.text(f"GRANT UPDATE ON dataset TO {APP_ROLE}"))

    op.create_table(
        "dataset_version",
        sa.Column("id", UUID, primary_key=True),
        sa.Column(
            "dataset_id", UUID, sa.ForeignKey("dataset.id", ondelete="CASCADE"), nullable=False
        ),
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
        sa.CheckConstraint("version_no >= 1", name="ck_dataset_version_version_no_positive"),
        sa.CheckConstraint(
            "row_count >= 0 AND column_count >= 0 AND byte_size >= 0",
            name="ck_dataset_version_counts_non_negative",
        ),
        sa.Index("ix_dataset_version_content_hash", "content_hash"),
    )

    op.drop_index("ix_computation_dataset_id", table_name="computation")
    op.drop_constraint("uq_schema_contract_dataset_id_version_no", "schema_contract")
    for table in ("computation", "schema_contract", "source_file"):
        op.drop_constraint(f"fk_{table}_dataset_id", table)
        op.execute(sa.text(f"DELETE FROM {table}"))
        op.alter_column(table, "dataset_id", new_column_name="dataset_version_id")
        op.create_foreign_key(
            f"fk_{table}_dataset_version_id_dataset_version",
            table,
            "dataset_version",
            ["dataset_version_id"],
            ["id"],
            ondelete="CASCADE",
        )

    op.drop_index("ix_dataset_content_hash", table_name="dataset")
    op.drop_constraint("ck_dataset_counts_non_negative", "dataset")
    for column in (
        "ingest_options",
        "byte_size",
        "column_count",
        "row_count",
        "parquet_uri",
        "content_hash",
    ):
        op.drop_column("dataset", column)
