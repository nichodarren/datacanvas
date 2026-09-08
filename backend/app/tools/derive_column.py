"""`derive_column` — one new column, computed from the ones already there (§11.4).

This and `filter_rows` are the two tools the expression language exists for
(§11.3), and between them they are most of Mechanism 1: *"the average tip rate
by day"* is `derive_column` then `aggregate`, and neither step needed a tool
nobody had written.

The derived column's logical type comes from the **expression's** type, not
from a guess about its values. `[tip] / [total_bill]` is numerical because
division is; `if([Age] < 18, "child", "adult")` is text because both branches
are. Inferring it from the results instead would make the type of a column
depend on the data in it, which is the one thing a schema is supposed not to do.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.expressions import ExpressionError, analyse
from app.storage.engine import DuckDBEngine, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import (
    AS_LOGICAL,
    BASE,
    TableInput,
    as_json,
    derived,
    execute,
    nest,
    preview,
)


@tool(category="compute", output_kind="table")
class DeriveColumn:
    """*"Add a column that is…"* (§11.4)."""

    name = "derive_column"
    #: v2 - carries `derived`, `size_column` and `ordered` from
    #: its source.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = "Add one column computed from the others"

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="name",
            tier=1,
            description="What to call the new column.",
            kind="column",
        ),
        Param(
            name="expression",
            tier=1,
            description=(
                "How to compute it, in the expression language. Columns are written in "
                "square brackets: [tip] / [total_bill]."
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
            raise ToolError("derive_column needs the DuckDB engine")

        source = ctx.source
        name = args["name"]
        if source.column(name) is not None:
            # Replacing a column silently would make the same name mean two
            # things in one chain, and the Run Log entry would not say which.
            raise ToolError(
                f"this table already has a column called {name!r}; derived columns take a new name"
            )

        try:
            computed = analyse(args["expression"], source.columns)
        except ExpressionError as bad:
            raise ToolError(str(bad)) from bad

        columns = (
            *source.columns,
            derived(name, AS_LOGICAL[computed.type], len(source.columns)),
        )
        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=(
                    f"SELECT *, {computed.sql} AS {_quote(name)} "  # noqa: S608
                    f"FROM {nest(source)} AS t"
                ),
                columns=columns,
            ),
        )
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"{name} is {computed.type}, computed from {', '.join(computed.columns) or 'nothing'}",
            derived=source.derived,
            size_column=source.size_column,
            ordered=source.ordered,
        )


__all__ = ["DeriveColumn"]
