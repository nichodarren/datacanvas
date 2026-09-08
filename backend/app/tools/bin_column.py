"""`bin_column` — a continuous column made groupable (§11.4).

The other half of `cardinality_report`'s answer. When that tool declines to
call `amount` a grouping mistake, it is because the answer for a continuous
quantity is this: cut it into buckets and group by those.

## The edges are named after the column they came from (v2)

A band's edges hold values of the column that was cut, so they are named for
it: `amount_from` and `amount_to`. They used to be `lower` and `upper`, which
named the role and lost the quantity, and the cost landed on the chart —
Vega-Lite composes a binned axis title from both fields, so every histogram
this product drew was labelled **`lower, upper`**. That is the name of the
machinery, not of the thing being counted.

⚠️ **Not `amount` itself.** A chained step reuses the contract's `ColumnSpec`
for any name the contract already knows, which is right where the column really
is the file's and wrong here, where it holds a computed DOUBLE — the read rules
would try `trim()` on a number. The suffix is what keeps the two apart, and the
names are checked against the whole source table so a file that already holds
`amount_from` still gets four distinct columns.

## Dates are bands too, and §11.4 always said so

A date column bins over `epoch(...)` — seconds since 1970 — and hands back its
edges as **dates**, not as the seconds it counted in. The arithmetic needs a
number; the reader needs a date, and a histogram whose x-axis reads
`1704067200` is a histogram nobody can use.

The code refused dates for its first version while its own summary and §11.4
both promised them. That is the direction of drift worth naming: the narrower
half was the code, so the code moved.

`include_nulls` is tier 3 (D-019). Whether rows with no value get a bucket of
their own is edge policy, and a model that turns it on produces a bucket that
is not a range — plausible in a table, wrong in a histogram.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.domain.enums import LogicalType
from app.expressions import read_column
from app.storage.engine import DuckDBEngine, EngineError, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import (
    BASE,
    SOURCE,
    TableInput,
    as_json,
    derived,
    execute,
    nest,
    preview,
)

MAX_BINS = 200


@tool(category="compute", output_kind="table")
class BinColumn:
    """*"Group it into bands."* (§11.4)."""

    name = "bin_column"
    #: v2 — the edge columns are named after the column they cut.
    version = 2
    summary = (
        "Cut a numeric or date column into buckets and count each one — "
        "the first half of a histogram"
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
            name="column",
            tier=1,
            description="The numerical or date column to cut into buckets.",
            kind="column",
        ),
        Param(
            name="strategy",
            tier=2,
            description=(
                "How the buckets are cut: 'equal_width' gives bands of equal size, "
                "'equal_count' gives bands holding equally many rows."
            ),
            kind="enum",
            default="equal_width",
            choices=("equal_width", "equal_count"),
        ),
        Param(
            name="n_bins",
            tier=2,
            description="How many buckets.",
            kind="integer",
            default=10,
            low=2,
            high=MAX_BINS,
        ),
        Param(
            name="include_nulls",
            tier=3,
            description="Give rows with no value a bucket of their own.",
            kind="boolean",
            default=False,
        ),
    )

    #: What can be cut into bands: something with an order and a distance
    #: between its values (§11.4). A category has neither.
    _BINNABLE = frozenset({LogicalType.NUMERICAL, LogicalType.DATE})

    def applies_to(self, contract: SchemaContract) -> bool:
        return any(spec.logical_type in self._BINNABLE for spec in contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("bin_column needs the DuckDB engine")

        source = ctx.source
        column = args["column"]
        spec = source.column(column)
        if spec is None:
            raise ToolError(
                f"no column named {column!r}; this table has: {', '.join(source.names)}"
            )
        logical = spec.logical_type
        if logical not in self._BINNABLE:
            raise ToolError(
                f"{column!r} is {logical.value}, and buckets need a numerical or date column"
            )

        lookup = {c.name: c for c in source.columns}
        read = read_column(column, lookup)
        # **Two expressions for one column, and the split is the whole of date
        # support.** The cut is arithmetic and needs a number; the edges are
        # read by a person and must stay dates. `epoch` is the bridge, and it
        # is used for the width and never for what comes back.
        measured = read if logical is LogicalType.NUMERICAL else f"epoch({read})"
        n_bins = args["n_bins"]
        keep_nulls = args["include_nulls"]

        low, high = self._extent(ctx, source, measured)
        if low is None or high is None:
            raise ToolError(f"{column!r} holds no values that read as numbers")
        if low == high:
            # One value is one bucket, and cutting it into ten would produce
            # nine empty bands that look like a distribution.
            only = f"{low:g}" if logical is LogicalType.NUMERICAL else "the same moment"
            raise ToolError(
                f"every value of {column!r} is {only}, so there is nothing to cut into bands"
            )

        if args["strategy"] == "equal_width":
            width = (high - low) / n_bins
            # `least` pins the maximum into the last bucket: without it the
            # largest value lands one past the end, in a band that does not
            # exist, and the row silently disappears from the result.
            index = (
                f"least(CAST(floor(({measured} - {low!r}) / {width!r}) AS BIGINT), {n_bins - 1})"
            )
        else:
            index = f"CAST(ntile({n_bins}) OVER (ORDER BY {measured}) AS BIGINT) - 1"

        return self._counted(ctx, source, read, index, n_bins, keep_nulls, column, logical)

    # -- the two shapes, kept apart because their SQL is not the same shape --

    def _extent(
        self, ctx: ExecContext, source: TableInput, read: str
    ) -> tuple[float | None, float | None]:
        assert isinstance(ctx.engine, DuckDBEngine)
        query = source.sql.replace(SOURCE, "?")
        row = (
            ctx.engine._cursor()
            .execute(
                f"SELECT min({read}), max({read}) FROM ({query}) AS t",  # noqa: S608
                [ctx.engine._source(ctx.handle)],
            )
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("bin_column found nothing")
        return (
            None if row[0] is None else float(row[0]),
            None if row[1] is None else float(row[1]),
        )

    def _counted(
        self,
        ctx: ExecContext,
        source: TableInput,
        read: str,
        index: str,
        n_bins: int,
        keep_nulls: bool,
        column: str,
        logical: LogicalType,
    ) -> dict[str, Any]:
        # **Named after the column, with a suffix, and never the column's own
        # name.** `amount` alone collides with the file's `amount`: a chained
        # step reuses the contract's `ColumnSpec` for any name the contract
        # knows — right for `filter_rows`, where the column really is the
        # file's, and wrong here, where it holds a computed DOUBLE. The read
        # rules would then try `trim()` on a number. Found by running it.
        #
        # Checked against the whole source table, so a file that already holds
        # `amount_from` still gets four distinct columns. Deterministic given
        # the inputs, which is all §9.4 asks.
        taken = {"bin", "count", *source.names}
        stem = column
        while f"{stem}_from" in taken or f"{stem}_to" in taken:
            stem = f"{stem}_"
        low, high = f"{stem}_from", f"{stem}_to"
        assert isinstance(ctx.engine, DuckDBEngine)
        having = "" if keep_nulls else f" WHERE {read} IS NOT NULL"
        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=(
                    # `lower` and `upper` are the **observed** edges of each
                    # band rather than the arithmetic ones. A band running
                    # 20-30 that actually holds 21 to 29 should say so: the
                    # arithmetic edge is a fact about the cut, and the reader
                    # is looking at a fact about the data.
                    f"SELECT {index} AS bin, min({read}) AS {_quote(low)}, "  # noqa: S608
                    f"max({read}) AS {_quote(high)}, count(*) AS count "
                    f"FROM {nest(source)} AS t{having} GROUP BY 1 ORDER BY 1"
                ),
                columns=(
                    derived("bin", LogicalType.NUMERICAL, 0),
                    # The edges keep the column's own type, so a date
                    # histogram gets a temporal axis instead of an axis of
                    # seconds since 1970 — and its own **name**, because a
                    # binned axis is titled by the field on it.
                    derived(low, logical, 1),
                    derived(high, logical, 2),
                    derived("count", LogicalType.NUMERICAL, 3),
                ),
            ),
        )
        empty = n_bins - (table.row_count or 0)
        # **The next step, named in the result.** A note reaches the model at
        # the moment it is deciding what to do with this table, which is worth
        # more than the same sentence sitting in the catalogue where it
        # competes with sixteen others for attention. `aggregate` already
        # points at `cardinality_report` the same way.
        note = (
            f"{n_bins} bands over {column}; draw it with "
            f"plot(mark='bar', x={low!r}, x_end={high!r}, y='count')"
        )
        if empty > 0:
            # Said out loud: an empty band is a gap in the data, and a reader
            # who cannot tell *no rows here* from *no band here* has lost the
            # one thing a histogram is read to find.
            note += f"; {empty} of them hold no rows"
        # A band and how many rows fell in it: the tool's arithmetic, not
        # the file's rows.
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            note,
            derived=True,
            size_column="count",
        )


__all__ = ["MAX_BINS", "BinColumn"]
