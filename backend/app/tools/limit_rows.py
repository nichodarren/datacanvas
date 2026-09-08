"""`limit_rows` — the first n rows, and nothing about which n (§11.4).

⚠️ **This does not sort, and that matters more than it looks.** `LIMIT 100`
over an unordered table is *some* hundred rows, and the note says so. Rows come
back in file order because `preserve_insertion_order` is pinned (see
`storage/engine.py`), so the answer is reproducible — but reproducible is not
the same as meaningful, and *the top 100* is a question only `sort_rows` can
answer.

`offset` is tier 3 (D-019): paging is a reader's mechanic, and a model that
sets it produces a page nobody asked for out of a result nobody saw.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, TableInput, as_json, execute, nest, preview

MAX_ROWS = 1_000_000


@tool(category="shape", output_kind="table")
class LimitRows:
    """*"Just the first few."* (§11.4)."""

    name = "limit_rows"
    #: v2 - carries `derived`, `size_column` and `ordered` from its
    #: source, so a top-n over an aggregate is still readable.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = (
        "Keep n rows, in the order the table already has. Use it for a top-n "
        "after sort_rows; results are already capped for display"
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
            tier=2,
            description="How many rows to keep.",
            kind="integer",
            default=100,
            low=1,
            high=MAX_ROWS,
        ),
        Param(
            name="offset",
            tier=3,
            description="How many rows to skip first.",
            kind="integer",
            default=0,
            low=0,
            high=MAX_ROWS,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("limit_rows needs the DuckDB engine")

        source = ctx.source
        n, offset = args["n"], args["offset"]
        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=f"SELECT * FROM {nest(source)} AS t LIMIT {n} OFFSET {offset}",  # noqa: S608
                columns=source.columns,
            ),
        )
        skipped = f", after skipping {offset:,}" if offset else ""
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"{table.row_count:,} rows in the order the table already had{skipped}; "
            f"this is not a ranking",
            derived=source.derived,
            size_column=source.size_column,
            ordered=source.ordered,
        )


__all__ = ["MAX_ROWS", "LimitRows"]
