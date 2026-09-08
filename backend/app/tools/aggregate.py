"""`aggregate` — group and count, and the end of four golden queries (§11.4).

C1, C2, C3 and C5 all finish here, and each finishes differently: a mean of a
derived column, a mean of a 0/1 flag, a mean per class after a filter, and a
plain count over dirty data. One tool, because they are one question asked
about different columns.

## Measures are written the way a person says them

`mean(tip_rate)`, `count()`, `sum(amount)`. A list of objects would be more
regular and would also be a thing to explain; the shape a model reaches for
first is the one people write, and it round-trips exactly.

## `count()` counts rows; `count(x)` counts values

The difference is the whole of missingness and it is not a subtlety a caller
should have to remember, so both spellings exist and mean what they say. A
column that is 20% empty has a `count()` and a `count(col)` that differ by
exactly its holes.

## Every result carries `n`, and that is two things at once

A mean over three rows and a mean over three hundred are different facts and
used to be the same number. Since v2 each group also reports how many rows it
was computed from.

The second reason is the one that forced it. **PG-1 needs a group size to
stand on**: `aggregate(group_by=["name"], measures=["mean(fare)"])` is one
person's fare per row, and without a count on the row the Privacy Gate cannot
tell that from a mean over three hundred. So it withheld the whole table, and a
model asked *what is the average fare per class* was shown no numbers at all —
whereupon it recited the right ones from memory of a famous dataset and was
correctly failed for citing a result that did not contain them.

`n` is skipped when a bare `count()` is already asked for, because that is the
same number under another name.

## Nothing is normalised on the way in

C5 is built on this: `region` holds `Jakarta`, `jakarta` and `Jakarta ` as
three different groups, and returning them as three is the point. Folding
case here would produce a different answer that looks the same, which is the
failure that golden query exists to catch.
"""

from __future__ import annotations

import re
from typing import Any

from app.domain.data import SchemaContract
from app.domain.enums import LogicalType
from app.expressions import read_column
from app.storage.engine import DuckDBEngine, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import (
    BASE,
    TableInput,
    as_json,
    derived,
    execute,
    nest,
    preview,
)

#: `fn(column)` or `fn()`. Anchored, so a measure carrying anything else — a
#: comma, a nested call, a stray quote — is refused rather than partly matched.
_MEASURE = re.compile(r"^([A-Za-z_]+)\(\s*(.*?)\s*\)$")

#: What each measure compiles to, and what it produces. `count` is the only one
#: that reads rows rather than values, which is why it is the only one that
#: works without a column.
_AGGREGATES: dict[str, tuple[str, LogicalType, bool]] = {
    "count": ("count", LogicalType.NUMERICAL, True),
    "distinct_count": ("count", LogicalType.NUMERICAL, False),
    "sum": ("sum", LogicalType.NUMERICAL, False),
    "mean": ("avg", LogicalType.NUMERICAL, False),
    "median": ("median", LogicalType.NUMERICAL, False),
    "min": ("min", LogicalType.NUMERICAL, False),
    "max": ("max", LogicalType.NUMERICAL, False),
}

#: Aggregates that need a number to work on. `count` and `distinct_count` do
#: not — counting how many distinct regions there are is a fair question.
_NEEDS_NUMBER = frozenset({"sum", "mean", "median"})

MAX_GROUPS = 10_000


def _counts_rows(measure: str) -> bool:
    """Whether this measure is already the group size.

    `count()` counts rows; `count(col)` counts values, and the two differ by
    exactly that column's holes — which is the whole of missingness and the
    reason both spellings exist. Only the first makes `n` redundant.
    """
    found = _MEASURE.match(measure)
    return found is not None and found.group(1).lower() == "count" and not found.group(2)


@tool(category="compute", output_kind="table")
class Aggregate:
    """*"…by…"* — one row per group (§11.4)."""

    name = "aggregate"
    #: v2 — every group reports `n`, the rows it was computed from.
    version = 2
    summary = "One row per group, with counts and averages over the rest"

    parameters = (
        Param(
            name="table",
            tier=2,
            description="Which table to read: 'dataset', or the id of an earlier step.",
            kind="table",
            default=BASE,
        ),
        Param(
            name="group_by",
            tier=2,
            description=(
                "Columns to group by, in the order they should appear. "
                "Leave empty for one row covering the whole table."
            ),
            kind="text_list",
            default=(),
        ),
        Param(
            name="measures",
            tier=1,
            description=(
                "What to compute per group, written as function(column): "
                "count(), count(Age), distinct_count(region), sum(amount), mean(tip), "
                "median(fare), min(age), max(age)."
            ),
            kind="text_list",
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("aggregate needs the DuckDB engine")

        source = ctx.source
        lookup = {spec.name: spec for spec in source.columns}
        groups = list(args["group_by"])
        measures = list(args["measures"])
        if not measures:
            raise ToolError("aggregate needs at least one measure, such as count()")

        for name in groups:
            if name not in lookup:
                raise ToolError(
                    f"no column named {name!r}; this table has: {', '.join(source.names)}"
                )

        selected: list[str] = []
        columns = []
        for name in groups:
            # **Grouped on the raw value, not the read value.** C5 depends on
            # it: `Jakarta` and `Jakarta ` are two groups because they are two
            # values in the file, and reading through `trim` would merge them
            # into an answer that looks the same and is different.
            selected.append(_quote(name))
            columns.append(lookup[name])
        for ordinal, measure in enumerate(measures, start=len(groups)):
            sql, spec = self._measure(measure, lookup, ordinal)
            selected.append(sql)
            columns.append(spec)

        # **The group size, unless it was already asked for.** Two reasons, and
        # the second is not optional: a mean over three rows and a mean over
        # three hundred are different facts, and PG-1 has nothing to stand on
        # without it (§13.5).
        size = next((spec.name for spec in columns[len(groups) :] if spec.name == "count"), None)
        if size is None:
            # A dataset may already hold a column called `n`, and grouping by it
            # would give this result two columns of that name. Deterministic
            # given the others, which is all §9.4 asks.
            taken = {spec.name for spec in columns}
            size = next(name for name in ("n", "n_rows", "group_size") if name not in taken)
            selected.append(f'count(*) AS "{size}"')
            columns.append(derived(size, LogicalType.NUMERICAL, len(selected) - 1))

        # **Ordered by the group keys, and that is INV-6 rather than tidiness.**
        # `GROUP BY` alone returns groups in whatever order the engine produces
        # them, so the same fingerprint could hand back the same numbers in a
        # different arrangement — and the preview, the chart and the narration
        # all read the arrangement. It is the argument that chose exact
        # `median()` over `approx_quantile`: *almost* deterministic is not.
        #
        # By key rather than by measure: ranking is `sort_rows`' job, and a
        # default that ranked would be an opinion nobody asked for.
        keys = ", ".join(_quote(name) for name in groups)
        grouping = f" GROUP BY {keys} ORDER BY {keys}" if groups else ""
        table = execute(
            ctx.engine,
            ctx.handle,
            TableInput(
                sql=(
                    f"SELECT {', '.join(selected)} "  # noqa: S608
                    f"FROM {nest(source)} AS t{grouping}"
                ),
                columns=tuple(columns),
            ),
        )
        if (table.row_count or 0) > MAX_GROUPS:
            raise ToolError(
                f"grouping by {', '.join(groups)} produces {table.row_count:,} rows, "
                f"past the {MAX_GROUPS:,} a grouped result stays readable at; "
                f"cardinality_report says which columns are safe to group by"
            )

        covering = "the whole table" if not groups else f"one row per {', '.join(groups)}"
        return as_json(
            table,
            preview(ctx.engine, ctx.handle, table),
            f"{table.row_count:,} group(s), {covering}; values are grouped exactly as "
            f"they appear in the data",
            # Every row here is a count or an average over a group, not a row
            # out of the file. That is the difference between K4 and K2.
            derived=True,
            size_column=size,
        )

    def _measure(self, measure: str, lookup: dict[str, Any], ordinal: int) -> tuple[str, Any]:
        found = _MEASURE.match(measure)
        if found is None:
            raise ToolError(
                f"{measure!r} is not a measure; write it as function(column), "
                f"for example mean(Age) or count()"
            )
        function, column = found.group(1).lower(), found.group(2)

        entry = _AGGREGATES.get(function)
        if entry is None:
            raise ToolError(
                f"there is no aggregate called {function!r}. "
                f"Available: {', '.join(sorted(_AGGREGATES))}"
            )
        sql_name, logical, rows_not_values = entry

        if not column:
            if not rows_not_values:
                raise ToolError(f"{function} needs a column, as in {function}(Age)")
            return ('count(*) AS "count"', derived("count", logical, ordinal))

        spec = lookup.get(column)
        if spec is None:
            raise ToolError(f"no column named {column!r}; this table has: {', '.join(lookup)}")
        if function in _NEEDS_NUMBER and spec.logical_type is not LogicalType.NUMERICAL:
            raise ToolError(
                f"{function}({column}) needs a numerical column, and {column!r} is "
                f"{spec.logical_type.value}"
            )

        read = read_column(column, lookup)
        distinct = "DISTINCT " if function == "distinct_count" else ""
        label = f"{function}_{column}"
        return (
            f"{sql_name}({distinct}{read}) AS {_quote(label)}",
            derived(label, logical, ordinal),
        )


__all__ = ["MAX_GROUPS", "Aggregate"]
