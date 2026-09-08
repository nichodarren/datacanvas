"""`cardinality_report` — which columns are worth grouping by (§11.4).

Three shapes, and each one is a different mistake waiting to be made:

* **one value throughout** — a column that cannot separate anything, and that
  will silently produce a single-row `aggregate` result that looks like a
  finding;
* **every value different** — an identifier, and grouping by it produces one
  group per row, which is the table again with extra steps;
* **more distinct values than a grouped result stays readable at** — legal, and
  the reason `max_dimension` exists rather than a hard rule.

None of the three is an error. All three are answers to *"can I group by
this?"* before somebody spends a step finding out.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.storage.reports import ReportReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate


@tool(category="profiling", output_kind="report")
class CardinalityReport:
    """*"How many different values does each column hold?"* (§11.4)."""

    name = "cardinality_report"

    #: INV-4: rises when a shape rule changes, when the ordering changes, or
    #: when a measure joins or leaves the bundle.
    #: v2 — names the columns that pass, not only the ones that do not.
    version = 2

    summary = "Which columns group into a readable number of values, and which do not"

    parameters = (
        Param(
            name="max_dimension",
            tier=2,
            description=(
                "Flag a column holding more than this many distinct values, on the grounds "
                "that a grouped result stops being readable past it."
            ),
            kind="integer",
            default=50,
            low=2,
            high=10_000,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("cardinality_report needs the DuckDB engine")

        report = ReportReader(ctx.engine).cardinality(
            ctx.handle, ctx.contract, max_dimension=args["max_dimension"]
        )
        return dict(report.as_json())


__all__ = ["CardinalityReport"]
