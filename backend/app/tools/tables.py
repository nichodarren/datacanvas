"""What a transform reads, and what it hands to the next one (§11.4 layer 1).

## Intermediates are not materialised, and that is a decision

§11.4 says a transform's output is a table and that transforms compose. The
obvious reading is that each one writes a Parquet file somewhere — the URI
layout already reserves `artifacts/{computation_id}/` for it — and the next one
reads it.

**This does not do that.** A transform's Computation stores the *query* that
produces its table, and the transform after it wraps that query. `filter →
derive → aggregate` is one nested SELECT executed once at the end.

What that buys:

* **no artifact table, no migration, no orphan files.** A materialised
  intermediate outlives the question that produced it, and something then has
  to decide when to delete it — a retention policy nobody has written and a
  class of bug (the file is gone, the Computation is not) that cannot happen
  if there is no file;
* every intermediate is **still a Computation** with a real fingerprint, a real
  parent, and a real row count. Nothing about the Run Log or INV-5 is deferred.

What it costs, stated: the terminal step re-executes the whole chain, so a
five-step chain over five million rows scans five million rows once per
*terminal* query rather than once per step. Against materialising, first-run
cost is the same and re-running a chain is slower. That is the right trade
while chains are short and the alternative is a storage lifecycle.

**And it is a stepping stone, not a dead end.** When `artifact` lands, a
transform materialises instead of nesting and nothing above it changes: the
result keeps the same shape and the parent link is already there.

## Why the stored query has no path in it

`@@source@@` stands where the Parquet path goes, and the path is substituted as
a **bound parameter** at execution. The stored SQL therefore carries no
filesystem layout — it is written to Postgres, returned over HTTP, and would
otherwise tell every reader where this tenant's bytes live.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.domain.data import ColumnSpec, SchemaContract
from app.domain.enums import LogicalType
from app.storage.engine import EngineError

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle
    from app.storage.engine import DuckDBEngine

#: Where the Parquet path goes. Replaced with `?` at execution and bound, never
#: interpolated (NFR-SEC.3).
SOURCE = "@@source@@"

#: What `table` means when nobody named one. Single-table MVP (§9.6), so the
#: base dataset is the only thing it could sensibly be — which is why this is
#: a tier-2 argument with a default rather than the tier-1 §11.4 sketches.
#: `table_ref` stays in the vocabulary for the day there is a second table.
BASE = "dataset"

#: Rows a transform keeps as a preview of its own output. They are raw values,
#: so they are K4 and the Privacy Gate has the last word on whether any of them
#: reach a model; this only bounds what the bundle stores.
PREVIEW_ROWS = 10


@dataclass(frozen=True, slots=True)
class TableInput:
    """One table, as the tool about to read it needs to see it."""

    #: A `SELECT` producing this table, with `SOURCE` where the path goes.
    sql: str
    #: The schema of *this* table, which after `derive_column` is not the
    #: schema of any contract. Expressions resolve against this.
    columns: tuple[ColumnSpec, ...]
    row_count: int | None = None
    #: Whether these rows were computed rather than read out of the file.
    #:
    #: **A property of the chain, not of the tool holding it.** `limit_rows`
    #: over the dataset holds five people; `limit_rows` over an aggregate holds
    #: five group averages, and the same tool produced both. Marking it on the
    #: tool sent the second one through the K4 door, where the gate withheld it
    #: — so a model was shown a ranking it could not read, cited it, and had
    #: five correct figures called unsupported.
    derived: bool = False
    #: Which column says how many source rows each row stands for, if any, so
    #: PG-1 survives a `sort_rows` or a `limit_rows` over an aggregate.
    size_column: str | None = None
    #: Whether the row order carries meaning because a step chose it.
    #:
    #: Carried for the same reason as `derived`: a tool cannot see it by
    #: looking at rows. `limit_rows` over an ordered table is a top-n and keeps
    #: the ordering; `sample_rows` over one throws it away, which is why it is
    #: the only reader that refuses.
    ordered: bool = False

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(spec.name for spec in self.columns)

    def column(self, name: str) -> ColumnSpec | None:
        return next((spec for spec in self.columns if spec.name == name), None)


def base_table(contract: SchemaContract) -> TableInput:
    """The dataset itself, as a table a transform can read."""
    return TableInput(
        # module constant and the path never appears in this string at all.
        sql=f"SELECT * FROM read_parquet({SOURCE})",  # noqa: S608
        columns=tuple(sorted(contract.columns, key=lambda spec: spec.ordinal)),
    )


#: What a derived column is physically, by what it logically holds. This is
#: what tells `read_column` not to run the file's shape rules over a value the
#: system computed itself.
_PHYSICAL: dict[LogicalType, str] = {
    LogicalType.NUMERICAL: "DOUBLE",
    LogicalType.TEXT: "DERIVED_TEXT",
    LogicalType.CATEGORICAL: "DERIVED_TEXT",
    LogicalType.BOOLEAN: "BOOLEAN",
    LogicalType.DATE: "TIMESTAMP",
    LogicalType.UNSUPPORTED: "DERIVED_TEXT",
}


def derived(name: str, logical: LogicalType, ordinal: int) -> ColumnSpec:
    """A column that exists because a transform made it.

    `detection_reason` says so rather than being left blank: a column in a
    result that no schema inference ever saw should say where it came from,
    and *derived by a tool* is the honest answer.

    `physical_type` is real rather than empty, and it carries a decision:
    `DERIVED_TEXT` rather than `VARCHAR` so that `read_column` can tell a
    string **out of the file** from a string **this system computed**. The
    first needs the shape rules; running them over the second is a category
    error, and one that raises rather than answering wrongly.
    """
    return ColumnSpec(
        name=name,
        ordinal=ordinal,
        physical_type=_PHYSICAL[logical],
        logical_type=logical,
        null_markers=(),
        detection_confidence=1.0,
        detection_reason="derived by a tool",
        overridden_by=None,
    )


def as_json(
    table: TableInput,
    preview: dict[str, Any],
    note: str = "",
    *,
    derived: bool = False,
    size_column: str | None = None,
    ordered: bool = False,
) -> dict[str, Any]:
    """The bundle a transform returns, kept beside the shape it serialises.

    `columns` is spelled `{name, logical_type}` deliberately: it is the shape
    `summarise`'s schema matcher already understands, so a model asking *what
    does this table hold now* is answered without teaching the planner a sixth
    shape.

    ## `derived` says whether these rows are the file's or the tool's

    The two are the same **shape** and a different **category**. `filter_rows`
    hands back rows out of the file — K4, and no model sees them outside
    `full`. `aggregate` and `bin_column` hand back rows the tool computed:
    counts and means over groups, which are K2/K3 and exactly what a narrator
    is supposed to read.

    A gate cannot tell those apart by looking, and guessing would either leak
    raw rows or blind the model to its own aggregates. It had been blinding
    them: every transform's preview was dropped, so a model that binned `Age`
    was shown four column names and a row count and **not one band**, and went
    looking for the values with `sample_rows` until the step budget ran out.
    So the tool says which it produced, because the tool is the only thing that
    knows.

    ## `ordered` says the row order was chosen rather than incidental

    `sort_rows` is the only tool that sets it and `sample_rows` is the only one
    that reads it, to refuse. Everything in between passes it along, because a
    ranking filtered or trimmed is still a ranking.

    ## `size_column` names how many rows each row stands for

    PG-1 suppresses a group too small to be anonymous, and it needs to know
    which column holds the group size. Sniffing for a column called `count`
    would read a *group key* named `count` as a size, so the tool names it —
    the same reason `derived` exists. `None` means there is no such column, and
    the gate then withholds the rows rather than guessing they are safe.
    """
    return {
        "sql": table.sql,
        "columns": [
            {"name": spec.name, "logical_type": spec.logical_type.value} for spec in table.columns
        ],
        "row_count": table.row_count,
        "preview": {
            **preview,
            "derived": derived,
            "size_column": size_column,
            "ordered": ordered,
        },
        "note": note,
    }


#: What an expression's type means as a column's logical type. `null` has no
#: honest answer -- an expression that is only ever null describes no column --
#: so it lands on `unsupported`, which is the vocabulary's own word for *there
#: is nothing here to read*.
AS_LOGICAL: dict[str, LogicalType] = {
    "number": LogicalType.NUMERICAL,
    "text": LogicalType.TEXT,
    "boolean": LogicalType.BOOLEAN,
    "date": LogicalType.DATE,
    "null": LogicalType.UNSUPPORTED,
}


def nest(table: TableInput) -> str:
    """The input as a subquery, ready to be wrapped.

    A function rather than an f-string at eight call sites, so the one place
    that decides how a chain is spelled is one place.
    """
    return f"({table.sql})"


def execute(engine: DuckDBEngine, handle: DataHandle, table: TableInput) -> TableInput:
    """Run the query, and hand back the same table knowing how big it is.

    Two statements rather than one, because `count(*)` over a nested SELECT and
    the first ten rows of it are different questions and DuckDB answers each
    better on its own.

    **The path is bound, never interpolated.** `SOURCE` is replaced with `?`
    here and the value is passed as a parameter, which is why the stored SQL
    can be written to Postgres and returned over HTTP without carrying this
    tenant's filesystem layout with it.
    """
    path = engine._source(handle)
    query = table.sql.replace(SOURCE, "?")
    row = engine._cursor().execute(f"SELECT count(*) FROM ({query})", [path]).fetchone()  # noqa: S608
    if row is None:  # pragma: no cover - an aggregate always returns a row
        raise EngineError("a transform returned nothing")
    return TableInput(sql=table.sql, columns=table.columns, row_count=int(row[0]))


def preview(engine: DuckDBEngine, handle: DataHandle, table: TableInput) -> dict[str, Any]:
    """The first rows of a table, for a person to look at.

    Raw values, so K4 — the Privacy Gate decides whether any of them reach a
    model, and `summarise` drops a list of lists by default anyway. This is for
    the screen.
    """
    path = engine._source(handle)
    query = table.sql.replace(SOURCE, "?")
    cursor = engine._cursor().execute(
        f"SELECT * FROM ({query}) LIMIT {PREVIEW_ROWS}",  # noqa: S608
        [path],
    )
    names = [str(column[0]) for column in (cursor.description or ())]
    rows = [[None if value is None else str(value) for value in row] for row in cursor.fetchall()]
    return {"columns": names, "rows": rows}


__all__ = [
    "AS_LOGICAL",
    "BASE",
    "PREVIEW_ROWS",
    "SOURCE",
    "TableInput",
    "as_json",
    "base_table",
    "derived",
    "execute",
    "nest",
    "preview",
]
