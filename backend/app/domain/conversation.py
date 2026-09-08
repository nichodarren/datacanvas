"""What was asked of a dataset, and what came back (§12.4).

## Stored to be read, never to be sent

§12.4 answers *does the copilot need history?* with **yes, but not a
transcript**, and this entity is the *yes*. Nothing here reaches a planner.
What a planner gets is `SessionState` — the schema digest, the last few steps,
pinned findings — assembled fresh each turn, so the context a model sees stays
almost constant however long a session runs.

Three reasons §12.4 gives for keeping the transcript out of the prompt, and
each one is a defect this project has already paid for somewhere else:

1. token cost grows linearly with the session;
2. determinism is poisoned — the same question answers differently depending on
   what was said before it, which is the thing P1 exists to remove;
3. the signal ratio falls as the log grows.

## A turn, not a message

§9.2 sketches `role` + `content`, which is a chat transcript: one row for the
question, one for the answer. This is one row for **both**, plus the
computations between them, and the reason is what a log entry is *for*:
clicking it focuses the cards that entry produced. Split across two rows, the
question would be in one and the artifacts in another with nothing joining
them.

It is also the shape the code already has — `run_turn` returns one `Turn`.

## Why it is deletable

`audit_event` is append-only and therefore keeps only `sha256(prompt)`
(§13.7.1). The sentence a person actually typed lives **here**, precisely
because here it can be deleted: a prompt is free text and can hold anything,
and NFR-PRIV.3 promises a hard delete. §13.5.4 says it plainly — a conversation
goes when its dataset goes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domain._checks import ensure_aware, ensure_non_empty
from app.domain.errors import InvariantViolation
from app.domain.ids import DatasetId, SchemaContractId, UserId


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    """One question, one answer, and the computations in between."""

    id: UUID
    dataset_id: DatasetId
    #: Which reading of the data the question was asked against. A turn asked
    #: before a type correction and one asked after are answers to different
    #: questions, and §9.4 already folds this id into every fingerprint below.
    schema_contract_id: SchemaContractId
    asked_by: UserId
    asked_at: datetime
    question: str

    #: `None` when the turn stopped before narrating — a budget, an outage, a
    #: model that ran out of steps. The row is still worth keeping: a question
    #: that could not be answered is the most useful kind to read back (P6).
    narrative: str | None = None
    grounded: bool = False
    stopped: str | None = None

    #: `[{ref, tool, args}, …]`, in the order they ran. **The link the log
    #: entry follows**: `ref` is a `computation_id`, and that is what names the
    #: cards this turn put on the canvas.
    steps: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    #: `[{kind, detail}, …]`. Kept because §12.5 rule 3 flags rather than hides,
    #: and a flag that disappears on reload has not flagged anything.
    complaints: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    tokens: int = 0
    #: Which rung answered — `groq`, or `groq#2` (D-096). §12.8 accounts per
    #: rung, and two accounts of one vendor are two bills.
    provider: str = ""
    #: Which model wrote the sentence. The rung names an account; this names
    #: what shaped the answer, and it is the question asked first when one
    #: looks wrong. Empty on rows written before it was recorded.
    model: str = ""

    def __post_init__(self) -> None:
        ensure_aware(self.asked_at, "asked_at")
        ensure_non_empty(self.question, "question")
        if self.tokens < 0:
            raise InvariantViolation(f"tokens cannot be negative, got {self.tokens}")
        if self.grounded and self.narrative is None:
            # Grounded means *every figure in this answer resolves*, and an
            # answer that was never written cannot have passed that. Letting
            # the pair through would put a green tick on an empty turn.
            raise InvariantViolation("a turn with no narrative cannot be grounded")


__all__ = ["ConversationTurn"]
