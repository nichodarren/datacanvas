"""Primary, then a different vendor, then local (D-076).

## What the layers are for, and it is not quality

The order is not best-to-worst. It is **independence**: a fallback behind the
same vendor as the primary shares its outage, its rate limit and its retirement
schedule, so it is not a fallback at all. Groq is second because it is a
different company, and OpenRouter is third because its free router picks a live
model that supports what was asked for — which is the answer to the failure
this project already had once, where a pinned model id simply stopped existing.

Local is last and is not really part of the same list: under privacy mode
`local` (§13.5) it is the **only** layer, and reaching a cloud provider would
be the policy violated rather than the outage survived. The cascade never
promotes a cloud client into a local-mode turn; the caller builds a cascade of
one.

## Why a rate limit is waited out rather than fallen through

Every other failure in `LLMUnavailable` is a reason to try somewhere else. A
rate limit is not: it **fixes itself**, and the provider says when. Since D-096
a turn is pinned to one vendor — a conversation belongs to a model, and its
tool-call transcript does not replay elsewhere — so once every key for that
vendor is limited there is nowhere to fall to. The choice is between waiting
the few seconds it asked for and throwing away the steps that already ran.

So the ladder is walked twice at most: once now, and once after the longest
wait any rung advertised. A wait is only taken when a provider **asked** for
it; nothing here sleeps on a guess, and the ceiling is small enough that a
turn stays a turn rather than becoming a background job.

## Why a refusal does not fall through

`LLMUnavailable` moves on. `LLMRefused` stops. A bad key, a model that does not
exist, a request the provider will reject identically next time — falling
through on any of those hides a misconfiguration behind a working fallback, and
the deployment runs permanently on its third choice with nothing on screen
saying so. That failure is quieter than an outage and lasts longer.
"""

from __future__ import annotations

import asyncio
import logging

from app.llm.contract import (
    Capabilities,
    LLMClient,
    LLMRefused,
    LLMUnavailable,
    Message,
    Proposal,
    ToolSpec,
)

log = logging.getLogger(__name__)

#: The longest this will wait for a rate limit to clear, in seconds.
#:
#: Chosen against the caller rather than against the provider: `/ask` is a
#: request somebody is watching, and a minute of silence reads as a hang. Past
#: this the honest answer is to say the keys are busy and let them ask again.
MAX_RETRY_WAIT = 20.0


class Cascade:
    """Several clients, tried in order, presenting as one."""

    def __init__(self, clients: tuple[LLMClient, ...]) -> None:
        if not clients:
            raise LLMRefused("a cascade needs at least one provider")
        self._clients = clients

    @property
    def clients(self) -> tuple[LLMClient, ...]:
        return self._clients

    @property
    def provider(self) -> str:
        return self._clients[0].provider

    @property
    def model(self) -> str:
        return self._clients[0].model

    @property
    def capabilities(self) -> Capabilities:
        """The **intersection**, not the first rung's.

        A cascade can answer from any rung, so what it can promise is what every
        rung can do. Reporting the primary's would let a deployment whose
        fallback cannot call tools believe it can, and discover otherwise on the
        day the primary is down — which is the day nobody is watching.
        """
        return Capabilities(
            function_calling=all(c.capabilities.function_calling for c in self._clients),
            structured_output=all(c.capabilities.structured_output for c in self._clients),
            context_tokens=min(c.capabilities.context_tokens for c in self._clients),
        )

    @property
    def identity(self) -> str:
        return self._clients[0].identity

    def pin(self, identity: str) -> LLMClient:
        """The rung that answered — **and every other account behind it**.

        `pin` exists because a conversation belongs to one *model*: replaying
        one vendor's tool-call transcript at another vendor breaks, and both
        Gemini and Groq have refused exactly that (see `LLMClient.pin`).

        **A different account of the same vendor is not another vendor.** Same
        model, same renderer, same validation; only the quota differs. So this
        returns the rung that answered followed by its siblings, and a rate
        limit at step three rolls onto the next key instead of ending the turn.
        That is the whole reason for configuring more than one account.

        Falls back to the whole cascade when the name is not one of its rungs,
        because a caller that cannot pin should still be able to ask. That case
        does not arise from a `Proposal`, whose identity this cascade set.
        """
        held = next((c for c in self._clients if c.identity == identity), None)
        if held is None:
            return self
        siblings = [c for c in self._clients if c.provider == held.provider and c is not held]
        return Cascade((held, *siblings)) if siblings else held

    async def propose(
        self,
        messages: tuple[Message, ...],
        tools: tuple[ToolSpec, ...] = (),
        *,
        temperature: float = 0.0,
        max_output_tokens: int = 2048,
    ) -> Proposal:
        for attempt in (1, 2):
            failures: list[str] = []
            waits: list[float | None] = []
            for client in self._clients:
                try:
                    return await client.propose(
                        messages,
                        tools,
                        temperature=temperature,
                        max_output_tokens=max_output_tokens,
                    )
                except LLMUnavailable as cause:
                    # Logged at warning rather than swallowed: a cascade that
                    # ran on its fallback for a month with nothing in the log
                    # is a bill, a latency change and a quality change nobody
                    # attributed.
                    log.warning("llm provider unavailable, falling through: %s", cause)
                    failures.append(str(cause))
                    waits.append(cause.retry_after)

            pause = self._pause(waits)
            if attempt == 1 and pause is not None:
                log.warning("every provider is rate limited; waiting %.1fs once", pause)
                await asyncio.sleep(pause)
                continue

            raise LLMUnavailable(self._why(failures, waits), retry_after=pause)

        raise LLMUnavailable("every provider was unavailable")  # pragma: no cover - unreachable

    @staticmethod
    def _pause(waits: list[float | None]) -> float | None:
        """The longest wait any rung asked for, if one is worth taking.

        Only an advertised wait counts. A rung that failed for some other
        reason contributes nothing and does not veto the wait either: two keys
        saying *six seconds* are still worth six seconds when a third is simply
        misconfigured.
        """
        asked = [wait for wait in waits if wait is not None and 0 < wait <= MAX_RETRY_WAIT]
        return max(asked) if asked else None

    def _why(self, failures: list[str], waits: list[float | None]) -> str:
        """One sentence, not one per rung.

        Ten rungs from six accounts (D-096) means the same rate limit is
        reported ten times, and a reader shown *groq is rate limiting this key;
        the free tier allows a few turns a minute* three times over learns to
        stop reading it. When every rung failed the same way, say it once and
        say how many.
        """
        if failures and all(wait is not None for wait in waits):
            vendors = " and ".join(sorted({client.provider for client in self._clients}))
            keys = "key" if len(failures) == 1 else f"all {len(failures)} keys"
            return (
                f"{vendors} is rate limiting {keys} right now; "
                f"the free tier allows a few turns a minute, so try again shortly"
            )

        seen: list[str] = []
        for failure in failures:
            if failure not in seen:
                seen.append(failure)
        return "; ".join(seen) or "every provider was unavailable"


__all__ = ["Cascade"]
