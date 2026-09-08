"""`missingness_report` — where the holes are, and which of them are the same hole (§11.4).

Two questions, and only the second needs its own tool. *How empty is each
column* is on every Profile card already; *are `cabin` and `deck` empty in the
**same** rows* is not, and it cannot be derived from two null counts. Two
columns at 77% empty are one absence or two, and which one it is changes what
the data means.

`co_missing` is tier 3 (D-019): a model that turned it off would be making a
cost decision it has no way to price, and the pairing is the reason to run this
rather than read the cards.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine
from app.storage.reports import ReportReader
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate


@tool(category="quality", output_kind="report")
class MissingnessReport:
    """*"What is not there?"* — per column, and per pair (§11.4)."""

    name = "missingness_report"

    #: INV-4: rises whenever these counts could change — a changed definition
    #: of *present*, a different pairing rule, a new measure in the bundle.
    version = 1

    summary = "Which columns are empty, how empty, and which go missing together"

    parameters = (
        Param(
            name="min_share",
            tier=2,
            description=(
                "Only report a column when at least this fraction of its values are missing. "
                "0 reports every column that has any hole at all."
            ),
            kind="number",
            default=0.0,
            low=0.0,
            high=1.0,
        ),
        Param(
            name="co_missing",
            tier=3,
            description="Also report pairs of columns that are empty in the same rows.",
            kind="boolean",
            default=True,
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Any table can be asked what it is missing, including one missing nothing.

        A report that comes back empty is an answer — *nothing is missing* is
        worth knowing, and refusing to run would leave the reader unable to
        tell it apart from *nobody asked*.
        """
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("missingness_report needs the DuckDB engine")

        report = ReportReader(ctx.engine).missingness(
            ctx.handle,
            ctx.contract,
            min_share=args["min_share"],
            co_missing=args["co_missing"],
        )
        return dict(report.as_json())


__all__ = ["MissingnessReport"]
