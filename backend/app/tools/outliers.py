"""`outlier_scan` — how many values fall outside the fence (§11.4).

## It scans, and that is the whole of it

There is no `action` (D-048). An `action="clip"` would produce a derived table,
and producing a corrected table is cleaning, which the MVP does not do. The
consequence was recorded when cleaning was cut: winsorization moved back out
of reach, and it stays there.

## Why `lower` and `upper` have no defaults

They are optional rather than defaulted, and the difference is not cosmetic.
Absent means *use the IQR fence*; any number a default could pick would be a
different instruction, silently applied. `Param.optional` exists for exactly
this shape.

## What an outlier is not

It is a value far from the others. Whether it is **wrong** is a domain
question, and D-020 puts that outside the MVP. The reason string says how many
and where the fence is; it never says *suspicious*, and the difference is the
line between a measurement and a judgement nobody here is qualified to make.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.domain.enums import LogicalType
from app.storage.engine import DuckDBEngine
from app.storage.reports import ReportReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate


@tool(category="quality", output_kind="report")
class OutlierScan:
    """*"Which values sit far from the rest?"* — one numerical column (§11.4)."""

    name = "outlier_scan"

    #: INV-4: rises when the fence rule changes, when a quantile definition
    #: changes, or when a measure joins or leaves the bundle.
    version = 1

    summary = "How many values in a numerical column fall outside the IQR fence"

    parameters = (
        Param(
            name="column",
            tier=1,
            description="The numerical column to scan.",
            kind="column",
        ),
        Param(
            name="method",
            tier=2,
            description="How the fence is drawn. Only the interquartile rule is available.",
            kind="enum",
            default="iqr",
            choices=("iqr",),
        ),
        Param(
            name="k",
            tier=2,
            description=(
                "How many interquartile ranges past the quartiles the fence sits. "
                "1.5 is the usual rule; 3 keeps only the far ones."
            ),
            kind="number",
            default=1.5,
            low=0.0,
            high=10.0,
        ),
        Param(
            name="lower",
            tier=2,
            description=(
                "Treat values below this as outliers instead of using the fence. "
                "Leave unset to mean no floor of your own."
            ),
            kind="number",
            optional=True,
        ),
        Param(
            name="upper",
            tier=2,
            description=(
                "Treat values above this as outliers instead of using the fence. "
                "Leave unset to mean no ceiling of your own."
            ),
            kind="number",
            optional=True,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Only where there is a number to be far from other numbers.

        The per-column check cannot happen here — `applies_to` sees the table,
        not the argument — so this asks whether *any* column qualifies, and
        `execute` refuses the wrong one by name.
        """
        return any(spec.logical_type is LogicalType.NUMERICAL for spec in contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("outlier_scan needs the DuckDB engine")

        column = args["column"]
        spec = next((c for c in ctx.contract.columns if c.name == column), None)
        if spec is None:
            raise ToolError(f"no column named {column!r} in this dataset")
        if spec.logical_type is not LogicalType.NUMERICAL:
            # Named rather than generic: §12.3 step 6 hands this back to the
            # model, and *"it is categorical"* is what lets it pick again
            # instead of retrying the same argument.
            raise ToolError(
                f"{column!r} is {spec.logical_type.value}, and an outlier fence needs a "
                f"numerical column"
            )

        report = ReportReader(ctx.engine).outliers(
            ctx.handle,
            ctx.contract,
            column=column,
            k=args["k"],
            lower=args["lower"],
            upper=args["upper"],
        )
        return dict(report.as_json())


__all__ = ["OutlierScan"]
