"""`plot` — a Vega-Lite spec, and not one number of its own (§11.9, D-016).

## It composes; it does not compute

The numbers come from layer 1 and layer 2; the pixels are drawn in the browser.
This assembles the description in between and nothing else, which is what keeps
INV-5 true of a chart: every value in it was already a Computation before it
was a mark.

## Why `transform` is tier 3 and the model never sees it

Vega-Lite has its own transforms — `aggregate`, `bin`, `calculate`, `filter`,
`window`, `regression`, `loess` — and **every one of them computes a number**.
Passing them through would break INV-5 outright, and would do something worse
than one violation: it would create **two roads to the same aggregation**, one
fingerprinted as a Step and one hidden inside a chart spec, with no way to tell
from the answer which one produced the figure.

§11.9.2's rule, in one sentence: *anything that changes a value is a Step;
`transform` may only touch how a value is shown.* So two are allowed — the axis
order and bar stacking — and D-019 keeps the argument away from the model
entirely, because closing the door is cheaper than validating what comes
through it.

## Why it reads its columns instead of selecting them (v2)

Every column in a normalised Parquet file is physically VARCHAR, so `SELECT *`
hands Vega-Lite `Age: "22"` under an encoding that declares `quantitative`.
Vega coerces, so most charts looked right — and a value that will not coerce
becomes `NaN` and its point **disappears with nothing said**, which is the
silent-wrongness class this design exists to refuse. v2 reads each encoded
column through `read_column`, the same one `aggregate` and `profile_column`
use, so *what this column's values are* keeps one answer across the system.

Only the encoded columns are selected. `SELECT *` shipped 891 passenger names
and ticket numbers to draw a two-channel scatter; the trade is that a tooltip
now names what the chart encodes rather than the whole row, which is what the
chart is actually claiming.

## Why an axis type comes from the data, not from the logical type (v2)

`Pclass` is `numerical` because **D-068 decided it should be** — inference must
not read `1,2,3` as a label when it may be a count. Handed to Vega-Lite as
`quantitative` it produces an axis with ticks at 1.4 and 2.6, values that name
no class, and bars a pixel wide.

That is D-085 for a third time: *cardinality is the real constraint; the
logical type is only its proxy, and where proxy and fact differ, the fact
wins.* Here the fact is the **mark**: a bar chart's feet are labels and its
heights are magnitudes, so a numerical column is drawn `ordinal` in the first
and `quantitative` in the second. `mean_Fare` has three distinct values too,
and making that ordinal would turn a magnitude into a label.

A continuous axis under bars is a histogram, and a histogram declares itself
with `x_end` rather than being guessed at from a count of levels.

## Why it refuses instead of sampling

Past 5,000 rows this declines and names the way out. Sampling quietly would put
a chart next to a table where **the chart shows a different subset**, with
nothing on screen saying so — the silent-wrongness class this whole design
exists to refuse. And the seed would have to be chosen by somebody: choosing it
here hides a decision that changes the picture (INV-6). `sample_rows` as its
own Step makes that decision visible, recorded and repeatable.
"""

from __future__ import annotations

import os
from typing import Any

from app.domain.data import ColumnSpec, SchemaContract
from app.domain.enums import LogicalType
from app.expressions import read_column
from app.storage.engine import DuckDBEngine, _quote
from app.tools.contract import ExecContext, ToolError, tool
from app.tools.parameters import Param, validate
from app.tools.tables import BASE, SOURCE, TableInput, execute

#: §11.9.3, and the number comes from **readability rather than performance**.
#: Past roughly this many points a scatter is a blob; the ceiling sits where a
#: chart stops being readable, not where a browser stops coping. The second is
#: far higher and helps nobody.
MAX_ROWS = 5_000

#: §11.9.1. Four, and each absence has a reason: `arc` because the eye cannot
#: compare angles and this product promises readings that hold up; `boxplot`
#: because it is a composite mark and `profile_column` already prints the
#: quartiles; `area` because `line` says the same thing without adding visual
#: weight to a magnitude nobody meant.
MARKS = ("point", "bar", "line", "rect")

#: How a column's logical type is spelled in Vega-Lite, before the data gets
#: a say. `numerical` is the only one the count of levels can move (v2).
_ENCODING_TYPE: dict[LogicalType, str] = {
    LogicalType.NUMERICAL: "quantitative",
    LogicalType.CATEGORICAL: "nominal",
    LogicalType.TEXT: "nominal",
    LogicalType.BOOLEAN: "nominal",
    LogicalType.DATE: "temporal",
    LogicalType.UNSUPPORTED: "nominal",
}

#: The channels a caller may set, in the order Vega-Lite reads them.
_CHANNELS = ("x", "y", "color", "size", "facet")

#: Which channels carry a **measured quantity** for each mark; every other
#: channel carries a category (v2).
#:
#: This is the mark's own grammar written down. A bar's height is a magnitude
#: and its foot is a label; a heatmap's two axes are both labels and its colour
#: is the magnitude; a scatter's two axes are both magnitudes. `size` is always
#: a magnitude — the size of a category means nothing — and `facet` is always a
#: category, because a panel per value is a label by construction.
_MEASURE: dict[str, frozenset[str]] = {
    "bar": frozenset({"y", "size"}),
    "rect": frozenset({"color", "size"}),
    "point": frozenset({"x", "y", "size"}),
    "line": frozenset({"x", "y", "size"}),
}

#: How much room one band gets when an axis is discrete.
#:
#: Vega-Lite's own default is 20, which is enough for a tick and not for a
#: label like `South Sulawesi`. This is a readability number like `MAX_ROWS`,
#: not a performance one.
DISCRETE_STEP = 24

#: How much room one cell of a heatmap gets on a discrete axis.
#:
#: Larger than a bar's band because a cell is read in two directions at once:
#: a square you compare against its neighbours, rather than a length you read
#: off an axis.
HEATMAP_STEP = 32

#: The axis types that draw in bands rather than along a continuum.
_DISCRETE = frozenset({"nominal", "ordinal"})

#: How many categories a channel can carry before the chart stops being one.
#:
#: Two numbers because the channels fail differently. An axis runs out of room
#: for labels; a legend runs out of colours long before that, and D-042 already
#: measured how few distinguishable hues exist — the eight it pinned are 29.2°
#: apart at their closest, and *a ninth hue probably does not exist*. A facet is
#: held to the legend's number for a plainer reason: twelve panels is already a
#: page, and fifty is a scroll.
MAX_AXIS_LEVELS = 50
MAX_LEGEND_LEVELS = 12


@tool(category="visual", output_kind="chart_spec")
class Plot:
    """*"Draw it."* — one chart from a table that already exists (§11.9)."""

    name = "plot"
    #: v3 — reads its columns, lets the mark choose the axis type, and lays a
    #: bar of named things on its side. Each changes the spec, so INV-4 says
    #: every cached chart is invalid.
    version = 3
    summary = "Draw a table that already exists as a point, bar, line or heatmap chart"

    parameters = (
        Param(
            name="table",
            tier=2,
            description=(
                "Which table to draw: 'dataset', or the id of an earlier step. "
                "Charts are usually drawn from an aggregate or a bin, not from raw rows."
            ),
            kind="table",
            default=BASE,
        ),
        Param(
            name="mark",
            tier=1,
            description=(
                "The kind of chart: 'point' for a scatter, 'bar' for a histogram or bar "
                "chart, 'line' for a trend over an ordered axis, 'rect' for a heatmap. "
                "A heatmap shows its numbers as colour, so give it a color column too."
            ),
            kind="enum",
            choices=MARKS,
        ),
        Param(name="x", tier=1, description="The column along the bottom.", kind="column"),
        Param(
            name="y",
            tier=2,
            description=(
                "The column up the side. A bar, line or heatmap needs one; for a bar "
                "chart of counts, run aggregate first and plot its count column."
            ),
            kind="column",
            optional=True,
        ),
        Param(
            name="x_end",
            tier=2,
            description=(
                "For a table that is already binned, the column holding each band's "
                "upper edge; set x to the lower edge. This draws a histogram with "
                "bands that touch. Use it with the output of bin_column: "
                "x=lower, x_end=upper, y=count."
            ),
            kind="column",
            optional=True,
        ),
        Param(
            name="color",
            tier=2,
            description="A column to colour by.",
            kind="column",
            optional=True,
        ),
        Param(
            name="size",
            tier=2,
            description="A column to size points by. Only meaningful for 'point'.",
            kind="column",
            optional=True,
        ),
        Param(
            name="facet",
            tier=2,
            description="A column to split the chart into one panel per value.",
            kind="column",
            optional=True,
        ),
        Param(
            name="transform",
            tier=3,
            description=(
                "A visual-only transform: 'sort' orders the axis by value, 'stack' stacks "
                "bars. Nothing that changes a number is available here."
            ),
            kind="enum",
            default="none",
            choices=("none", "sort", "stack"),
        ),
    )

    def applies_to(self, contract: SchemaContract) -> bool:
        """Anything with columns can be drawn; whether it is small enough is a
        question about the *table*, and `applies_to` is handed the dataset."""
        return bool(contract.columns)

    def args(self, **given: Any) -> dict[str, Any]:
        return validate(self.name, self.parameters, given)

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(ctx.engine, DuckDBEngine):  # pragma: no cover - one engine ships
            raise ToolError("plot needs the DuckDB engine")

        source = execute(ctx.engine, ctx.handle, ctx.source)
        rows = source.row_count or 0
        if rows > MAX_ROWS:
            # §11.9.3, and P6: name the way out rather than failing bare.
            raise ToolError(
                f"{rows:,} rows is too many to draw. Use sample_rows(n={MAX_ROWS}) first, "
                f"or aggregate to summarise it."
            )

        lookup = {spec.name: spec for spec in source.columns}
        mark = args["mark"]
        fields: dict[str, str] = {}
        for channel in _CHANNELS:
            named = args.get(channel)
            if not named:
                continue
            if named not in lookup:
                raise ToolError(f"no column named {named!r}; this table has: {', '.join(lookup)}")
            fields[channel] = named

        end = args.get("x_end") or ""
        if end and end not in lookup:
            raise ToolError(f"no column named {end!r}; this table has: {', '.join(lookup)}")

        self._check(mark, fields, binned=bool(end))

        # **Values first, types second.** The count of levels decides an axis,
        # and the rows are already here — so it costs nothing beyond the query
        # that was going to run anyway.
        values = self._values(
            ctx, source, lookup, sorted(set(fields.values()) | ({end} if end else set()))
        )

        channels: dict[str, dict[str, Any]] = {}
        for channel, named in fields.items():
            measure = channel in _MEASURE[mark]
            if not measure:
                self._readable(channel, named, len({row.get(named) for row in values}))
            channels[channel] = {
                "field": named,
                "type": self._encoding(lookup[named], measure=measure),
            }

        if end:
            # **`bin: "binned"` is Vega-Lite being told the binning already
            # happened.** It is not a transform and computes nothing: it says
            # *this field is a band's lower edge and x2 is its upper*, so the
            # bars span their band instead of standing as hairlines on a
            # continuous axis. §11.9.2's line holds — nothing here changes a
            # value, only how wide it is drawn.
            channels["x"]["bin"] = "binned"
            # **Back to the declared type, past the cardinality rule.** A ten
            # band histogram has ten distinct lower edges, which is under the
            # discrete threshold — and an ordinal axis cannot carry a band that
            # spans a range. A date histogram stays `temporal` here rather than
            # becoming `quantitative`, which is why this reads the map instead
            # of naming a type.
            channels["x"]["type"] = _ENCODING_TYPE[lookup[fields["x"]].logical_type]
            # **Titled by its own field.** Vega-Lite composes a binned axis
            # title from `x` and `x2` together, so a histogram came out
            # labelled `lower, upper` — the machinery rather than the
            # quantity. `bin_column` names the lower edge after the column it
            # cut, so the field on the axis already *is* the answer.
            channels["x"]["title"] = _binned_title(fields["x"], end)
            channels["x2"] = {"field": end}

        spec_size: dict[str, Any] = {}
        # **A discrete axis is a stack of bands and needs room per band.**
        # Vega-Lite's own default of 20px fits a tick, not `South Sulawesi`,
        # and a heatmap drawn at that size is a postage stamp — which is what
        # a crosstab of eight by three looked like.
        if mark == "rect":
            if channels.get("x", {}).get("type") in _DISCRETE:
                spec_size["width"] = {"step": HEATMAP_STEP}
            if channels.get("y", {}).get("type") in _DISCRETE:
                spec_size["height"] = {"step": HEATMAP_STEP}

        if _lies_down(mark, channels, binned=bool(end)):
            # **A bar of named things reads down the page, not across it.**
            # Eight regions on a vertical axis turn their labels ninety
            # degrees, and a label you tilt your head for is a label the chart
            # is making you work for. Swapping the two encodings is the whole
            # of it: the roles were already decided above, so what changes is
            # which side of the plot each one sits on.
            #
            # Only `nominal` — a set of names has no order to read left to
            # right, so stacking it downward loses nothing. An `ordinal` axis
            # does have one (`rating` runs 1 to 5) and a `temporal` axis is an
            # arrow; both stay upright.
            channels["x"], channels["y"] = channels["y"], channels["x"]
            # Discrete bands need room of their own, or lying down trades a
            # cramped set of labels for a cramped set of bars.
            spec_size["height"] = {"step": DISCRETE_STEP}

        if args["transform"] == "sort" and "y" in channels:
            channels["x"]["sort"] = "-y"
        if args["transform"] == "stack" and "y" in channels:
            channels["y"]["stack"] = "zero"

        return {
            "spec": {
                "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
                "mark": {"type": mark, "tooltip": True},
                **spec_size,
                "encoding": channels,
                # **Values inline.** The ceiling is what makes it affordable,
                # and it makes the chart self-contained: a spec that pointed at
                # a URL would be a second way to reach data, outside INV-7.
                "data": {"values": values},
            },
            "mark": mark,
            "encoding": {channel: str(entry["field"]) for channel, entry in channels.items()},
            "row_count": rows,
            "note": (
                f"{args['mark']} chart of {rows:,} row(s); "
                f"every value in it came from the step this reads"
            ),
        }

    @staticmethod
    def _check(mark: str, channels: dict[str, str], *, binned: bool = False) -> None:
        """The combinations that produce a chart nobody can read.

        Refused rather than drawn, for the reason `arc` is absent: a chart that
        cannot be read honestly is worse than no chart, because it is still
        read.
        """
        if mark == "rect" and "y" not in channels:
            raise ToolError("a heatmap needs both x and y; give it a y column")
        if mark == "rect" and "color" not in channels:
            # **Colour is the measure on a heatmap, not decoration.** Without
            # it every cell is drawn the same, and a grid of identical blocks
            # says only *these combinations exist* — which the axes already
            # said. Observed on screen: eight regions by three channels, all
            # one blue, no legend.
            raise ToolError(
                "a heatmap shows its numbers as colour, so it needs a color column; "
                "aggregate(group_by=[<x>, <y>], measures=['count()']) produces one "
                "called count"
            )
        if mark == "line" and "y" not in channels:
            raise ToolError("a line needs something to plot up the side; give it a y column")
        if mark == "bar" and "y" not in channels:
            # **A bar with no height is not a chart with a default; it is 891
            # zero-height bars.** The parameter used to promise a "count-style
            # bar chart" here, which this tool cannot draw: counting is a
            # number, so the only way Vega-Lite could supply it is a transform,
            # and §11.9.2 forbids exactly that. P6 — name the way out.
            raise ToolError(
                "a bar needs something to plot up the side; for counts, run "
                "aggregate(group_by=[...], measures=['count()']) first and plot its "
                "count column"
            )
        if "size" in channels and mark != "point":
            raise ToolError(f"size is only meaningful on a point chart, not on a {mark}")
        if binned and mark != "bar":
            raise ToolError(f"x_end draws a histogram, which needs mark='bar', not {mark!r}")
        if binned and "x" not in channels:
            raise ToolError("x_end is the upper edge of a band; give x the lower edge too")

    @staticmethod
    def _readable(channel: str, named: str, levels: int) -> None:
        """A category channel that has more values than it can show.

        Refused rather than drawn, for the reason `arc` is absent from `MARKS`:
        a chart that cannot be read honestly is worse than no chart, because it
        is still read. `plot(mark="bar", x="Name")` on Titanic draws 891 bars
        one row high and calls itself a distribution.

        P6 — and the way out is the answer to the question the caller was
        really asking. *Which are the common ones* is a top-N, and a top-N is
        `sort_rows` then `limit_rows`; a continuous quantity that arrived here
        as a category wants `bin_column` instead.
        """
        ceiling = MAX_AXIS_LEVELS if channel in ("x", "y") else MAX_LEGEND_LEVELS
        if levels <= ceiling:
            return
        raise ToolError(
            f"{named!r} has {levels:,} distinct values, too many for {channel} to show "
            f"(at most {ceiling}). For the common ones, sort_rows by the count and "
            f"limit_rows to the top few; for a continuous quantity, bin_column first."
        )

    @staticmethod
    def _encoding(spec: ColumnSpec, *, measure: bool) -> str:
        """How Vega-Lite should read this column in this channel (v2).

        **A category channel is discrete, and that is the mark's own claim
        rather than a threshold.** A bar chart's feet are labels — that is what
        makes it a bar chart — so a numerical column standing there is drawn
        `ordinal` however many levels it has. Left continuous it produces the
        axis D-085 was about: ticks at 1.4 and 2.6, naming no class, with the
        bars a pixel wide.

        A continuous x under bars is a **histogram**, and a histogram says so
        with `x_end`, which puts the type back where the column declared it.

        `ordinal` rather than `nominal` for a numerical or a date, because the
        order is real: classes 1, 2, 3 are ranked, and a nominal scale would be
        free to draw them in any order it liked.

        Nothing bounds this by counting, because the ceilings already do: a
        category channel past `_readable` has few enough levels to draw.
        """
        declared = _ENCODING_TYPE[spec.logical_type]
        if measure:
            return declared
        return "ordinal" if declared in ("quantitative", "temporal") else declared

    @staticmethod
    def _values(
        ctx: ExecContext,
        source: TableInput,
        lookup: dict[str, ColumnSpec],
        wanted: list[str],
    ) -> list[dict[str, Any]]:
        """Every row of the table, in the columns the chart encodes (v2).

        **Read through `read_column`, not selected raw.** A column out of the
        Parquet file is VARCHAR, so a raw select declares `quantitative` over
        `"22"` and leaves Vega-Lite to coerce — which it does, until a value
        that will not coerce turns into `NaN` and takes its mark off the chart
        without a word. A column an earlier step computed is already typed, and
        `read_column` knows not to read it twice.

        Whole rather than paged: the ceiling above already guarantees there are
        few enough, and a chart drawn from part of a table without saying so is
        the thing §11.9.3 refuses.
        """
        assert isinstance(ctx.engine, DuckDBEngine)
        selected = ", ".join(f"{read_column(name, lookup)} AS {_quote(name)}" for name in wanted)
        query = source.sql.replace(SOURCE, "?")
        cursor = ctx.engine._cursor().execute(
            f"SELECT {selected} FROM ({query}) AS t LIMIT {MAX_ROWS}",  # noqa: S608
            [ctx.engine._source(ctx.handle)],
        )
        names = [str(column[0]) for column in (cursor.description or ())]
        return [
            {name: _plain(value) for name, value in zip(names, row, strict=True)}
            for row in cursor.fetchall()
        ]


def _lies_down(mark: str, channels: dict[str, dict[str, Any]], *, binned: bool) -> bool:
    """Whether this bar chart should be drawn on its side.

    A bar whose feet are **names** — regions, statuses, true and false — reads
    as a list, and a list runs down a page. Drawn upright those names turn
    ninety degrees, which is the state this rule exists to leave.

    Three things keep it narrow. Only `bar`, because a scatter has no feet and
    a heatmap's axes are both labels. Never a histogram (`binned`), whose axis
    is a continuous quantity in its natural direction. And only `nominal`: an
    `ordinal` axis is an ordered scale that reads left to right, and a
    `temporal` axis is an arrow — turning either of those sideways would be
    rearranging a fact rather than a label.
    """
    if mark != "bar" or binned:
        return False
    if "x" not in channels or "y" not in channels:
        return False
    return bool(channels["x"]["type"] == "nominal")


def _binned_title(x: str, end: str) -> str:
    """What a band's two edges agree they are.

    Vega-Lite composes a binned axis title from `x` and `x2` together, which
    produced `lower, upper` — the machinery rather than the quantity. The pair
    names the same column twice with different suffixes, so what they share
    *is* the answer: `amount_from` and `amount_to` agree on `amount`.

    Falls back to the x field when they agree on nothing, which is the honest
    answer for a table this system did not bin.
    """
    shared = os.path.commonprefix([x, end]).rstrip("_")
    return shared or x


def _plain(value: Any) -> Any:
    """A value JSON can hold, without deciding what it means.

    Numbers stay numbers so a quantitative axis works; everything else becomes
    a string, because a `Decimal` or a `date` in a spec is a serialisation
    question and not a charting one.
    """
    if value is None or isinstance(value, bool | int | float):
        return value
    return str(value)


__all__ = [
    "DISCRETE_STEP",
    "MARKS",
    "MAX_AXIS_LEVELS",
    "MAX_LEGEND_LEVELS",
    "MAX_ROWS",
    "Plot",
]
