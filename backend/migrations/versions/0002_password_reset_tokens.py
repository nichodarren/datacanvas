"""Password reset tokens (FR-A.6).

A separate table rather than columns on `app_user`, for two reasons. A user may
hold several outstanding requests (they clicked twice, or an old mail is still
in the inbox), and each needs its own expiry and single-use flag. And a used
token is kept rather than deleted: "this link was already used at 14:02" is a
better answer to a confused user than "invalid link".

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"


def upgrade() -> None:
    op.create_table(
        "password_reset_token",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        # SHA-256 hex, like a session token (§13.2).
        sa.Column("token_hash", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("used_at", TS, nullable=True),
        sa.Column("requested_ip", sa.Text, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_token"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_token_token_hash"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_user.id"],
            name="fk_password_reset_token_user_id",
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "ix_password_reset_token_user_id_used_at",
        "password_reset_token",
        ["user_id", "used_at"],
    )

    # The grant has to be issued per table; ALL TABLES in migration 0001 only
    # covered the tables that existed then. Forgetting this is how a deployment
    # discovers at runtime that the application cannot write to a new table.
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON password_reset_token TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE ALL ON password_reset_token FROM {APP_ROLE}")
    op.drop_table("password_reset_token")
