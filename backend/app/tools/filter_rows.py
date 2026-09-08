"""`filter_rows` — the rows that match, and how many did not (§11.4).

**The count of what was dropped is not decoration.** §11.4 names it in the
tool's own row, and the reason is the failure it prevents: an aggregate over a
filter that matched nothing looks exactly like an aggregate over a filter that
matched everything, and both produce a confident number. Saying *778 rows were
left behind* is what turns a result into a result about something.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.expressions import ExpressionError, analyse
from app.storage.engine import DuckDBEngine
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, TableInput, as_json, execute, nest, preview


@tool(category="shape", output_kind="table")
class FilterRows:
    """*"Only the rows where…"* (§11.4)."""

    name = "filter_rows"
    #: v2 - carries `derived`, `size_column` and `ordered` from its
    #: source, so filtering an aggregate leaves an aggregate.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = "Keep the rows that satisfy a condition, and say how many were dropped"

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="expression",
            tier=1,
            description=(
                "A condition, in the expression language. Columns are written in square "
                'brackets: [Age] < 18 and [Sex] = "female".'
            ),
            kind="expression",
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("filter_rows needs the DuckDB engine")

        source = ctx.source
        try:
            condition = analyse(args["expression"], source.columns, expect="boolean")
        except ExpressionError as bad:
            # Re-raised as a `ToolError` so §12.3 step 6 hands it back the way
            # it hands back any other bad argument. The message is unchanged:
            # it already names the column and the type, which is what a model
            # needs to pick again.
            raise ToolError(str(bad)) from bad

        before = execute(ctx.engine, ctx.handle, source)
        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=f"SELECT * FROM {nest(source)} AS t WHERE {condition.sql}",  # noqa: S608
                columns=source.columns,
            ),
        )

        kept = table.row_count or 0
        total = before.row_count or 0
        dropped = total - kept
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"{kept:,} of {total:,} rows match; {dropped:,} were left behind",
            derived=source.derived,
            size_column=source.size_column,
            ordered=source.ordered,
        )


__all__ = ["FilterRows"]
