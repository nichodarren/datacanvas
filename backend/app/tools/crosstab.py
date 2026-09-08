"""`crosstab` — how two categorical columns relate (§11.4).

The one `relationship` tool in the MVP, and the only one that stays inside
D-020's line. *"How does survival break down by class?"* is a count of
combinations, and reading it needs no domain knowledge. *"Does class **cause**
survival?"* is the same table with a claim attached, and that claim is exactly
what §16 defers.

`normalize` is where the tool earns its keep. Raw counts hide the comparison a
reader is making: 233 women survived and 109 men did, which sounds close until
`normalize="row"` says 74% against 19%. Both are in the bundle, always, so the
narration cannot pick one and leave the reader unable to see the other.
"""

from __future__ import annotations

from typing import Any

from app.domain.data import SchemaContract
from app.domain.enums import LogicalType
from app.storage.crosstab import CrosstabReader
from app.storage.engine import DuckDBEngine
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate

#: Always an axis, whatever it holds.
_GROUPABLE = (LogicalType.CATEGORICAL, LogicalType.BOOLEAN)

#: How many distinct values a *numeric* column may hold and still be an axis.
#:
#: WARNING: type alone was the first rule, and it made the canonical Titanic
#: question unanswerable. `Survived` holds 0 and 1, and D-068 keeps such a
#: column `numerical` deliberately -- inference must not read `1,0,1,1` as a
#: flag when it is equally a count of items, because guessing wrong turns
#: arithmetic into logic. That decision is right where it lives and its
#: consequence lands here: a column that **is** a flag was barred from the one
#: tool that reads flags.
#:
#: So the rule is what it always operationally meant. A column can be an axis
#: when it holds few enough values to be one; the logical type is a proxy for
#: that, and where the proxy and the fact disagree, the fact wins. Twelve is
#: months, quarters, ratings, and every flag there is; a column of prices is
#: nowhere near it and still gets refused, which is the case the type rule was
#: protecting against.
MAX_NUMERIC_LEVELS = 12


@tool(category="relationship", output_kind="matrix")
class Crosstab:
    """*"How do these two break down against each other?"* (§11.4)."""

    name = "crosstab"

    #: INV-4: rises when the counting rule, the level cap, the tie-break or the
    #: normalisation arithmetic changes.
    version = 1

    summary = (
        "Counts of every combination of two categorical columns, as a table. "
        "For a heatmap, aggregate on both columns and plot that instead"
    )

    parameters = (
        Param(name="a", tier=1, description="The column down the side.", kind="column"),
        Param(name="b", tier=1, description="The column across the top.", kind="column"),
        Param(
            name="normalize",
            tier=2,
            description=(
                "What each cell is a share of: 'none' for raw counts, 'row' to compare "
                "across a row, 'column' to compare down a column, 'all' for share of the table."
            ),
            kind="enum",
            default="none",
            choices=("none", "row", "column", "all"),
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Two columns that could be axes, or there is nothing to cross.

        Coarse on purpose. Stage 0 sees the contract and never the data, so a
        numeric column counts as a candidate here and is checked properly in
        `execute`, where the distinct count can actually be read.
        """
        candidates = [
            spec
            for spec in contract.columns
            if spec.logical_type in _GROUPABLE or spec.logical_type is LogicalType.NUMERICAL
        ]
        return len(candidates) >= 2

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("crosstab needs the DuckDB engine")

        a, b = args["a"], args["b"]
        if a == b:
            # A column against itself is a diagonal, and a diagonal is the
            # column's own value counts written expensively. `profile_column`
            # already answers that, so say so rather than return it.
            raise ToolError(
                f"{a!r} cannot be crossed with itself; profile_column counts one column"
            )

        reader = CrosstabReader(ctx.engine)
        for name in (a, b):
            spec = next((c for c in ctx.contract.columns if c.name == name), None)
            if spec is None:
                raise ToolError(f"no column named {name!r} in this dataset")
            if spec.logical_type in _GROUPABLE:
                continue
            if spec.logical_type is LogicalType.NUMERICAL:
                levels = reader.levels(ctx.handle, name)
                if levels <= MAX_NUMERIC_LEVELS:
                    continue
                raise ToolError(
                    f"{name!r} holds {levels:,} distinct values, too many for an axis; "
                    f"{self._usable(ctx.contract)}"
                )
            raise ToolError(
                f"{name!r} is {spec.logical_type.value} and cannot be an axis; "
                f"{self._usable(ctx.contract)}"
            )

        matrix = reader.crosstab(ctx.handle, ctx.contract, a=a, b=b, normalize=args["normalize"])
        return dict(matrix.as_json())

    @staticmethod
    def _usable(contract: SchemaContract) -> str:
        """The columns that would work, named.

        A refusal that says only what is wrong is a refusal the model answers
        by proposing the same thing again -- observed live, three times in one
        turn, until the retry budget ran out.
        """
        names = [spec.name for spec in contract.columns if spec.logical_type in _GROUPABLE]
        if not names:
            return "this dataset has no categorical column to cross"
        return f"columns that work: {', '.join(names)}"


__all__ = ["Crosstab"]
