"""`sort_rows` — the same rows, a different order (§11.4).

`nulls` is tier 3 (D-019). Where missing values sort is edge policy: a model
that sets it produces an order that is plausible, cited, and not what anybody
asked for. The default is `last`, because a reader sorting descending is
looking for the largest values and a column of nulls at the top is a wall
between them and the answer.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.expressions import read_column
from app.storage.engine import DuckDBEngine, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, TableInput, as_json, execute, nest, preview


@tool(category="shape", output_kind="table")
class SortRows:
    """*"Order it by…"* (§11.4)."""

    name = "sort_rows"
    #: v2 - its bundle now says the order was chosen (`ordered`), and
    #: carries `derived`/`size_column` from its source.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = "Reorder rows by one or more columns"

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="by",
            tier=1,
            description="Columns to sort by, most significant first.",
            kind="text_list",
        ),
        Param(
            name="direction",
            tier=2,
            description="Which way to sort.",
            kind="enum",
            default="desc",
            choices=("asc", "desc"),
        ),
        Param(
            name="nulls",
            tier=3,
            description="Where missing values go.",
            kind="enum",
            default="last",
            choices=("first", "last"),
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("sort_rows needs the DuckDB engine")

        source = ctx.source
        keys = list(args["by"])
        if not keys:
            raise ToolError("sort_rows needs at least one column to sort by")
        for name in keys:
            if source.column(name) is None:
                raise ToolError(
                    f"no column named {name!r}; this table has: {', '.join(source.names)}"
                )

        way = args["direction"].upper()
        nulls = args["nulls"].upper()
        # **Sorted on the column's read value, not on its bytes.** Every column
        # is physically VARCHAR, so ordering `Age` as text puts 9 after 18 —
        # right in SQL, wrong in every other sense.
        lookup = {spec.name: spec for spec in source.columns}
        order = ", ".join(
            f"{read_column(name, lookup)} {way} NULLS {nulls}, {_quote(name)} {way}"
            for name in keys
        )

        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=f"SELECT * FROM {nest(source)} AS t ORDER BY {order}",  # noqa: S608
                columns=source.columns,
            ),
        )
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"ordered by {', '.join(keys)} ({args['direction']})",
            derived=source.derived,
            size_column=source.size_column,
            # The one tool that sets it: from here the order means something.
            ordered=True,
        )


__all__ = ["SortRows"]
