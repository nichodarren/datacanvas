"""The reading behind `crosstab` (§11.4, `matrix`).

## Long-form, not a grid of grids

§11.4.1 settled this: `matrix` is table-backed, stored as `(row, column,
value)`, and that is what makes `crosstab -> plot(mark="rect")` a heatmap for
free. A nested `{female: {0: 81, 1: 233}}` would render the same and would not
compose with anything.

## Missing values are excluded, and the exclusion is reported

A blank is not a category (§FR-B.3, and the same `_PRESENT` rule the whole
system uses). Rows where either column is empty are dropped from the counts and
counted separately, because a crosstab that quietly summed to less than the
table would have every share computed against the wrong denominator.

## Why both axes are capped

Two columns of 500 categories is 250,000 cells, which is not a table anybody
reads and is a payload nothing should carry. The cap keeps the commonest
levels, and `omitted_rows`/`omitted_columns` say how many did not fit — a
truncated result that does not say it was truncated is the failure mode the
Privacy Gate's `Filtered` exists to avoid, and it applies just as much here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.domain.data import SchemaContract
from app.storage.engine import DuckDBEngine, EngineError, _quote

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle

#: How many levels each axis keeps. 50 x 50 is 2,500 cells, which is already
#: past what a person reads and well short of what a payload cannot carry.
MAX_LEVELS = 50


@dataclass(frozen=True, slots=True)
class Cell:
    """One combination, its count, and **every** share of it.

    All three, whatever `normalize` said, and that is not redundancy. A reader
    asking *how does survival break down by sex* means the row share; a reader
    asking *where did the survivors come from* means the column share; and a
    narration handed only one of them will work the other out by dividing --
    which §12.1 forbids and the citation check catches, correctly, on a
    sentence that was true.

    Observed live: three complaints on one right answer, because the bundle
    held counts and the model needed percentages.
    """

    row: str
    column: str
    count: int
    #: The share `normalize` selected. Kept as its own field because it is what
    #: a chart encodes, and a chart should not have to know which of the three
    #: it was asked for.
    value: float
    #: Of this cell's row, of its column, and of the whole table.
    row_share: float = 0.0
    column_share: float = 0.0
    total_share: float = 0.0


@dataclass(frozen=True, slots=True)
class Matrix:
    """A labelled grid, long-form, with what it left out."""

    row_column: str
    column_column: str
    normalize: str
    rows: tuple[str, ...]
    columns: tuple[str, ...]
    cells: tuple[Cell, ...]
    counted: int
    #: Rows where either column was empty. Excluded from every count above.
    incomplete: int = 0
    omitted_rows: int = 0
    omitted_columns: int = 0

    def as_json(self) -> dict[str, object]:
        """The bundle as JSONB holds it, kept beside the shape it serialises."""
        return {
            "row_column": self.row_column,
            "column_column": self.column_column,
            "normalize": self.normalize,
            "rows": list(self.rows),
            "columns": list(self.columns),
            "cells": [
                {
                    "row": cell.row,
                    "column": cell.column,
                    "count": cell.count,
                    "value": cell.value,
                    "row_share": cell.row_share,
                    "column_share": cell.column_share,
                    "total_share": cell.total_share,
                }
                for cell in self.cells
            ],
            "counted": self.counted,
            "incomplete": self.incomplete,
            "omitted_rows": self.omitted_rows,
            "omitted_columns": self.omitted_columns,
        }


class CrosstabReader:
    """Counts one pair of categorical columns against each other."""

    def __init__(self, engine: DuckDBEngine) -> None:
        self._engine = engine

    def crosstab(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        a: str,
        b: str,
        normalize: str = "none",
    ) -> Matrix:
        del contract  # the caller has already decided these columns are axes
        known = {column.name for column in self._engine.columns(handle)}
        for name in (a, b):
            if name not in known:
                raise EngineError(f"no column named {name!r} in this dataset")

        left, right = _quote(a), _quote(b)
        # The same definition of *present* as everywhere else: a blank string
        # is not a value (FR-B.3), so it is not a level either.
        filled = " AND ".join(
            f"({side} IS NOT NULL AND trim({side}) <> '')" for side in (left, right)
        )
        present = f"({filled})"

        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT trim(CAST({left} AS VARCHAR)), trim(CAST({right} AS VARCHAR)), count(*) "  # noqa: S608
                f"FROM read_parquet(?) WHERE {present} GROUP BY 1, 2 ORDER BY 1, 2",
                [self._engine._source(handle)],
            )
            .fetchall()
        )
        incomplete = self._incomplete(handle, present)

        counts = {(str(row), str(column)): int(count) for row, column, count in rows}
        row_levels, omitted_rows = self._levels(counts, index=0)
        column_levels, omitted_columns = self._levels(counts, index=1)

        kept = {
            key: count
            for key, count in counts.items()
            if key[0] in set(row_levels) and key[1] in set(column_levels)
        }
        counted = sum(kept.values())

        return Matrix(
            row_column=a,
            column_column=b,
            normalize=normalize,
            rows=row_levels,
            columns=column_levels,
            cells=_cells(kept, row_levels, column_levels, normalize, counted),
            counted=counted,
            incomplete=incomplete,
            omitted_rows=omitted_rows,
            omitted_columns=omitted_columns,
        )

    def levels(self, handle: DataHandle, name: str) -> int:
        """How many distinct values a column holds, for deciding if it is an axis.

        A count rather than the values: the caller is asking whether the column
        is small enough to be a dimension, and reading the values to answer
        that would be reading data to make a metadata decision.
        """
        column = _quote(name)
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(DISTINCT trim(CAST({column} AS VARCHAR))) "  # noqa: S608
                f"FROM read_parquet(?) WHERE {column} IS NOT NULL AND trim({column}) <> ''",
                [self._engine._source(handle)],
            )
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("distinct count returned nothing")
        return int(row[0])

    def _incomplete(self, handle: DataHandle, present: str) -> int:
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*) FILTER (WHERE NOT {present}) FROM read_parquet(?)",  # noqa: S608
                [self._engine._source(handle)],
            )
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("crosstab returned nothing")
        return int(row[0])

    @staticmethod
    def _levels(counts: dict[tuple[str, str], int], *, index: int) -> tuple[tuple[str, ...], int]:
        """The commonest levels on one axis, and how many did not fit.

        Ranked by total count and then by name: ties broken by anything else
        would make the same data produce a different matrix on a different run,
        and INV-6 does not bend for ordering.
        """
        totals: dict[str, int] = {}
        for key, count in counts.items():
            totals[key[index]] = totals.get(key[index], 0) + count
        ranked = sorted(totals, key=lambda level: (-totals[level], level))
        return (tuple(sorted(ranked[:MAX_LEVELS])), max(0, len(ranked) - MAX_LEVELS))


def _cells(
    counts: dict[tuple[str, str], int],
    rows: tuple[str, ...],
    columns: tuple[str, ...],
    normalize: str,
    counted: int,
) -> tuple[Cell, ...]:
    """Every combination, including the ones that never happened.

    A cell missing from the result and a cell holding zero read identically to
    a chart and differently to a person: the first looks like a gap in the
    query, the second is a fact about the data. Dense beats sparse here.
    """
    row_totals = {row: sum(counts.get((row, col), 0) for col in columns) for row in rows}
    column_totals = {col: sum(counts.get((row, col), 0) for row in rows) for col in columns}

    def share(count: int, denominator: int) -> float:
        # Four places, so `share * 100` lands on exactly two and a narration
        # quoting `18.89` matches the number it was given rather than passing
        # on a tolerance.
        return 0.0 if denominator <= 0 else round(count / denominator, 4)

    cells = []
    for row in rows:
        for column in columns:
            count = counts.get((row, column), 0)
            of_row = share(count, row_totals[row])
            of_column = share(count, column_totals[column])
            of_all = share(count, counted)
            selected = {
                "row": of_row,
                "column": of_column,
                "all": of_all,
            }.get(normalize, float(count))
            cells.append(
                Cell(
                    row=row,
                    column=column,
                    count=count,
                    value=selected,
                    row_share=of_row,
                    column_share=of_column,
                    total_share=of_all,
                )
            )
    return tuple(cells)


__all__ = ["MAX_LEVELS", "Cell", "CrosstabReader", "Matrix"]
