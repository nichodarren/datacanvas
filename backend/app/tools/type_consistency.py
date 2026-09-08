"""`type_consistency_report` — columns holding what they say they do not (§11.4).

## What it compares, and why that is the honest comparison

The contract says a column is `numerical`. This counts how many of its present
values actually read as a number by the same shape rules inference used, and
reports the gap. A column that is 94.8% numeric with 62 rows spelling `unknown`
is the classic case: the type is right, the null marker is not, and no
completeness figure anywhere shows it — `unknown` is a value, so the column
reports 0% null while a twentieth of it is missing in fact.

## Text and categorical are not scanned, deliberately

**Anything is text.** A conformance figure for a text column would be 1.0 for
every text column ever, which is not a measurement, it is a tautology dressed
as one. So they are excluded and `scanned` says how many columns could
disagree — a report of nothing over nothing is stated as such rather than
returned as a clean bill of health.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.storage.reports import ReportReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate


@tool(category="quality", output_kind="report")
class TypeConsistencyReport:
    """*"Is this column really what we think it is?"* (§11.4)."""

    name = "type_consistency_report"

    #: INV-4: rises with any change to the shape rules, to which logical types
    #: are scanned, or to the measures returned.
    version = 1

    summary = "Columns whose values do not match the type the schema declares"

    parameters = (
        Param(
            name="min_conformance",
            tier=2,
            description=(
                "Report a column when the fraction of its values matching its declared type "
                "falls below this. 0.95 flags a column with one bad value in twenty."
            ),
            kind="number",
            default=0.95,
            low=0.0,
            high=1.0,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Only where a declared type exists to disagree with.

        Stage 0 of discovery (§12.2), and it earns its place here: on a file
        read entirely as text there is nothing this tool could ever find, and
        offering it would spend a step to say so.
        """
        return any(
            spec.logical_type.value in {"numerical", "boolean", "date"} for spec in contract.columns
        )

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("type_consistency_report needs the DuckDB engine")

        report = ReportReader(ctx.engine).type_consistency(
            ctx.handle, ctx.contract, min_conformance=args["min_conformance"]
        )
        return dict(report.as_json())


__all__ = ["TypeConsistencyReport"]
