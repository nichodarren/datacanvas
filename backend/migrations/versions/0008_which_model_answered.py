"""`conversation_turn.model`: which model wrote the sentence on screen.

`provider` already records **which rung** answered — `gemini`, or `gemini#2`
when several accounts of one vendor are configured (D-096) — because §12.8
accounts per rung and two accounts of one vendor are two bills. That is the
right key for a cost report and the wrong one for a reader: `gemini#2` names
an account, not a model, and the account is not what shaped the answer.

So this adds the model beside it. Two columns rather than one parsed string,
because they answer different questions and change on different schedules: a
rung is configuration and moves when somebody edits `.env`, while a model id
moves when a vendor retires one — the failure this project has already had
once, with a pinned id that simply stopped existing.

## Why it is worth a migration rather than a display trick

The alternative was to show the vendor half of the rung and leave the version
out. But *which model answered* is the question that gets asked after an answer
looks wrong, and a history that cannot answer it for last week's turns cannot
answer it at all. Rows written before this exist with an empty string, which is
honest — nobody recorded it then.

Nullable is not used: an empty string means *not recorded*, and NULL would mean
the same thing with one more state to handle at every read.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_turn",
        sa.Column("model", sa.Text, nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("conversation_turn", "model")
