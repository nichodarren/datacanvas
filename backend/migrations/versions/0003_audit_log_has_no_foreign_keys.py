"""Drop the audit log's foreign keys.

Found by trying to delete a workspace. ``audit_event.workspace_id`` carried
``ON DELETE SET NULL``, and SET NULL is an UPDATE — which the append-only
trigger refuses. The result: **no workspace and no user that had ever produced
an audit event could be deleted at all.** That is a direct conflict with FR-B.6
(deletion must be real) and NFR-PRIV.3 (hard delete within 24 hours).

The fix is not to weaken the trigger. It is to notice that an audit log should
never have referenced the data it describes: the log has to outlive that data,
which is the entire reason it exists. ``target_id`` was already a plain UUID
for exactly this reason; ``workspace_id`` and ``actor_user_id`` were not, and
that was the inconsistency.

After this, those columns record *who and where this happened*, as of the
moment it happened. Resolving them to a current row is best-effort, and a
missing row is a fact about the past rather than a broken reference.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-28
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("fk_audit_event_workspace_id", "audit_event", type_="foreignkey")
    op.drop_constraint("fk_audit_event_actor_user_id", "audit_event", type_="foreignkey")


def downgrade() -> None:
    """Restores the constraints, and with them the deletion deadlock.

    Kept faithful rather than convenient: a downgrade that quietly improves on
    the schema it is restoring is a downgrade that cannot be trusted to
    reproduce the past.
    """
    op.create_foreign_key(
        "fk_audit_event_workspace_id",
        "audit_event",
        "workspace",
        ["workspace_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_audit_event_actor_user_id",
        "audit_event",
        "app_user",
        ["actor_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
