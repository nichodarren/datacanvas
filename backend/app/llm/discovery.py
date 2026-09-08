"""Which tools the model is even shown (§12.2).

## What v1 did, and why it failed invisibly

v1 matched keywords against exact phrases. *"how is age spread out?"* matched
none of `distribution`, `histogram`, `plot`, so the visualisation tool was never
offered and the system failed **for a reason the user could not see**. A
reasonable paraphrase is the normal case, not an edge one, and the approach does
not survive past about forty tools.

## Three stages, and the first one is free

```
Stage 0  eligibility     deterministic, no model, no cost
         Drop tools whose `applies_to(contract)` is false for this dataset.
         No datetime column, no time-based tool. Ever.

Stage 1  category         one cheap call, ~200 tokens
         The request plus six one-line category descriptions.
         Answers with one or two categories.

Stage 2  the shortlist    no call
         Full specs for the tools in those categories, plus a small core set
         that is always present as a safety net.
```

The cost is one extra round trip. The alternative considered and deferred was
embedding retrieval over tool descriptions: cheaper per turn, and it needs
embedding infrastructure and is harder to debug. §12.2 says start here and move
if latency becomes a real problem — and the category decision is **recorded**,
so a wrong shortlist can be read afterwards rather than guessed at.

## Why the core set exists

A category choice can be wrong. When it is, a shortlist with nothing familiar
in it turns a bad guess into a dead turn — the model has no way back. The core
set means the two tools that answer *what is in this data* are always on the
table, so the worst case is a turn that under-answers rather than one that
cannot answer.

## Language

The interface is English (OQ-11). Two-stage selection happens to be
language-agnostic, so an Indonesian prompt will **probably** work — that is a
bonus, not a promise, and §12.2 is explicit that it is untested and unsupported.
What is guaranteed is that a non-English prompt never produces a silently wrong
result: a category choice this stage cannot make comes back empty, and an empty
choice falls back to the core set rather than to a guess.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.domain.data import SchemaContract
from app.llm.contract import LLMClient, LLMError, Message, ToolSpec
from app.tools.contract import Registration, ToolRegistry
from app.tools.parameters import json_schema

log = logging.getLogger(__name__)

#: §11.4.2 — six questions, not six shelves. The wording is what the model
#: actually reads in stage 1, so each line is written to be chosen *against*
#: the others rather than to be accurate in isolation.
CATEGORIES: dict[str, str] = {
    "shape": "Pick out the rows or columns I mean: select, filter, sort, limit, sample.",
    "compute": "Make a new number: derive a column, aggregate, group, bin.",
    "profiling": "What is in this data: describe it, profile a column, count distinct values.",
    "quality": "What might be wrong with it: missing values, duplicates, outliers, mixed types.",
    "relationship": "How two things relate: cross-tabulate, correlate.",
    "visual": "Draw it: a chart of a table that already exists.",
}

#: Always offered, whatever stage 1 decides.
#:
#: The first two answer *what is in this data*, which is the question a reader
#: falls back to when the shortlist missed — and neither can produce a wrong
#: number, only an unhelpful one.
#:
#: ⚠️ **`filter_rows` was added 2026-08-27 after measuring, and it corrects a
#: conclusion recorded the day before.** Three of five questions that need a
#: subset — *for passengers under 18, what is the survival rate by class* —
#: routed to `compute` alone, which is **right**: the intent is a rate per
#: group. But the shortlist then held no way to say *under 18*, so the model
#: reached for `derive_column` and burned six steps. That was written up as
#: evidence of constraint decay (R-18) and it was not: the model was doing the
#: best it could with a menu that was missing half the answer.
#:
#: **Filtering is a modifier on other questions; the rest of `shape` are
#: questions in their own right.** Stage 1 routes *sort the rows by fare* and
#: *give me a random sample* correctly on their own — measured 4 of 4 — so
#: only this one needs to be permanently visible. One tool, not five.
CORE_SET: frozenset[str] = frozenset({"describe_dataset", "profile_column", "filter_rows"})

#: Output budget for stage 1, and it is **not** the ~200 tokens §12.2 names.
#:
#: That figure is the *input*: six lines plus the question, measured at 240.
#: The output cap was 32 on the reasoning that two category names are four
#: tokens — and every question fell back, live, with nothing raised. A
#: reasoning model spends its output budget thinking before it writes, so
#: `openai/gpt-oss-120b` returned **an empty `content` and a full 32 tokens
#: used**: a truncation that looks exactly like a model with no opinion.
#:
#: ⚠️ The fallback hid it. Every one of six questions came back with the core
#: set and the system looked like it was working. A degradation graceful enough
#: to be invisible is a degradation nobody investigates — which is why
#: `Shortlist.fell_back` is recorded rather than merely handled.
#:
#: 256 leaves room to think: the same call answers `profiling, visual` in 123.
_CATEGORY_TOKENS = 256

_SYSTEM = (
    "You route a data question to the kinds of tool that could answer it. "
    "Reply with category names from the list, comma separated, at most two, "
    "and nothing else. If none of them fit, reply with the single word: none."
)


@dataclass(frozen=True, slots=True)
class Shortlist:
    """What the model will be shown, and the record of how it was chosen.

    The trail is not decoration. §12.2 lists debuggability as the reason to
    prefer this over embedding retrieval, and a shortlist nobody can explain is
    the v1 failure in a new shape: the wrong tools offered for a reason nobody
    can see.
    """

    tools: tuple[ToolSpec, ...]
    categories: tuple[str, ...]
    #: Tools dropped by stage 0, with the reason. Feeds FR-E.3.
    ineligible: tuple[str, ...] = ()
    #: True when stage 1 could not choose and the core set carried the turn.
    fell_back: bool = False
    tokens: int = 0
    names: tuple[str, ...] = field(default_factory=tuple)


def eligible(registry: ToolRegistry, contract: SchemaContract) -> tuple[Registration, ...]:
    """Stage 0. Deterministic, free, and impossible for a model to get wrong."""
    return tuple(
        registration for registration in registry.all() if registration.tool.applies_to(contract)
    )


def spec_for(registration: Registration) -> ToolSpec:
    """One tool as the model may see it — tier 3 withheld (D-019)."""
    tool = registration.tool
    return ToolSpec(
        name=tool.name,
        description=tool.summary,
        parameters=json_schema(tool.parameters, for_llm=True),
    )


async def choose_categories(client: LLMClient, question: str) -> tuple[tuple[str, ...], int]:
    """Stage 1. One small call, or nothing.

    Returns the categories it recognised and what the call cost. **Never
    raises**: a discovery layer that could fail the turn would make an outage in
    the cheapest call take down the whole planner, when falling back to the core
    set answers less rather than not at all.
    """
    listing = "\n".join(f"- {name}: {line}" for name, line in CATEGORIES.items())
    messages = (
        Message(role="system", content=_SYSTEM),
        Message(role="user", content=f"{listing}\n\nQuestion: {question}"),
    )

    try:
        proposal = await client.propose(
            messages, (), temperature=0.0, max_output_tokens=_CATEGORY_TOKENS
        )
    except LLMError as cause:
        log.warning("category selection unavailable, falling back to the core set: %s", cause)
        return ((), 0)

    said = (proposal.text or "").lower()
    # Read by containment rather than by parsing: a model that answers
    # `profiling, quality` and one that answers `I would use profiling` have
    # chosen the same thing, and refusing the second is refusing a right answer
    # over its punctuation.
    found = tuple(name for name in CATEGORIES if name in said)
    return (found[:2], proposal.spent)


async def discover(
    client: LLMClient,
    registry: ToolRegistry,
    contract: SchemaContract,
    question: str,
) -> Shortlist:
    """The three stages, end to end.

    ⚠️ **Nothing calls this today** (D-094, 2026-08-27). The planner offers
    every eligible tool and makes no category call, on the product owner's
    decision: at seventeen tools the whole catalogue fits in a prompt, so the
    reason §12.2 gives for staging does not apply yet.

    Kept whole and kept tested, because the reason will apply again — §12.2's
    argument is about a catalogue too large for a prompt, and catalogues grow.
    `eligible()` and `spec_for()` below are still very much in use; it is
    **stage 1**, the model call, that is switched off.
    """
    live = eligible(registry, contract)
    # By name rather than by identity: `Registration` holds a tool instance, and
    # comparing dataclasses that wrap unhashable objects is a correctness
    # question nobody should have to think about to read this line.
    kept = {registration.tool.name for registration in live}
    dropped = tuple(
        registration.tool.name
        for registration in registry.all()
        if registration.tool.name not in kept
    )

    categories, tokens = await choose_categories(client, question)
    wanted = set(categories)
    chosen = tuple(
        registration
        for registration in live
        if registration.category in wanted or registration.tool.name in CORE_SET
    )

    # An empty stage 1 is not an error and not a guess: it is the core set,
    # which under-answers rather than answering wrongly.
    if not chosen:
        chosen = tuple(registration for registration in live if registration.tool.name in CORE_SET)

    return Shortlist(
        tools=tuple(spec_for(registration) for registration in chosen),
        categories=categories,
        ineligible=dropped,
        fell_back=not categories,
        tokens=tokens,
        names=tuple(registration.tool.name for registration in chosen),
    )


__all__ = [
    "CATEGORIES",
    "CORE_SET",
    "Shortlist",
    "choose_categories",
    "discover",
    "eligible",
    "spec_for",
]
