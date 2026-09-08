"""`sample_rows` — n rows at random, **the same n every time** (§11.4).

## The seed is INV-6, not a convenience

*"Same fingerprint implies same result. Always."* A sample without a seed
breaks that outright: the same question asked twice returns different rows, and
every number computed downstream moves with them. So the seed is part of the
arguments, part of the fingerprint, and `REPEATABLE` is not optional.

## Why it has a default anyway (D-019)

Making `seed` tier 1 would satisfy INV-6 and demand that a person invent a
random number — a question with no right answer, asked at the worst moment.
The default makes *"take 1000 rows"* reproducible without anyone thinking about
it, and changing it stays available to whoever actually wants a different
sample. §11.4 spells this out in its own note.

`reservoir` rather than `bernoulli`: reservoir sampling returns **exactly** n
rows, and `bernoulli(p)` returns about n. A tool asked for 1,000 rows that
returns 987 has answered a different question quietly.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, TableInput, as_json, execute, nest, preview

#: The default, and it is a date rather than a random number so that anyone
#: reading a Run Log entry can see it was chosen rather than rolled.
DEFAULT_SEED = 20260728

MAX_ROWS = 1_000_000


@tool(category="shape", output_kind="table")
class SampleRows:
    """*"Give me a random thousand."* — reproducibly (§11.4)."""

    name = "sample_rows"
    #: v2 - refuses a table that is already ordered, and carries
    #: `derived`/`size_column` from its source.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = (
        "Take n rows at random, identically on every run. Only for analysing "
        "some of the rows: results are already capped for display"
    )

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="n",
            tier=1,
            description="How many rows to take.",
            kind="integer",
            low=1,
            high=MAX_ROWS,
        ),
        Param(
            name="seed",
            tier=2,
            description=(
                "Which sample to take. The same seed always returns the same rows; "
                "change it only to get a different sample."
            ),
            kind="integer",
            default=DEFAULT_SEED,
            low=0,
            high=2_147_483_647,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("sample_rows needs the DuckDB engine")

        source = ctx.source
        if source.ordered:
            # **A random sample of a ranking is not a smaller ranking.** The
            # rows survive and the order does not, so the card reads as a top-n
            # while listing whatever the sampler happened to keep, in whatever
            # order it happened to keep it. Seen live on *which 5 regions have
            # the highest average amount*, which ended
            # sort_rows -> limit_rows -> select_columns -> sample_rows.
            #
            # Refused rather than quietly re-sorted: the caller asked for two
            # incompatible things, and picking one for them hides that.
            raise ToolError(
                "this table is already in a chosen order, and sampling it at random "
                "would throw that order away; use limit_rows to keep the first n rows"
            )
        n, seed = args["n"], args["seed"]
        available = execute(ctx.engine, ctx.handle, source).row_count or 0
        if available <= n:
            # Sampling more rows than exist is the whole table, and saying so
            # is better than returning it silently as though it were a sample.
            table = execute(ctx.engine, ctx.handle, source)
            return as_json(
                table,
                preview(ctx.engine, ctx.handle, table),
                f"this table holds {available:,} rows, which is not more than {n:,}, "
                f"so every row is here and nothing was sampled",
                derived=source.derived,
                size_column=source.size_column,
                # Nothing was sampled, so whatever order arrived is intact.
                ordered=source.ordered,
            )

        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=(
                    f"SELECT * FROM {nest(source)} AS t "  # noqa: S608
                    f"USING SAMPLE reservoir({n} ROWS) REPEATABLE ({seed})"
                ),
                columns=source.columns,
            ),
        )
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"{n:,} of {available:,} rows, seed {seed}; the same seed returns the same rows",
            derived=source.derived,
            size_column=source.size_column,
        )


__all__ = ["DEFAULT_SEED", "MAX_ROWS", "SampleRows"]
