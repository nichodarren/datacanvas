"""`describe_dataset` — the Profile tab's one tool (§11.8).

Every card on that tab is a slice of one call to this. §11.7.6(a) settled that
shape and §11.8.1 restates it: one pass, one bundle, **one fingerprint**. The
rejected alternative — a `histogram` tool, a `top_values` tool, a `median` tool
— reads well until you count what the tab actually asks for. Twelve columns
times four statistics is forty-eight tool calls, forty-eight fingerprints,
forty-eight cache lookups and forty-eight Run Log entries, against NFR-PERF.2's
two-second budget.

The single fingerprint buys the opposite: opening the tab a second time is a
cache hit, and because §9.4 folds `schema_contract_id` into the hash, correcting
one column's type invalidates the whole bundle — which is right. This is not a
collection of independent results that happen to be requested together; it is
one result about one table read one way.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.storage.profile import DatasetProfile, ProfileReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate

#: Bounds on the tier-2 arguments. Not taste — each is a number that changes the
#: result, so each has to be pinned somewhere a person can find it.
MAX_TOP_N = 20
MAX_BINS = 50
MAX_SAMPLES = 10


@tool(category="profiling", output_kind="column_cards")
class DescribeDataset:
    """*"What is in this data?"* — every column, cheaply (§11.4, §11.8)."""

    name = "describe_dataset"

    #: INV-4: this rises whenever the numbers this returns could change — a new
    #: statistic, a changed binning rule, a corrected shape rule. It does **not**
    #: rise for a reworded docstring, and §9.4 explains why that distinction is
    #: worth keeping: every bump invalidates every cached bundle.
    #:
    #: 1 → 2 (D-040): the ``identifier`` shape was removed, so a column of serial
    #: numbers now returns a median and bins where it previously returned
    #: samples. Same arguments, same data, different answer — which is exactly
    #: the condition INV-4 names. Leaving it at 1 would have served the old
    #: bundle from cache forever, carrying a ``kind`` the frontend no longer has
    #: a branch for.
    #: 3 → 4 (D-068). The overview card counts true and false from the same
    #: vocabulary the panel does, and that vocabulary gained `1` and `0`. This
    #: tool's own code did not change; the list it reads did, which is exactly
    #: the case INV-4 exists for.
    version = 4

    summary = "Shape, types, completeness and cardinality for every column"

    parameters = (
        Param(
            name="top_n",
            tier=2,
            description="How many of the commonest values to keep per categorical column.",
            default=3,
            low=1,
            high=MAX_TOP_N,
        ),
        Param(
            name="n_bins",
            tier=2,
            description="Histogram buckets for each numerical column.",
            default=10,
            low=2,
            high=MAX_BINS,
        ),
        Param(
            name="samples",
            tier=2,
            description="How many example values to show per column.",
            default=3,
            low=1,
            high=MAX_SAMPLES,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Always. A dataset with columns can always be described, and a
        dataset with none cannot be opened at all."""
        return True

    def args(self, **given: Any) -> dict[str, Any]:
        """Validated, defaulted, and normalised into what the fingerprint sees.

        Defaults are filled in here rather than at the call site. An argument
        left out and the same argument passed at its default value are the same
        question, and if they hash differently the cache answers one of them
        twice.
        """
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("describe_dataset needs the DuckDB engine")

        profile = ProfileReader(ctx.engine).describe(
            ctx.handle,
            ctx.contract,
            top_n=args["top_n"],
            n_bins=args["n_bins"],
            samples=args["samples"],
        )
        return _as_json(profile)


def _as_json(profile: DatasetProfile) -> dict[str, Any]:
    """The bundle as JSONB can hold it.

    ``logical_type`` is a ``StrEnum``, which ``json`` serialises as its value —
    but only because it subclasses ``str``. Written out explicitly so the
    payload does not depend on that being true of whatever the enum becomes.
    """
    columns = []
    for column in profile.columns:
        entry = asdict(column)
        entry["logical_type"] = column.logical_type.value
        entry["null_share"] = column.null_share
        entry["samples"] = list(column.samples)
        entry["bins"] = [asdict(b) for b in column.bins]
        entry["top"] = [asdict(t) for t in column.top]
        columns.append(entry)

    return {"row_count": profile.row_count, "columns": columns}


__all__ = ["MAX_BINS", "MAX_SAMPLES", "MAX_TOP_N", "DescribeDataset"]
