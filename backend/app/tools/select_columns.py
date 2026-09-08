"""`select_columns` — the columns I meant, in the order the file had them (§11.4)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, TableInput, as_json, execute, nest, preview


@tool(category="shape", output_kind="table")
class SelectColumns:
    """*"Just these columns."* (§11.4)."""

    name = "select_columns"
    #: v2 - carries `derived`, `size_column` and `ordered` from
    #: its source.
    #:
    #: INV-4: the output changed, so every bundle cached under v1 must miss.
    version = 2
    summary = "Keep only the named columns, in the order the file had them"

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="columns",
            tier=1,
            description="The columns to keep.",
            kind="column_list",
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("select_columns needs the DuckDB engine")

        source = ctx.source
        wanted = list(args["columns"])
        if not wanted:
            raise ToolError("select_columns needs at least one column")

        missing = [name for name in wanted if source.column(name) is None]
        if missing:
            available = ", ".join(source.names)
            raise ToolError(f"no column named {missing[0]!r}; this table has: {available}")

        # **File order, not the order they were asked for.** §11.4 says so, and
        # the reason is that `columns` is a set — the argument is sorted for the
        # fingerprint (§9.4), so the order somebody typed is not recoverable
        # here and pretending otherwise would produce a layout nobody chose.
        keep = [spec for spec in source.columns if spec.name in set(wanted)]
        projection = ", ".join(_quote(spec.name) for spec in keep)

        table = TableInput(
            sql=f"SELECT {projection} FROM {nest(source)} AS t",  # noqa: S608
            # Renumbered, because a table's ordinals are dense and a column
            # that was fourth in the file is first here.
            columns=tuple(replace(spec, ordinal=index) for index, spec in enumerate(keep)),
        )
        table = execute(ctx.engine, ctx.handle, table)
        dropped = len(source.columns) - len(keep)
        note = f"{dropped} column(s) left behind" if dropped else ""
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            note,
            derived=source.derived,
            size_column=source.size_column,
            ordered=source.ordered,
        )


__all__ = ["SelectColumns"]
