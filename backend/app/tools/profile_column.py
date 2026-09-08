"""`profile_column` — one column, in depth (§11.7).

The second tool this product has ever had, and the first one that exercises the
§11.2 contract twice. `describe_dataset` shaped that contract by being its only
user; this is where the shape is tested rather than assumed.

## Why it is a separate tool and not an argument to `describe_dataset`

§11.7.5 answers it with a budget. The overview profiles **every** column and has
to open a 60-column file inside NFR-PERF.2's two seconds, so it takes one pass
and computes what one pass affords. This computes **one** column and is free to
be slow, because nobody opens it before deciding which column they care about.

Folding them together would mean either the overview pays for depth it does not
show, or the panel is limited to what a single cheap pass can reach. §11.7.6(a)
already rejected the other direction — twelve small tools instead of one bundle
— for the same arithmetic, one layer down.

## One bundle, one fingerprint

Same reasoning as §11.8.1: one pass, one `computation_id`. The panel's every
number, and the sentence §11.7.7 writes out of them, share one id — so citing
the sentence cites the numbers, and correcting a column's type invalidates the
whole panel rather than half of it (§9.4 folds `schema_contract_id` in).
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.data import SchemaContract
from app.storage.column_profile import ColumnDetail, ColumnReader
from app.storage.engine import DuckDBEngine
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate

#: Bounds on the tier-2 arguments. Each changes the result, so each is pinned
#: where a person can find it — the same rule `describe_dataset` follows.
MAX_TOP_N = 50
MAX_BINS = 100
MAX_SAMPLES = 20

_ARGUMENTS = frozenset({"column", "top_n", "n_bins", "samples"})


@tool(category="profiling", output_kind="stat_panel")
class ProfileColumn:
    """*"What shape is this column?"* — one column, deeply (§11.7)."""

    name = "profile_column"

    #: INV-4: raise this whenever the numbers here could change — a new
    #: statistic, a changed binning rule, a corrected shape rule. Not for a
    #: reworded docstring: every bump invalidates every cached bundle.
    #:
    #: 1 → 2, on the day this tool was written. The narrative template rendered
    #: 98,400 as `9.84e+04` — `f"{v:,.4g}"` reaches for scientific notation, and
    #: §11.7.7 spells its figures out. Fixing it changed the tool's output, and
    #: **the cache proved it**: two columns profiled after the fix read
    #: correctly while `amount`, already computed, kept serving the old string.
    #:
    #: That is INV-4 arriving in person on this tool's first afternoon, and the
    #: rule left one option rather than two: `computation` is immutable by
    #: trigger (§9.2), so a stale bundle cannot be edited or deleted — it can
    #: only be made unreachable by a version that no longer matches it.
    #: 2 → 3, same afternoon. The narrative joined its fragments with two
    #: spaces, which HTML collapses to one — the panel read *"1,200 distinct
    #: Median 600.5"*, two facts with nothing between them. Rewritten as
    #: sentences. Output changed, so the version does; the rule does not care
    #: that the change was punctuation.
    #: 3 → 4, and this is the last of the afternoon. The header line called
    #: `nulls / total` *empty*, so a column of empty strings read
    #: *"0.0% empty. Every row is empty."* — two true statements about two
    #: different things, arriving as a contradiction. It says *null* now, and
    #: the all-absent branch says which kind of absent.
    #:
    #: 4 → 5 (D-051). The first bump that adds rather than repairs: variance,
    #: range, excess kurtosis, both whisker ends, and a 101-point ECDF grid.
    #: Four of those five are new statistics and the fifth is a new array, so
    #: every cached bundle is missing fields the panel now reads — INV-4 in its
    #: plainest form, and the only reason this one is comfortable is that the
    #: rule fires the same way whether the output grew or went wrong.
    #:
    #: 5 → 6 (D-056). `presence`: completeness in file order, bucketed into
    #: `MATRIX_SLOTS` — the one question about nulls that no count answers,
    #: which is *where* they are.
    #:
    #: 6 → 7 (D-060). `concentration`: cumulative share against category rank,
    #: over **every** category rather than the ten the table shows.
    #:
    #: 7 → 8 (D-065). Three em dashes left §11.7.7's narrative for a middle dot
    #: and two commas. **A punctuation change is an output change**, and the
    #: rule does not grade them — a cached bundle would keep serving the old
    #: string beside a panel rendering the new one, which is the same failure
    #: that took this tool from 2 to 3 on its first afternoon.
    #:
    #: 8 → 9 (D-068). A column declared boolean now counts `1` as true and `0`
    #: as false. Every cached bundle for such a column recorded them as
    #: *neither*.
    #:
    #: 9 → 10 (D-069). The date bundle rebuilt on calendar boundaries: the
    #: epoch-binned timeline is gone, every series is zero-filled across its own
    #: domain, and the weekday cycle stops starting on Friday.
    #:
    #: 10 → 11 (D-070, D-071). The text bundle rebuilt: character and word
    #: distributions, four more composition shares, the values that repeat, and
    #: a vocabulary block that crosses §11.7.3's boundary on purpose.
    #:
    #: 11 → 12, an hour later, and **the cache proved it again**. `TextStats`
    #: shipped with `others_distinct` hard-coded to 0 and it was fixed after the
    #: bump — so the fingerprint never moved, and the panel kept reading
    #: `0 more values` above a remainder of 1,166 rows while the reader
    #: returned 1,028. Fifth time this tool has learned the rule, and the tell
    #: was the same every time: a figure on screen that the code plainly no
    #: longer computes.
    #:
    #: 12 → 13 (D-073). A word cloud, and sixty single terms to draw it with
    #: where the panel had twelve. `top_words` is now the head of that list
    #: rather than its own query, so the cloud and the bar column beside it
    #: cannot disagree.
    #:
    #: 13 → 14 (D-074). The numerical bundle carries a rug: every distinct
    #: value with its count, unbinned, so a column that only holds multiples of
    #: five stops looking continuous.
    #:
    #: 14 -> 15, minutes later, and **the cache proved the rule a sixth time**.
    #: `rug` was added to the model and not to `_as_json`, so it crossed as
    #: `[[1.0, 236], ...]` where every other pair on this wire crosses as an
    #: object: the panel read `point.value` off an array, got `undefined` for
    #: every tick, keyed all of them `undefined` and positioned all of them at
    #: `NaN%`. Naming it did not move the fingerprint, so the cache kept
    #: serving the array. Same tell as the other five: a figure on screen that
    #: the code plainly no longer produces.
    #:
    #: 15 -> 16 (D-074). The rug keeps its largest value whatever the stride
    #: did with it, so it stops where its own axis does.
    version = 16

    summary = "Full univariate profile of one column, shaped by its logical type"

    parameters = (
        Param(
            name="column",
            tier=1,
            kind="column",
            description="The name of the column to profile, exactly as the schema spells it.",
        ),
        Param(
            name="top_n",
            tier=2,
            description="How many of the commonest values to list for a categorical column.",
            default=10,
            low=1,
            high=MAX_TOP_N,
        ),
        Param(
            name="n_bins",
            tier=2,
            description="Histogram buckets for a numerical column.",
            default=20,
            low=2,
            high=MAX_BINS,
        ),
        Param(
            name="samples",
            tier=2,
            description="How many example values to show.",
            default=10,
            low=1,
            high=MAX_SAMPLES,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Wherever there is a column to profile.

        The per-type branching lives inside the profile rather than here: every
        logical type has a shape, including `empty`, so narrowing this would
        only hide the one column a reader most wants explained.
        """
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        """Validated and defaulted here, never at the call site.

        An argument left out and the same argument passed at its default are the
        same question; if they hashed differently the cache would answer one of
        them twice.
        """
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("profile_column needs the DuckDB engine")

        detail = ColumnReader(ctx.engine).profile(
            ctx.handle,
            ctx.contract,
            column=args["column"],
            top_n=args["top_n"],
            n_bins=args["n_bins"],
            samples=args["samples"],
        )
        return _as_json(detail)


def _as_json(detail: ColumnDetail) -> dict[str, Any]:
    """The bundle as JSONB can hold it.

    `asdict` walks the nested dataclasses; the two derived numbers are written
    in afterwards. `null_share` is a property rather than a field, so it is not
    in the dict — and a client recomputing it from `nulls / total` would be a
    second place that has to agree about what counts as absent.
    """
    payload: dict[str, Any] = asdict(detail)
    payload["completeness"]["null_share"] = detail.completeness.null_share

    numeric = detail.numeric
    if numeric is not None:
        # Tuples of pairs become a list of two-element lists through `asdict`,
        # which is honest JSON but awkward to read. Named on the wire instead.
        payload["numeric"]["quantiles"] = [
            {"q": q, "value": value} for q, value in numeric.quantiles
        ]
        payload["numeric"]["ecdf"] = [{"p": p, "value": value} for p, value in numeric.ecdf]
        payload["numeric"]["rug"] = [
            {"value": value, "count": count} for value, count in numeric.rug
        ]

    # Same reason as `quantiles`: `asdict` turns tuples of pairs into lists of
    # two-element lists, which is honest JSON and awkward to read.
    categorical = detail.categorical
    if categorical is not None:
        payload["categorical"]["concentration"] = [
            {"rank": rank, "share": share} for rank, share in categorical.concentration
        ]

    payload["presence"]["slots"] = [
        {"rows": rows, "present": seen} for rows, seen in detail.presence.slots
    ]
    text = detail.text
    if text is not None:
        for key in ("top", "top_words", "top_pairs", "top_triples"):
            payload["text"][key] = [
                {"value": item.value, "count": item.count} for item in getattr(text, key)
            ]
        payload["text"]["vocabulary"] = [
            {"rank": rank, "share": share} for rank, share in text.vocabulary
        ]

    for shape, keys in (
        (
            "date",
            (
                "by_year",
                "by_month",
                "by_day",
                "by_weekday",
                "by_month_of_year",
                "by_hour",
            ),
        ),
    ):
        block = payload.get(shape)
        if block is not None:
            for key in keys:
                block[key] = [{"key": k, "count": n} for k, n in block[key]]

    return payload
