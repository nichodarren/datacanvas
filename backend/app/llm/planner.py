"""The planner loop (§12.3), and the two validations that make it trustworthy.

## The loop

```
1  assemble context          §12.4 — structured state, never a transcript
2  tool discovery            §12.2 — three stages, already built
3  privacy gate              §13.5 — every payload, one exit
4  call the model
5  receive a proposal
6  VALIDATE the proposal
     registered?   no -> reject with feedback
     args valid?   no -> reject with feedback, twice at most
     applies_to?   no -> reject with the reason
     in budget?    no -> stop, and say so
7  run it as a Step, through the same executor the manual path uses
8  hand back a **summary**, gate-filtered — never the bundle
9  repeat until it narrates, or MAX_STEPS
10 VALIDATE the narration    hard fail, see below
11 stream
```

## Why step 6 rejects instead of raising

A model that names an argument wrong has made a recoverable mistake, and the
recovery is telling it what it did. Two attempts, then the turn stops: a third
is a model that has not understood the schema, and looping on it spends tokens
to arrive at the same place.

## Why step 10 is a hard failure

§12.5 asks for three checks, and the second is the one v1 did not have:

1. **Every citation resolves** to something that ran in this turn.
2. **Every number in the narration appears in a cited result.** This closes the
   most dangerous failure mode there is — *the model cites the right
   computation and misreads the number out of it*. It happens, and without a
   numeric check nothing catches it: the citation is valid, the id resolves,
   the sentence is confident, and the figure is wrong.
3. **A number with no citation is flagged, not hidden.** Hiding it would leave
   a confident sentence with nothing behind it and no way to tell.

Failing the turn is the point. A broken citation means the product's central
claim — every number is traceable — was violated, and that is not something to
let through quietly (INV-5).

## What is not here yet, and why that is the plan rather than a shortcut

Step 7 runs through an injected `Executor`. **`Step` does not exist yet**: the
`step` table is Phase 3's first migration and has not been written, so today's
implementation produces a `Computation` and citations resolve to a
`computation_id`. §12.5 names `computation_id` in its own rule, so the contract
is unchanged; what is missing is the Run Log entry above it. D-049 already moved
the copilot ahead of that work, and this is that ordering, stated.
"""

from __future__ import annotations

import contextlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

from app.domain.data import SchemaContract
from app.llm.contract import LLMClient, LLMError, Message, ToolCall
from app.llm.discovery import Shortlist, eligible, spec_for
from app.llm.privacy import SUPPRESSED, Filtered, GroupRow, PrivacyGate
from app.storage.engine import EngineError
from app.tools.contract import ToolError, ToolRegistry, UnknownTool

log = logging.getLogger(__name__)

#: §12.3. Down from v1's eight: the data showed a turn needing more than six
#: was almost always a model that had got lost, not analysis that was deep.
MAX_STEPS = 6

#: §12.3 step 6. Two, then stop.
MAX_ARG_RETRIES = 2


def _stopped(reason: str, steps: list[Ran]) -> str:
    """Why the turn ended, and what it had already produced.

    **A turn that stops is almost never a turn that did nothing.** A rate limit
    on the call that would have written the sentence arrives *after* the tools
    have run, and their results are already on the canvas with ids of their
    own. Reporting only the failure tells the reader the question went nowhere,
    which is both discouraging and false — and it hides work they have already
    paid for and can read.

    §14.5, and the same rule as everywhere else in this product: an empty state
    says which kind of empty it is.
    """
    if not steps:
        return reason
    ran = ", ".join(step.tool for step in steps)
    what = "step" if len(steps) == 1 else "steps"
    return f"{reason}. {len(steps)} {what} had already run and their results are below: {ran}."


#: `[ref: 4f2c…]`. Whitespace is tolerated because a model writing prose puts
#: it where prose wants it, and refusing a valid citation over a space would be
#: rejecting a right answer for its formatting.
CITATION = re.compile(r"\[ref:\s*([0-9a-zA-Z-]+)\s*\]")

#: `[4f2c…]` — the same citation with the label left off.
#:
#: ⚠️ Read **only when the id resolves to something that ran in this turn**,
#: which is what makes it unambiguous: a markdown link, a footnote marker and a
#: bracketed aside do not happen to spell a reference this turn produced.
#:
#: Found live, and it is the sharpest miss this validator has had. A model
#: narrated survival rates of 35.7 / 49.3 / 50.0 against a result holding
#: 91.7 / 91.3 / 37.2 — **exactly the failure rule 2 exists to catch** — and
#: rule 2 never ran, because the citation was spelled without its label and
#: rule 3 reported the sentence as uncited instead. The reader was still
#: warned, so nothing unsafe shipped; but *uncited* and *wrong* are different
#: faults, and the diagnosis is the part somebody acts on.
BARE_CITATION = re.compile(r"\[([0-9a-zA-Z-]{4,})\]")

#: Spelled out rather than escaped inside an f-string: three separate edits
#: to this file lost a backslash between a shell heredoc and a Python
#: literal, and each time the damage looked like a syntax error on a line
#: nobody had touched.
NEWLINE = chr(10)

#: What a model writes when it means a minus sign.
#:
#: ⚠️ Not a hypothetical list. Groq's `gpt-oss-120b` narrated a real skewness of
#: -0.03 as U+2011 NON-BREAKING HYPHEN, so `-?` did not match and the figure was
#: read as **positive** 0.03 — which then genuinely was not in the result, and
#: the turn was failed for a sentence that was correct. A validator that cries
#: wolf is worse than no validator: it teaches the reader to click past the one
#: warning that mattered.
_MINUS = "-\u2011\u2012\u2013\u2212"

#: What a model writes between thousands. Narrow no-break space is what the same
#: model used, and reading `1<U+202F>200` as `1` would fail a correct sentence for
#: its typography.
_GROUPING = ",\u00a0\u202f\u2009"

#: Numbers as they appear in prose: `1,200`, `-3.5`, `98400`. Deliberately not
#: matching a bare `%` or a year-like token on its own — those are picked up as
#: numbers and checked, which is the safe direction to be wrong in.
#:
#: ⚠️ **A dash between two digits is a range, not a minus**, and the lookbehind
#: is the whole of that rule. Observed live on a correct sentence: a model
#: describing bands wrote `0.42<U+2011>8 years (54 passengers)` with a non-breaking
#: hyphen, and every band in it came back as a negative the result did not
#: contain — nine complaints against nine right numbers. **A validator that
#: fails correct sentences teaches the reader to click past the one that
#: mattered, and this is the fifth time that shape has come up in this file.**
#:
#: A sign still counts anywhere a digit does not precede it, which is every
#: place a negative number is actually written.
NUMBER = re.compile(rf"(?<!\d)[{_MINUS}]?\d[\d{_GROUPING}]*(?:\.\d+)?")

#: How close a narrated number has to be to a computed one. Relative, because a
#: model rounding 1,204,556 to "1.2 million" is being helpful and a model
#: turning 0.43 into 0.34 is not.
TOLERANCE = 0.005

#: ⚠️ **The citation rule is spelled out to the letter, and that is deliberate.**
#:
#: The first version said *put [ref: id] after every figure*. Models obeyed it
#: loosely — a markdown paragraph with one citation at the end of some sentences
#: — so §12.5 rule 3 flagged nearly every answer. **An answer that is always
#: marked unverified teaches the reader that the mark means nothing**, which is
#: the same failure as a false positive and costs the same thing: the one
#: warning that mattered gets clicked past.
#:
#: `prompt is preference, code is guarantee` still holds — the validator is
#: what enforces this, and it does not soften. What the prompt can do is stop
#: the model failing a check it was trying to pass.
#:
#: WARNING: **chaining is explained here because nothing else could explain
#: it.** Transforms compose through a `table` argument holding an earlier
#: step's id, and that is Mechanism 1 — the answer to the long tail, and the
#: reason the catalogue is not merely a list. A model that does not know the
#: id it was handed can be passed back has eight transforms it can only ever
#: use one at a time, and since D-049 the prompt is the only door. The
#: *guarantee* is still code: `table` is validated, resolved against this
#: dataset only, and refused if it names anything else.
_SYSTEM = """\
You answer questions about one tabular dataset by calling tools. You never \
compute a number yourself and you never guess one.

Tools compose, and most questions worth asking take more than one step. \
Every result comes back with an id, and any tool with a `table` argument \
can be given that id to read the previous step's output instead of the \
dataset. Leave `table` unset to read the dataset itself.

Work in that order: narrow the rows first if the question is about some \
of them, add a column only if the number you need is not in the data \
already, and group last. Prefer the tool whose name matches the question.

When the question asks to **see** something — a chart, a plot, a histogram, \
a distribution, how one thing looks against another — the answer is a chart, \
and `plot` is the tool that makes one. Run whatever produces the numbers, \
then call `plot` on that result, then write the sentences. A paragraph \
describing a chart is not a chart. A scatter shows one row per point, \
so plot the rows themselves; group \
first only when the question asks for a summary per category.

Every result that nothing else reads is shown to the reader as a card of \
its own, so call a tool only when you already know what will read its \
output. Do not look around first: the schema above is everything the \
dataset has, and a step taken to orient yourself becomes a card that \
answers nothing. If a step turns out to be a wrong turn, leave it and move \
on, and do not run the same work again in another shape.

You are shown at most 20 rows of any result, so `limit_rows` and \
`sample_rows` never make one more readable. Reach for them only when the \
question is about some of the rows, and never after `sort_rows`, which \
throws away the ordering that was the point of sorting.

When you have what you need, write the answer as a few short sentences of \
plain English. No markdown, no bullet lists, no headings.

Citation rule, and it is strict: every sentence that states a number must end \
with [ref: <id>], where <id> is the id of the tool result that number came \
from. One sentence, one citation, at the end. If a sentence would state \
numbers from two different results, split it into two sentences. A sentence \
with no number needs no citation.

Example: The column holds 891 values [ref: abc-123]. Its mean is 32.2 \
[ref: abc-123]."""


def _offer_everything(registry: ToolRegistry, contract: SchemaContract) -> Shortlist:
    """Every tool this dataset could use, with no model call at all.

    ⚠️ **§12.2's stage 1 is switched off** (D-094, 2026-08-27), on the product
    owner's decision. At seventeen tools the whole catalogue is ~2,760 tokens
    against ~1,050 for a typical shortlist, so it fits in a prompt — and the
    reason §12.2 gives for staging is a catalogue that does not.

    Measured before switching it off, so the trade is on the record rather than
    assumed: stage 1 routed **25 of 25** one-step questions to the right
    category, including ones with no keyword overlap at all. It also produced
    the failure that motivated this: *for passengers under 18, what is the
    survival rate by class* routes to `compute`, which is right, and the
    shortlist then held nothing that could say *under 18* because filtering
    lives in `shape`. **A tool that is always offered cannot be invisible.**

    Stage 0 stays. `applies_to` reads the contract, costs nothing, cannot be
    got wrong by a model, and without it a dataset holding no numbers is still
    offered `outlier_scan` — a step spent to be told no.

    `discovery.py` is kept whole and kept tested. Catalogues grow, and §12.2's
    argument becomes true again when this one outgrows a prompt.
    """
    live = eligible(registry, contract)
    kept = {registration.tool.name for registration in live}
    return Shortlist(
        tools=tuple(spec_for(registration) for registration in live),
        categories=(),
        ineligible=tuple(
            registration.tool.name
            for registration in registry.all()
            if registration.tool.name not in kept
        ),
        fell_back=False,
        tokens=0,
        names=tuple(sorted(kept)),
    )


class Executor(Protocol):
    """Runs one tool and returns what it can be cited as.

    Injected rather than imported so the planner cannot reach data on its own,
    and so the manual path and this path stay the same path (§12.3 step 7).
    """

    async def run(self, tool_name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """`(reference, bundle)`. The reference is what a citation must match."""
        ...


@dataclass(frozen=True, slots=True)
class Ran:
    """One tool that actually ran, and what the model was told about it."""

    ref: str
    tool: str
    args: dict[str, Any]
    #: Gate-filtered text. This, and never the bundle, is what step 8 sends.
    summary: str
    #: Every number in the bundle, for the §12.5 rule 2 check. Held here rather
    #: than re-derived later so the figures checked against are exactly the
    #: figures computed.
    figures: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Complaint:
    """Something wrong with the narration that the reader must be able to see."""

    kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class Turn:
    """One question, answered or honestly not."""

    narrative: str | None = None
    steps: tuple[Ran, ...] = ()
    #: Why the loop stopped short, when it did. `None` means it finished.
    stopped: str | None = None
    #: §12.5. Non-empty means the narration failed validation.
    complaints: tuple[Complaint, ...] = ()
    #: What was said back to the model when a proposal was refused (§12.3 step
    #: 6). Kept because a turn that went nowhere should be explainable.
    rejections: tuple[str, ...] = ()
    tokens: int = 0
    categories: tuple[str, ...] = field(default_factory=tuple)
    #: Which rung answered last — `gemini`, or `gemini#2` (D-096). §12.8
    #: accounts per rung, and two accounts of one vendor are two bills.
    provider: str = ""
    #: Which model wrote the sentence. **The rung is the account and this is
    #: what shaped the answer**, and they move on different schedules: a rung
    #: changes when somebody edits `.env`, a model id when a vendor retires
    #: one.
    #:
    #: The *last* call rather than the first, because that is the one that
    #: produced the narration on screen. A turn stays on one vendor (`pin`),
    #: but a rate limit at step three rolls it onto a sibling account, and
    #: labelling the answer with the rung that ran step one would name a
    #: model that did not write it.
    model: str = ""

    @property
    def grounded(self) -> bool:
        return self.narrative is not None and not self.complaints


# --------------------------------------------------------------- step 8 ------


#: Keys that carry machinery rather than an answer, and are skipped whole.
#:
#: A transform stores the query that produces its table and `plot` stores a
#: Vega-Lite document; both are how the system works rather than what it found.
#: Sending them would spend tokens on SQL and on chart geometry, and a spec's
#: inlined `data.values` would reach the model as a shape the gate never
#: classified — raw rows arriving by a door K4 does not watch.
_PLUMBING = frozenset({"sql", "spec"})


def summarise(bundle: dict[str, Any], gate: PrivacyGate) -> tuple[str, tuple[float, ...]]:
    """A tool result as the model may see it, and the figures it contains.

    **Allowlist, and the default is to drop.** A walker that emitted whatever
    it found would send category values as though they were statistics, which
    is precisely the leak the gate exists to prevent — so an unrecognised shape
    is left out rather than guessed at. The consequence is stated: a tool whose
    output shape nobody taught this function will summarise as less than it
    could, and never as more than it should.
    """
    lines: list[str] = []
    figures: list[float] = []
    # The denominator every share is out of, read from the bundle rather
    # than passed in: it is the tool's own count of what it looked at.
    completeness = bundle.get("completeness")
    present = 0
    if isinstance(completeness, dict):
        found = completeness.get("present")
        if isinstance(found, int) and not isinstance(found, bool):
            present = found

    def walk(node: Any, path: str) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int | float):
            figures.append(float(node))
            # A proportion is quoted as a percentage by every narrator
            # alive, so both forms are the same fact. `top5_share: 1.0`
            # failing a sentence that says `100%` is the validator
            # arguing about units.
            if path.endswith("_share") and 0.0 <= float(node) <= 1.0:
                percent = float(node) * 100
                figures.append(round(percent, 1))
                lines.append(gate.statistic(path, f"{node} ({percent:.1f}%)"))
                return
            lines.append(gate.statistic(path, node))
            return
        if isinstance(node, str):
            # K3. A bare string in a result is a value out of the data far more
            # often than it is a label, so it goes out only where K3 does.
            if gate.allows.category_values:
                lines.append(f"{path}: {node}")
            return
        if isinstance(node, dict):
            table = _as_table(node)
            if table is not None:
                rendered, seen = _render_table(table, gate)
                figures.extend(seen)
                if rendered:
                    lines.append(f"{path}:{NEWLINE}{rendered}")
                return
            for key, value in node.items():
                if key in _PLUMBING:
                    continue
                walk(value, f"{path}.{key}" if path else str(key))
            return
        if isinstance(node, list | tuple):
            # K1 before K3: a list of column cards is **structural metadata**,
            # which §13.5 lets through in every mode but `local`. Dropping it
            # was the allowlist being right about the rule and wrong about the
            # category, and the cost showed up live — the model could not
            # answer *how many columns are there* because it had never been
            # shown one, so it re-ran `describe_dataset` until the turn died.
            schema = _as_columns(node)
            if schema is not None:
                # The count first, and in `figures`: *how many columns* is a
                # question about this result, and a reader who asks it should
                # not have the right answer failed for want of the number
                # being on the list.
                figures.append(float(len(schema)))
                if gate.allows.schema:
                    joined = NEWLINE.join(schema)
                    lines.append(f"{path}: {len(schema)}{NEWLINE}{joined}")
                return
            rows = _as_groups(node)
            if rows is not None:
                filtered = gate.groups(rows, total=present)
                figures.extend(float(row.count) for row in rows)
                figures.extend(float(value) for row in rows for value in row.values)
                if present > 0:
                    # The share, so the narrator quotes it instead of
                    # deriving it. Rounded to what the summary prints,
                    # because a model repeating `21.2` must match `21.2`.
                    figures.extend(round(row.count / present * 100, 1) for row in rows)
                # A category value that looks like a number **is** in the
                # result, so naming it is grounded. A `rating` column
                # holding "3" is the ordinary case, not a corner one.
                for row in rows:
                    with contextlib.suppress(ValueError):
                        figures.append(float(row.key.replace(",", "")))
                lines.append(f"{path}:{NEWLINE}{filtered.render()}")
                return
            findings = _as_findings(node)
            if findings is not None:
                # **K1, not K3.** A finding's subject is a column name and its
                # reason is prose the tool computed about that column, so both
                # ride with the schema. Judging them as category values was the
                # mistake that dropped `describe_dataset`'s column list, and
                # the shape here is close enough to make it twice.
                for subject, reason, measures in findings:
                    for key, value in measures.items():
                        figures.append(value)
                        # The percentage as well, because the reason prints
                        # `(19.9%)` and a model quoting the sentence it was
                        # given must not be told the number is not there.
                        if key.endswith("_share") or key == "conformance":
                            figures.append(round(value * 100, 1))
                    if gate.allows.schema:
                        lines.append(f"{path}: {subject}: {reason}")
                return
            cells = _as_cells(node)
            if cells is not None:
                # A cell key is two data values, so it goes out under K3 and
                # through k-anonymity like any other group: a combination only
                # four rows hold is a person, whatever it is called.
                figures.extend(float(row.count) for row in cells)
                for row in cells:
                    for value in row.values:
                        figures.append(value)
                        figures.append(round(value * 100, 2))
                # Rendered here rather than by `Filtered.render`, which prints
                # measures positionally. Three unlabelled decimals on a line
                # is a model told 14.75 without being told it is the column
                # share, and a narration that quotes the wrong one of them is
                # grounded, cited, and wrong.
                lines.append(f"{path}:{NEWLINE}{_render_cells(gate.groups(cells))}")
                return
            # A list of anything else is dropped rather than flattened: it is
            # the shape most likely to be rows.
        return

    walk(bundle, "")
    said = NEWLINE.join(line for line in lines if line)

    # **Everything shown is quotable.** The walker collects numbers it can read
    # as numbers, and a date is not one of them: `bin_column` over `order_date`
    # renders `2023-01-05 | 2023-03-12 | 118`, the model quite reasonably says
    # *from 2023 to 2025*, and rule 2 called three correct years unsupported
    # because no float in the bundle equalled 2023.
    #
    # §12.5 rule 2 asks whether a figure **appears in the cited result**, and
    # 2023 does — this was the check disagreeing with the text it had itself
    # handed over. Reading the rendered summary back closes that gap for every
    # shape at once rather than teaching the walker about dates and then about
    # the next type after them.
    #
    # It does not weaken the rule. What rule 2 exists to catch is a model
    # citing the right computation and stating a number that is **not** in it;
    # a number inside the summary is in it by construction.
    figures.extend(_numbers(said))
    return (said, tuple(dict.fromkeys(figures)))


def _as_columns(node: list[Any] | tuple[Any, ...]) -> list[str] | None:
    """`[{name, kind, …}, …]` — the shape `describe_dataset` returns.

    Only the name and the logical type leave, and only those: the rest of a
    column card is counts and shares, which are K2 and belong to the walker
    that classifies them one at a time. Matched by key name rather than by
    position, so a list of pairs cannot be mistaken for this.
    """
    if not node:
        return None
    named: list[str] = []
    for item in node:
        if not isinstance(item, dict):
            return None
        name = item.get("name")
        kind = item.get("kind") or item.get("logical_type")
        if not isinstance(name, str) or not isinstance(kind, str):
            return None
        named.append(f"{name}: {kind}")
    return named


def _numeric_args(args: dict[str, Any]) -> tuple[float, ...]:
    """Every argument a narration could legitimately quote.

    Booleans are excluded: `True` is not a number a sentence states, and
    `isinstance(True, int)` would otherwise put `1.0` on the list for every
    flag, grounding a `1` the result never contained.
    """
    return tuple(
        float(value)
        for value in args.values()
        if isinstance(value, int | float) and not isinstance(value, bool)
    )


def _as_findings(
    node: list[Any] | tuple[Any, ...],
) -> tuple[tuple[str, str, dict[str, float]], ...] | None:
    """`[{subject, reason, measures}, …]` — what every `report` analyzer returns.

    Five tools share one shape so this has to learn it once. Before it existed
    a report reached the walker, matched neither of the two list shapes it
    knew, and was **dropped in full** — the model would have been handed a
    missingness report containing no columns, no counts and no reasons, and
    would have had nothing to do but run it again.
    """
    if not node:
        return ()
    out: list[tuple[str, str, dict[str, float]]] = []
    for item in node:
        if not isinstance(item, dict):
            return None
        subject, reason = item.get("subject"), item.get("reason")
        measures = item.get("measures")
        if not isinstance(subject, str) or not isinstance(reason, str):
            return None
        if not isinstance(measures, dict):
            return None
        numbers = {
            key: float(value)
            for key, value in measures.items()
            if isinstance(key, str)
            and isinstance(value, int | float)
            and not isinstance(value, bool)
        }
        out.append((subject, reason, numbers))
    return tuple(out)


def _as_cells(node: list[Any] | tuple[Any, ...]) -> tuple[GroupRow, ...] | None:
    """`[{row, column, count, value}, …]` — the long-form `matrix` shape.

    Flattened to `row x column` group rows rather than given a renderer of its
    own, and that is the point: a cell holding four rows is as identifying as
    a group holding four rows, so it belongs in the machinery PG-1 already
    guards rather than beside it.
    """
    if not node:
        return ()
    rows: list[GroupRow] = []
    for item in node:
        if not isinstance(item, dict):
            return None
        left, right = item.get("row"), item.get("column")
        count = item.get("count")
        if not isinstance(left, str) or not isinstance(right, str):
            return None
        if not isinstance(count, int) or isinstance(count, bool):
            return None
        # The three shares, in the order `_SHARE_LABELS` names them. Positional
        # because `GroupRow` carries a bare tuple, which is exactly why the
        # rendering has to supply the labels.
        measures: list[float] = []
        for key in ("row_share", "column_share", "total_share"):
            found = item.get(key)
            measures.append(
                float(found)
                if isinstance(found, int | float) and not isinstance(found, bool)
                else 0.0
            )
        rows.append(GroupRow(key=f"{left} x {right}", count=count, values=tuple(measures)))
    return tuple(rows)


#: What `_as_cells` puts in `GroupRow.values`, in order.
_SHARE_LABELS = ("of row", "of column", "of table")


def _render_cells(filtered: Filtered) -> str:
    """A gated matrix as text a model can read without counting columns.

    The gate decides **which** cells leave; this decides how they read. Keeping
    those apart is what lets PG-1 stay one implementation while a shape that
    carries three different shares still says which is which.
    """
    lines = []
    for row in filtered.rows:
        if row.key == SUPPRESSED:
            lines.append(SUPPRESSED)
            continue
        shares = ", ".join(
            f"{value * 100:.2f}% {label}"
            for value, label in zip(row.values, _SHARE_LABELS, strict=False)
        )
        lines.append(f"{row.key}: n={row.count}{', ' + shares if shares else ''}")
    if filtered.omitted:
        lines.append(f"...and {filtered.omitted} more combinations")
    return NEWLINE.join(lines)


@dataclass(frozen=True, slots=True)
class _Table:
    """A transform's preview, before the gate decides what may leave."""

    names: tuple[str, ...]
    rows: tuple[tuple[Any, ...], ...]
    #: Rows the **tool** computed rather than rows out of the file (§13.5).
    derived: bool
    #: Which column holds how many source rows each row stands for, if any.
    #: Named by the tool rather than sniffed for: a group key called `count`
    #: is not a group size.
    size_column: str | None


def _as_table(node: dict[str, Any]) -> _Table | None:
    """`{columns: [str], rows: [[…]], derived: bool}` — what `as_json` builds.

    Matched by shape *and* by the flag, so the top-level bundle — whose
    `columns` are dicts and which has no `rows` — cannot be mistaken for one.
    """
    names, rows = node.get("columns"), node.get("rows")
    if not isinstance(names, list) or not isinstance(rows, list):
        return None
    if not all(isinstance(name, str) for name in names):
        return None
    if not all(isinstance(row, list) for row in rows):
        return None
    size = node.get("size_column")
    return _Table(
        names=tuple(names),
        rows=tuple(tuple(row) for row in rows),
        derived=bool(node.get("derived")),
        size_column=size if isinstance(size, str) and size in names else None,
    )


def _render_table(table: _Table, gate: PrivacyGate) -> tuple[str, list[float]]:
    """A derived table as the model may read it, and the figures in it.

    ⚠️ **This is the fix for a model that could not see its own arithmetic.**
    Every transform's preview used to be dropped, on the grounds that a list of
    lists *is the shape most likely to be rows* — true, and the reason raw rows
    must not go out. But `aggregate` and `bin_column` return rows the **tool**
    computed, and dropping those meant a model that binned `Age` was shown four
    column names and a row count with **not one band in it**. It went looking
    for the values with `sample_rows`, got another table it could not see, and
    looped until the step budget ran out — observed four times in a row on
    *give me histogram of age*.

    ## What the gate still does

    * Rows out of the file (`derived=False`) go only under `full`, unchanged.
    * A derived table needs `category_values`, the same key that lets a group
      label out anywhere else.
    * **PG-1 rides on the count column when there is one.** A band holding
      three rows is three people, and it is suppressed exactly as a group of
      three is suppressed in every other shape on this wire.
    * PG-2 caps the rows, and the cap is *said* — a truncated list that does
      not say it was truncated is a model narrating over a gap it cannot see.

    ⚠️ **A derived table that does not name a size column is not sent**, because
    PG-1 has nothing to stand on. That used to include every `mean(x) by y`, and
    the cost was visible the moment it was measured: a model shown no numbers at
    all recited the right ones from memory of a famous dataset and was correctly
    failed for citing a result that did not contain them. `aggregate` v2 carries
    `n`, so the gate can do its job instead of looking away.
    """
    if not table.rows:
        return ("", [])

    if not table.derived:
        raw = gate.rows(table.rows)
        return (_grid(table.names, raw), []) if raw else ("", [])

    if not gate.allows.category_values:
        return ("", [])

    if table.size_column is None:
        return ("", [])
    counted = table.names.index(table.size_column)

    kept: list[tuple[Any, ...]] = []
    suppressed = 0
    for row in table.rows[: gate.max_rows]:
        size = row[counted]
        if isinstance(size, str):
            with contextlib.suppress(ValueError):
                size = float(size)
        if isinstance(size, int | float) and not isinstance(size, bool) and size < gate.k:
            suppressed += 1
            continue
        kept.append(row)

    figures: list[float] = []
    for row in kept:
        for value in row:
            with contextlib.suppress(TypeError, ValueError):
                if value is None or isinstance(value, bool):
                    continue
                number = float(value)
                figures.append(number)
                # **A proportion and its percentage are the same fact**, and
                # the walker above already says so for a `_share` column. A
                # mean over a 0/1 flag is a proportion under another name:
                # `mean_Survived` holds 0.742 and every narrator alive writes
                # 74.2%. Failing that sentence is the validator arguing about
                # units, and a validator that fails correct sentences teaches
                # the reader to click past the one that mattered.
                if 0.0 <= number <= 1.0:
                    figures.append(round(number * 100, 1))

    body = _grid(table.names, tuple(kept)) if kept else ""
    tail: list[str] = []
    if suppressed:
        # **Said in words, because the short form was read as a zero.**
        # Observed live: `1 row(s) [suppressed, n<5]` came back narrated as
        # *the last bin has no passengers*. A suppression narrated as an
        # absence is worse than showing nothing at all — it converts *we are
        # not telling you* into a false claim about the data, and the reader
        # has no way to tell.
        held = "row" if suppressed == 1 else "rows"
        tail.append(
            f"({suppressed} more {held} exist but hold fewer than {gate.k} records each, "
            f"so they are withheld — they are not empty)"
        )
    if len(table.rows) > gate.max_rows:
        tail.append(f"...and {len(table.rows) - gate.max_rows} more rows")
    return (NEWLINE.join([body, *tail]).strip(), figures)


def _grid(names: tuple[str, ...], rows: tuple[tuple[Any, ...], ...]) -> str:
    """Header then rows, pipe separated.

    Labelled rather than positional, for the reason D-086(c) gave: three bare
    decimals on a line is a model told `31.87` without being told which of
    three shares it is, and a narration that quotes the wrong one is grounded,
    cited, and wrong.
    """
    lines = [" | ".join(names)]
    lines.extend(
        " | ".join("null" if value is None else str(value) for value in row) for row in rows
    )
    return NEWLINE.join(lines)


def _as_groups(node: list[Any] | tuple[Any, ...]) -> tuple[GroupRow, ...] | None:
    """`[{value, count}, …]` is the one list shape this understands.

    It is the shape every top-N block on this wire already uses, and matching it
    by name rather than by position means a list of pairs cannot be mistaken for
    one.
    """
    if not node:
        return ()
    rows: list[GroupRow] = []
    for item in node:
        if not isinstance(item, dict):
            return None
        key, count = item.get("value"), item.get("count")
        if not isinstance(key, str) or not isinstance(count, int) or isinstance(count, bool):
            return None
        rows.append(GroupRow(key=key, count=count))
    return tuple(rows)


# -------------------------------------------------------------- step 10 ------


def validate_narrative(text: str, steps: tuple[Ran, ...]) -> tuple[Complaint, ...]:
    """§12.5, all three rules."""
    complaints: list[Complaint] = []
    known = {step.ref: step for step in steps}

    def refs_in(fragment: str) -> list[str]:
        """Every citation in a fragment, however it was spelled.

        A bare `[id]` counts only when it names a step that ran, which is what
        keeps this from reading brackets that were never citations.
        """
        found = CITATION.findall(fragment)
        found.extend(
            ref for ref in BARE_CITATION.findall(fragment) if ref in known and ref not in found
        )
        return found

    cited = CITATION.findall(text)
    for ref in cited:
        if ref not in known:
            complaints.append(
                Complaint(
                    kind="unresolved-citation",
                    detail=f"[ref: {ref}] does not name anything that ran in this turn",
                )
            )

    # Rule 3 before rule 2, because a number with no citation cannot be checked
    # against one — reporting it as *wrong* would be reporting the wrong fault.
    for sentence in _sentences(text):
        numbers = _numbers(sentence, frozenset(known))
        if not numbers:
            continue
        refs = refs_in(sentence)
        if not refs:
            complaints.append(
                Complaint(
                    kind="uncited-number",
                    detail=f"a figure is stated with no citation: {sentence.strip()[:80]}",
                )
            )
            continue

        # Rule 2. The failure v1 could not see: the citation resolves, the
        # sentence is confident, and the figure is not the computed one.
        #
        # Only against citations that **resolved**. A sentence whose every
        # citation dangles has already been reported once, and adding *this
        # number is not in the result it cites* on top of it names a second
        # fault that is really the first one's shadow.
        resolved = [ref for ref in refs if ref in known]
        if not resolved:
            continue
        available = tuple(figure for ref in resolved for figure in known[ref].figures)
        for number in numbers:
            if not any(_close(number, figure) for figure in available):
                complaints.append(
                    Complaint(
                        kind="unsupported-number",
                        detail=(
                            # `%g` keeps six significant digits, so a complaint
                            # about 168113.6 was printed as **168114** — a
                            # number the sentence never contained, in the one
                            # place a reader goes to check what went wrong.
                            f"{number:.12g} is not in the result it cites "
                            f"({_named(resolved, known)})"
                        ),
                    )
                )

    return tuple(complaints)


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _named(refs: list[str], known: dict[str, Ran]) -> str:
    """The steps a complaint is about, by name rather than by id.

    Two reasons, and the second is not cosmetic. D-099 took `computation_id`
    off the screen because a UUID cannot be remembered, compared or typed —
    and this string is rendered in the panel, so it was the one place an id
    survived. And the same id appeared twice whenever a sentence cited it
    twice, which reads as two different faults.
    """
    seen: list[str] = []
    for ref in refs:
        name = known[ref].tool if ref in known else ref
        if name not in seen:
            seen.append(name)
    return ", ".join(seen)


def _numbers(text: str, known: frozenset[str] = frozenset()) -> list[float]:
    """Every number a sentence actually claims.

    ⚠️ **A citation id contains digits, and they are not claims.** `known` is
    what makes that true for a citation spelled without its label: a bare
    `[5aa86861]` is a span to skip only when it names a step that ran, which is
    the same test `refs_in` applies.

    Widening what counts as a citation without widening this produced three
    false positives per sentence the moment it was tried — `5` and `86861`
    read straight out of the reference. A validator that fails correct
    sentences teaches the reader to click past the one that mattered, and this
    is the fourth time that shape has come up in this file.
    """
    spans = list(CITATION.finditer(text))
    spans.extend(match for match in BARE_CITATION.finditer(text) if match.group(1) in known)

    found: list[float] = []
    for match in NUMBER.finditer(text):
        if any(span.start() <= match.start() < span.end() for span in spans):
            continue
        written = match.group()
        for sign in _MINUS[1:]:
            written = written.replace(sign, "-")
        for separator in _GROUPING:
            written = written.replace(separator, "")
        try:
            found.append(float(written))
        except ValueError:  # pragma: no cover - the pattern cannot produce this
            continue
    return found


def _close(said: float, computed: float) -> bool:
    if said == computed:
        return True
    scale = max(abs(said), abs(computed))
    return scale > 0 and abs(said - computed) / scale <= TOLERANCE


# ---------------------------------------------------------- the loop ---------


async def run_turn(
    question: str,
    *,
    client: LLMClient,
    registry: ToolRegistry,
    contract: SchemaContract,
    gate: PrivacyGate,
    executor: Executor,
    budget: int | None = None,
) -> Turn:
    """§12.3, steps 1 to 10. Step 11 belongs to whatever streams this."""
    shortlist = _offer_everything(registry, contract)
    spent = shortlist.tokens

    schema = gate.schema(contract)
    messages: list[Message] = [
        Message(role="system", content=_SYSTEM),
        # §12.4: structured state, never a transcript. Today that is the schema
        # digest; `recent_steps`, `pinned` and `definitions` arrive with the
        # entities that hold them.
        Message(
            role="user",
            content=f"Columns:{NEWLINE}{schema}{NEWLINE}{NEWLINE}Question: {question}",
        ),
    ]

    steps: list[Ran] = []
    rejections: list[str] = []
    retries = 0
    answered_by = ""
    answered_with = ""

    # **One turn, one model.** The cascade picks; after that the conversation
    # is pinned to whoever answered, because every call after the first
    # replays a transcript containing tool calls, and a transcript belongs to
    # the vendor that produced it. See `LLMClient.pin`.
    answering: LLMClient = client

    for _ in range(MAX_STEPS):
        if budget is not None and spent >= budget:
            return Turn(
                steps=tuple(steps),
                stopped=_stopped(f"token budget of {budget} reached", steps),
                rejections=tuple(rejections),
                tokens=spent,
                categories=shortlist.categories,
                provider=answered_by,
                model=answered_with,
            )

        try:
            proposal = await answering.propose(tuple(messages), shortlist.tools)
        except LLMError as cause:
            return Turn(
                steps=tuple(steps),
                stopped=_stopped(str(cause), steps),
                rejections=tuple(rejections),
                tokens=spent,
                categories=shortlist.categories,
                provider=answered_by,
                model=answered_with,
            )
        spent += proposal.spent
        if answering is client and proposal.provider:
            answering = client.pin(proposal.provider)
        # Overwritten every call on purpose: the label belongs to whoever wrote
        # the sentence, which is the last rung to answer. A turn stays on one
        # vendor (`pin`), but a rate limit at step three rolls it onto a sibling
        # account, and naming the rung that ran step one would name a model that
        # did not write the answer.
        answered_by, answered_with = proposal.provider, proposal.model

        if not proposal.calls:
            text = proposal.text or ""
            return Turn(
                narrative=text or None,
                steps=tuple(steps),
                complaints=validate_narrative(text, tuple(steps)) if text else (),
                rejections=tuple(rejections),
                tokens=spent,
                categories=shortlist.categories,
                provider=answered_by,
                model=answered_with,
            )

        call = proposal.calls[0]
        args, refusal = _check(call, registry, contract, tuple(steps))

        if refusal is None:
            # **The normalised arguments, not the model's.** `args()` fills the
            # defaults, and §9.4 hashes what it is given: an argument omitted
            # and the same argument at its default are one question, so handing
            # the raw dict on would put two cache entries behind one question —
            # and the second is the one nobody could reproduce from the Run Log.
            try:
                ref, bundle = await executor.run(call.name, args)
            except (ToolError, EngineError) as declined:
                # ⚠️ **A tool that refuses mid-run is step 6 again, not a crash.**
                #
                # `_check` can only see what `args()` can see, and `args()` sees
                # the argument without the data. Whether `Survived` is a column
                # a crosstab can use is a question about the *contract*, and
                # `applies_to` is handed the table rather than the argument — so
                # per-column refusals necessarily live inside `execute`.
                #
                # This was unreachable until the analyzers landed: the two
                # profiling tools only refuse when the engine is wrong, which
                # cannot happen. It cost a live turn the first time it could —
                # the model proposed `crosstab(Sex, Survived)`, a reasonable
                # guess on a 0/1 column, and the whole turn died with a
                # traceback instead of being told to pick again.
                #
                # **Two types, and the second cost a second live turn.**
                # `EngineError` is what storage raises when an argument names
                # a column it cannot find, and it is not a `ToolError` — so
                # catching only the latter left the same hole one layer down.
                # Both mean *this tool cannot answer with these arguments*,
                # which is step 6. What is deliberately **not** caught is
                # `InvariantViolation`: that means the system is wrong, and a
                # model cannot fix it by proposing something else.
                refusal = str(declined)

        if refusal is not None:
            retries += 1
            rejections.append(refusal)
            if retries > MAX_ARG_RETRIES:
                return Turn(
                    steps=tuple(steps),
                    stopped=_stopped(f"gave up after {MAX_ARG_RETRIES} rejected proposals", steps),
                    rejections=tuple(rejections),
                    tokens=spent,
                    categories=shortlist.categories,
                    provider=answered_by,
                    model=answered_with,
                )
            messages.append(Message(role="assistant", content="", tool_calls=(call,)))
            messages.append(
                Message(role="tool", content=refusal, tool_call_id=call.id or call.name)
            )
            continue

        summary, figures = summarise(bundle, gate)
        # **The arguments are part of the result.** §9.4 hashes them into the
        # computation's identity and the Run Log records them, so a narration
        # quoting the threshold a scan was run at is quoting the computation,
        # not inventing a number. Found live: `cardinality_report` prints
        # `past the 50 a grouped result stays readable at` in its own reason
        # and the model was failed for repeating the sentence it was handed.
        ran = Ran(
            ref=ref,
            tool=call.name,
            args=args,
            summary=summary,
            figures=figures + _numeric_args(args),
        )
        steps.append(ran)
        messages.append(Message(role="assistant", content="", tool_calls=(call,)))
        messages.append(
            Message(
                role="tool",
                content=f"id: {ref}{NEWLINE}{summary}",
                tool_call_id=call.id or call.name,
            )
        )

    return Turn(
        steps=tuple(steps),
        stopped=_stopped(f"reached {MAX_STEPS} steps without an answer", steps),
        rejections=tuple(rejections),
        tokens=spent,
        categories=shortlist.categories,
        provider=answered_by,
        model=answered_with,
    )


def _check(
    call: ToolCall,
    registry: ToolRegistry,
    contract: SchemaContract,
    already: tuple[Ran, ...] = (),
) -> tuple[dict[str, Any], str | None]:
    """Step 6. Returns `(normalised arguments, refusal)`; one of the two is empty.

    The normalised arguments come back rather than being recomputed by the
    caller: validating and normalising is one pass, and doing it twice is two
    places that have to agree about defaults.
    """
    if call.unparsed is not None:
        return (
            {},
            f"Your arguments were not a JSON object: {call.unparsed[:120]}. "
            "Send an object whose keys are the parameter names.",
        )
    try:
        registration = registry.get(call.name)
    except UnknownTool:
        offered = ", ".join(sorted(r.tool.name for r in registry.all()))
        return ({}, f"There is no tool called {call.name!r}. The tools you have are: {offered}.")

    if not registration.tool.applies_to(contract):
        return ({}, f"{call.name} does not apply to this dataset.")

    try:
        args = registration.tool.args(**call.arguments)
    except ToolError as cause:
        return ({}, f"{cause}")

    # **The same call twice is a loop, and it is cheap to catch here.** The
    # second run is a cache hit so it computes nothing, but it still costs a
    # full round trip and a place out of the six §12.3 allows — and a model
    # repeating itself is the shape §12.3 gave MAX_STEPS for. Observed live:
    # `describe_dataset` proposed twice with identical arguments, then the turn
    # ran out of budget before it narrated.
    for step in already:
        if step.tool == registration.tool.name and step.args == args:
            return (
                {},
                f"You already ran {registration.tool.name} with those arguments "
                f"in this turn; its result is id {step.ref}. Use it, or call a "
                f"different tool, or write the answer.",
            )

    return (args, None)


__all__ = [
    "CITATION",
    "MAX_ARG_RETRIES",
    "MAX_STEPS",
    "TOLERANCE",
    "Complaint",
    "Executor",
    "Ran",
    "Turn",
    "run_turn",
    "summarise",
    "validate_narrative",
]
