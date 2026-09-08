"""Reading and writing the conversation log (§12.4).

Two operations, and there is deliberately no third. Nothing updates a turn: it
records what happened, and what happened does not change. Nothing deletes one
either — the dataset's own delete cascades, which is what §13.5.4 promises and
NFR-PRIV.3 depends on.

**Every read is scoped to one dataset in the query**, not filtered after it.
The same rule the rest of §13.3.1 follows: a row that belongs to somebody else
comes back as *not found* rather than as *forbidden*, because a 403 confirms
the id exists.
"""

from __future__ import annotations

import uuid

import sqlalchemy as sa
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.conversation import ConversationTurn
from app.domain.ids import DatasetId, SchemaContractId, UserId
from app.repositories.tables import conversation_turn

#: How many turns the log shows. A page of history is a list somebody scans,
#: and past a hundred entries nobody scans it — they search, which is a
#: different feature and not one that exists.
MAX_TURNS = 100


def _to_turn(row: Row[tuple[object, ...]]) -> ConversationTurn:
    return ConversationTurn(
        id=row.id,
        dataset_id=DatasetId(row.dataset_id),
        schema_contract_id=SchemaContractId(row.schema_contract_id),
        asked_by=UserId(row.asked_by),
        asked_at=row.asked_at,
        question=row.question,
        narrative=row.narrative,
        grounded=row.grounded,
        stopped=row.stopped,
        steps=tuple(row.steps or ()),
        complaints=tuple(row.complaints or ()),
        tokens=row.tokens,
        provider=row.provider,
        model=row.model,
    )


class ConversationRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def record(self, turn: ConversationTurn) -> ConversationTurn:
        """Append one. Never updates — a turn records what happened."""
        await self._c.execute(
            sa.insert(conversation_turn).values(
                id=turn.id,
                dataset_id=turn.dataset_id,
                schema_contract_id=turn.schema_contract_id,
                asked_by=turn.asked_by,
                asked_at=turn.asked_at,
                question=turn.question,
                narrative=turn.narrative,
                grounded=turn.grounded,
                stopped=turn.stopped,
                steps=list(turn.steps),
                complaints=list(turn.complaints),
                tokens=turn.tokens,
                provider=turn.provider,
                model=turn.model,
            )
        )
        return turn

    async def forget(self, turn_id: uuid.UUID, dataset_id: DatasetId) -> bool:
        """Delete one turn, within one dataset. `True` if there was one.

        **The dataset is in the statement rather than checked after it**, so a
        turn belonging to somebody else is simply not matched — the same shape
        `within` uses, and the reason a caller gets *not found* rather than
        *forbidden* (§13.3.1).

        ⚠️ **The computations this turn named are not touched, and that is the
        design rather than an omission.** A `Computation` is identified by its
        fingerprint (§9.4) and shared by every turn that asked the same
        question of the same data; deleting one because a log entry was tidied
        away would empty a cache entry another turn still cites, and INV-5 says
        a displayed figure must resolve. What NFR-PRIV.3 asks to be removable
        is the **sentence** — the question and the narration in this row — and
        that is what goes. §13.7.1 keeps only `sha256(prompt)` in the audit log
        for the same reason, which is why this table has no immutability
        trigger while `computation` does.
        """
        done = await self._c.execute(
            sa.delete(conversation_turn).where(
                conversation_turn.c.id == turn_id,
                conversation_turn.c.dataset_id == dataset_id,
            )
        )
        return bool(done.rowcount)

    async def history(
        self, dataset_id: DatasetId, *, limit: int = MAX_TURNS
    ) -> tuple[ConversationTurn, ...]:
        """The log for one dataset, **newest first**.

        Newest first because that is the order it is read: the last thing asked
        is the thing on screen, and the list is scanned upward from it. The
        canvas keeps every turn's cards, so this list is the index into it
        rather than a replacement for it.
        """
        rows = (
            await self._c.execute(
                sa.select(conversation_turn)
                .where(conversation_turn.c.dataset_id == dataset_id)
                .order_by(conversation_turn.c.asked_at.desc(), conversation_turn.c.id.desc())
                .limit(limit)
            )
        ).all()
        return tuple(_to_turn(row) for row in rows)


__all__ = ["MAX_TURNS", "ConversationRepository"]
