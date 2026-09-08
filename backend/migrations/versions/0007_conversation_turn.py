"""`conversation_turn`: what was asked, what came back, and what it produced.

§12.4 named this table and answered the question it exists for — *does the chat
need history?* — with **yes, but not a transcript**. The rule it drew is the one
this migration has to make possible and no wider:

> Transkrip tetap **disimpan** (`ConversationTurn`) untuk ditampilkan ke
> pengguna dan untuk debugging — tapi tidak dikirim ke model.

Nothing here is ever fed back to a planner. §12.4 gives three reasons and each
one is a defect this project has already paid for elsewhere: token cost that
grows linearly with a session, determinism poisoned by what was said earlier,
and a signal ratio that falls as the log gets longer.

## Two deviations from §9.2's sketch, and why

§9.2 sketches `id, analysis_id, role, content, llm_request_snapshot,
token_usage, provider, created_at`. Two of those do not fit what is being
built, and saying so is cheaper than discovering it after there are rows.

**1. A turn, not a message.** `role` + `content` is a chat transcript: one row
for the question, another for the answer. But the product owner's design makes
a log entry a **handle on its own results** — click it and the canvas focuses
the cards that entry produced. That only works if one row owns one question,
one answer, and the computations between them. Splitting it into two rows
would put the question in one and the artifacts in another, with nothing
joining them.

That is also what the code already produces: `run_turn` returns one `Turn`.
Storing it as two rows would take a shape the system has and break it apart to
match a sketch written before that shape existed.

**2. `dataset_id`, not `analysis_id`.** `Analysis` does not exist, and creating
it here would be a table with exactly one row per dataset and no reader —
which §20 warns is how tables rot. The product owner's answer settles it: the
analysis page is per dataset, so the history is per dataset. When `Analysis`
lands with the Run Log and the Findings Board, this column becomes
`analysis_id` and the migration is a real one, on rows that exist. That is
written down rather than left to be rediscovered.

`llm_request_snapshot` is **not** created. It serves FR-G.7, which is P1, and
the planner does not currently hand back the messages it sent — building the
column before the plumbing would be a column nothing writes.

## Not append-only, and that is deliberate

Unlike `audit_event`, this table has no immutability trigger. §13.7.1 settled
why: a prompt is free text and can hold anything a person typed, so the audit
log keeps only `sha256(prompt)` while **the sentence itself lives here, where
it can be deleted**. `ON DELETE CASCADE` on the dataset is what NFR-PRIV.3
depends on, and §13.5.4 states it outright: a conversation goes when its
dataset goes.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.TIMESTAMP(timezone=True)

APP_ROLE = "datacanvas_app"


def upgrade() -> None:
    op.create_table(
        "conversation_turn",
        sa.Column("id", UUID, primary_key=True),
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
        sa.Column(
            "asked_by", UUID, sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("asked_at", TS, nullable=False),
        # The sentence as typed. §13.7.1 keeps only its hash in the audit log
        # precisely so that the sentence can live somewhere deletable, and this
        # is that somewhere.
        sa.Column("question", sa.Text, nullable=False),
        # Null when the turn stopped before narrating — a budget, an outage, a
        # model that ran out of steps. The row is still worth keeping: a
        # question that could not be answered is the most useful kind to read
        # back (P6).
        sa.Column("narrative", sa.Text, nullable=True),
        sa.Column("grounded", sa.Boolean, nullable=False),
        sa.Column("stopped", sa.Text, nullable=True),
        # `[{ref, tool, args}, …]` — the computations this turn produced, in
        # order. **This is the link the product owner's design turns on**:
        # clicking a log entry focuses the cards it made, and `ref` is what
        # names them.
        #
        # JSONB rather than a join table because `step` does not exist yet and
        # a citation resolves to a `computation_id` (§12.5 names that id in its
        # own rule). When `step` lands this becomes a real relation.
        sa.Column("steps", pg.JSONB, nullable=False, server_default="[]"),
        # `[{kind, detail}, …]`. Kept because §12.5 rule 3 flags rather than
        # hides, and a flag that vanishes on reload has not flagged anything.
        sa.Column("complaints", pg.JSONB, nullable=False, server_default="[]"),
        sa.Column("tokens", sa.Integer, nullable=False, server_default="0"),
        # Which rung answered — `groq`, or `groq#2` (D-096). §12.8 accounts for
        # cost per rung, and two accounts of one vendor are two bills.
        sa.Column("provider", sa.Text, nullable=False, server_default=""),
        sa.CheckConstraint("tokens >= 0", name="tokens_non_negative"),
        sa.CheckConstraint("length(question) > 0", name="question_is_not_empty"),
        # The list is read one way only: newest first, for one dataset.
        sa.Index("ix_conversation_turn_dataset_asked", "dataset_id", "asked_at"),
    )

    # No immutability trigger, unlike `audit_event`. §13.7.1: the audit log is
    # append-only and therefore keeps only a hash of the prompt, while the
    # sentence lives here **so that it can be deleted** (NFR-PRIV.3).
    op.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON conversation_turn TO "{APP_ROLE}"')


def downgrade() -> None:
    op.drop_table("conversation_turn")
