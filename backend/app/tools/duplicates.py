"""`duplicate_report` — how much of this table is a copy of itself (§11.4).

## Three numbers, because they answer three questions

A count of duplicates is ambiguous in a way that shows up as a wrong sentence
in a narration, so this returns all three and names each one:

| measure | question |
|---|---|
| `duplicate_groups` | how many values repeat at all |
| `duplicate_rows` | how many rows are involved in a repeat |
| `redundant_rows` | how many rows would go if each were kept once |

Only the last answers *"how much of this table is redundant"*, and it is the
one a reader means. Reporting `duplicate_rows` under that question overstates
the redundancy by exactly the number of groups.

## No `keep`

Choosing which row survives is repair, and repair is out of the MVP (D-048).
This says how many, on which columns, and stops.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.storage.reports import ReportReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate


@tool(category="quality", output_kind="report")
class DuplicateReport:
    """*"Are these rows repeats?"* — over every column, or a subset (§11.4)."""

    name = "duplicate_report"

    #: INV-4: rises when the counting rule changes, or when a measure is added
    #: to or removed from the bundle.
    version = 1

    summary = "How many rows repeat, over every column or a named subset"

    parameters = (
        Param(
            name="subset",
            tier=2,
            description=(
                "Columns that define a duplicate. Leave empty to mean an exact copy "
                "across every column."
            ),
            kind="column_list",
            default=(),
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("duplicate_report needs the DuckDB engine")

        report = ReportReader(ctx.engine).duplicates(
            ctx.handle, ctx.contract, subset=list(args["subset"])
        )
        return dict(report.as_json())


__all__ = ["DuplicateReport"]
