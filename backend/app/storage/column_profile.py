"""One column, in depth (§11.7) — what `describe_dataset` deliberately is not.

§11.7.5 draws the line and it is the whole reason two readers exist. The Profile
tab profiles **every** column and has to be cheap enough to open on a 60-column
file inside NFR-PERF.2's two seconds, so it takes one pass and computes what one
pass affords. This computes **one** column and is allowed to be slow, because
nobody opens it until they have already decided which column they care about.

## What this deliberately does not compute

**Multimodality**, which §11.7.3 lists for numeric columns. It belongs to
`distribution_shape` (§11.4, P1) — a tool whose entire job is *"what shape is
this distribution"* — and computing it here would make two tools answer one
question, which §11.5 warns makes the LLM hesitate between them.

**Kurtosis was in this list until D-051 and is not any more, because the line
was drawn in the wrong place.** The argument above is sound and it was applied
to the wrong pair: skewness and kurtosis are the third and fourth standardised
moments, and splitting a pair across two tools is an arbitrary boundary rather
than a principled one — especially with skewness already on this side of it.
The boundary that holds is **moments here, tests and mode-counting there**:
`profile_column` reports what the distribution *is*, `distribution_shape`
reports what it *passes* — normality, dip, how many peaks.

**Gaps in a date range.** It needs a calendar join over the span, and the
timeline histogram already shows a hole as an empty bar.

Both are omissions of scope, not of care, and the owner asked for the profile to
be *"sesuaikan dengan MVP"*.

## Two things in §11.7 that were already dead when this was written

**§11.7.6(d)** — *"peringatan kualitas adalah bagian dari profil"* — and the
`warnings[]` field in §11.7.2's output shape. **D-041** revoked every quality
code product-wide; §11.7.4 is a draft with nothing implemented. There is no
`warnings` here, and the narrative in §11.7.7 loses its last line.

**§11.7.6(b)** — *"profil adalah Step"*. Narrowed at the owner's direction: a
profile opened from the Profile tab produces a **Computation** — cached,
fingerprinted, citable, invalidated by a schema change — but **not a Step**, so
it never lands in the Run Log. Browsing twelve columns is orientation, not
analysis, and twelve *"I looked at a column"* entries would bury the surface
that FR-H calls the primary one.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.authz.data_access import DataHandle
from app.domain.enums import LogicalType
from app.storage.engine import DuckDBEngine, EngineError
from app.storage.profile import (
    _AS_MOMENT,
    _AS_NUMBER,
    _FALSE_WORDS,
    _PRESENT,
    _TRIM,
    _TRUE_WORDS,
    Bin,
    TopValue,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle at runtime, not at type time
    from app.domain.data import SchemaContract

#: Quantiles §11.7.2 fixes as the default. Written out rather than derived: they
#: are part of the tool's argument surface, so a caller can name them and a
#: fingerprint can tell two choices apart.
QUANTILES = (0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99)

#: The multiplier on the IQR that decides an outlier. Tukey's 1.5, and it is an
#: argument rather than a constant everywhere else in this product for a reason
#: — §11.7.6 wants the rule visible, not magic. Here it is fixed because the
#: panel states it in words beside the count.
IQR_K = 1.5

#: How many values at each end §11.7.3 asks for.
EXTREMES = 5

#: A category with fewer rows than this is "rare" (§11.7.3).
RARE_BELOW = 5

#: The cyclic domains, in the order they are read rather than the order they
#: sort. `isodow` runs 1 to 7 from Monday and `month` 1 to 12 from January, so
#: index into each of these plus its base is the number DuckDB returns.
_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)
_HOURS = tuple(f"{hour:02d}" for hour in range(24))


def _tokens(name: str) -> str:
    """The token array for one value: split on non-alphanumerics, lowercased.

    **And nothing else** (D-071). No stopword list, no stemming, no language —
    a stopword list *is* a language, and the product has no notion of one, so
    the honest choice is to remove nothing rather than to nail an English list
    into a profiler that will meet Indonesian text on its first real dataset.
    """
    trimmed = _fit(_TRIM, name)
    return f"list_filter(regexp_split_to_array(lower({trimmed}), '[^a-z0-9]+'), x -> length(x) > 0)"


def _sequence(grain: str, earliest: datetime, latest: datetime) -> list[str]:
    """Every calendar key between two moments, inclusive, at one grain."""
    if grain == "year":
        return [str(year) for year in range(earliest.year, latest.year + 1)]
    if grain == "month":
        keys: list[str] = []
        year, month = earliest.year, earliest.month
        while (year, month) <= (latest.year, latest.month):
            keys.append(f"{year:04d}-{month:02d}")
            year, month = (year + 1, 1) if month == 12 else (year, month + 1)
        return keys
    day = earliest.date()
    end = latest.date()
    days: list[str] = []
    while day <= end:
        days.append(day.isoformat())
        day += timedelta(days=1)
    return days


#: Steps in the ECDF grid, so the curve is sampled at 101 points from 0 to 1.
#:
#: Sampled with `quantile_cont`, the same function the seven named quantiles in
#: `QUANTILES` use — deliberately, because the panel draws this curve directly
#: below a table of those seven numbers, and two estimators would put the p95
#: row and the p95 point on the curve in slightly different places. Every
#: position in `QUANTILES` is a whole percent, so all seven are exact members of
#: this grid rather than near neighbours of it.
#:
#: The consequence is worth stating: between two adjacent grid points the curve
#: is drawn as a straight line, so on a column with few distinct values a true
#: vertical jump renders as a short ramp. A flat run *is* drawn flat — asking
#: for p30 through p70 of a column whose middle is all one value returns that
#: value forty-one times over, which plots as the vertical the step function
#: has.
ECDF_POINTS = 100

#: Ranks the concentration curve keeps exactly, before it starts sampling.
#:
#: The head is where a Pareto reading lives — *four categories cover 80%* is a
#: statement about ranks 1 to 4, and an evenly-sampled curve over five thousand
#: categories would step past all of them. Every rank up to here is a real
#: point; the tail is sampled to fill out `CONCENTRATION_POINTS`.
CONCENTRATION_HEAD = 50

#: Total points on the curve, head included. A column with fewer distinct
#: values than this gets every one of them.
CONCENTRATION_POINTS = 120

#: Terms kept at each n-gram width, and how many values the frequency table
#: shows. Enough to read a pattern, few enough that the panel stays a panel.
TOP_TERMS = 12
TOP_VALUES = 10

#: Terms offered to the word cloud (D-073).
#:
#: Five times the bar column, because the two figures are not the same figure
#: at different sizes: twelve bars are a ranking a reader counts down, and a
#: cloud is a *shape* — twelve words arranged in a box is a scatter of labels
#: with nothing to see. Sixty is where a body of text starts to look like one,
#: and the layout drops whatever will not fit rather than shrinking everything
#: until nothing is legible.
CLOUD_TERMS = 60

#: Distinct values drawn on the rug (D-074).
#:
#: A rug is not a histogram and the cap is not a bin count: every tick is one
#: **distinct value**, at its own position, so what the reader sees is the
#: lattice the column actually sits on. Four hundred is where ticks a panel
#: wide stop being separable, and a column with more distinct values than that
#: is not one whose rounding is legible at this width anyway.
RUG_POINTS = 400

#: How long a span may be before the timeline stops offering a daily grain.
#:
#: Not a payload limit but a legibility one: 1,200 bars across a panel about
#: 1,030px wide is under a pixel each, and a chart nobody can read is not made
#: honest by being complete. Longer columns get year and month, which is what
#: anybody reads a decade of data at anyway.
DAILY_GRAIN_LIMIT = 1200

#: Slots the completeness strip is drawn in (§11.7.3, D-056).
#:
#: A **constant rather than an argument**, unlike `n_bins`. Binning a histogram
#: is a statistical choice — move it and you can reach a different conclusion
#: about the shape. This is a display resolution: the strip answers *where in
#: the file the gaps are*, and no reading of that changes between 200 slots and
#: 260. An argument here would only offer a way to get a second fingerprint for
#: the same question.
#:
#: 240 against a panel about 1030px wide, so a slot is a little over four
#: pixels — thin enough that a run of missing rows reads as a gap rather than
#: as a bar, wide enough to survive a laptop's rounding.
MATRIX_SLOTS = 240


@dataclass(frozen=True, slots=True)
class Completeness:
    """How much of the column is really there.

    `empty` is counted apart from `nulls` because §11.7.3 asks for it and
    because they are different facts: a NULL is an absent answer, a `""` is an
    answer that says nothing. Everything else in this product already treats
    them alike (`_PRESENT` excludes both), so this is the one place the
    distinction survives.
    """

    total: int
    present: int
    nulls: int
    empty: int
    zeros: int | None
    negatives: int | None

    @property
    def null_share(self) -> float:
        return 0.0 if self.total == 0 else self.nulls / self.total


@dataclass(frozen=True, slots=True)
class Presence:
    """Completeness in **file order**, bucketed — missingno's matrix, for one column.

    The question it answers is the one no count can: *where* the gaps are. A
    column that is 7% null because the last eighty rows were never filled in is
    a different column from one that is 7% null at random, and `null 7.0%` says
    the same thing about both.

    Ordered by `file_row_number`, and that is load-bearing. `row_number() OVER
    ()` over a parallel scan has no defined order, so two reads of one file
    could bucket their rows differently and INV-6 would break somewhere nobody
    would look — the numbers would all still be right.
    """

    #: How many file rows each slot covers. 1 when the column is short enough
    #: that every row gets its own.
    rows_per_slot: int
    #: `(rows, present)` per slot, in file order. The last slot may be short.
    slots: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class Cardinality:
    distinct: int
    is_unique: bool

    @staticmethod
    def of(distinct: int, present: int) -> Cardinality:
        return Cardinality(distinct=distinct, is_unique=present > 0 and distinct == present)


@dataclass(frozen=True, slots=True)
class NumericStats:
    """§11.7.3 for a numerical column, minus what `distribution_shape` owns."""

    conforming: int
    mean: float | None
    median: float | None
    mode: float | None
    std: float | None
    variance: float | None
    minimum: float | None
    maximum: float | None
    value_range: float | None
    iqr: float | None
    skewness: float | None
    #: Excess kurtosis, Fisher's definition — a normal distribution scores 0,
    #: not 3. DuckDB's `kurtosis()` is the sample-corrected excess form, and the
    #: panel says which convention beside the number: a reader who knows the
    #: other one would read 0 as impossibly flat.
    kurtosis: float | None
    quantiles: tuple[tuple[float, float], ...]
    outlier_low: float | None
    outlier_high: float | None
    outlier_count: int
    #: Where the whiskers stop: the most extreme value still **inside** the
    #: fence, at each end. Not the fence itself — a whisker drawn to the fence
    #: claims data reaches a place no value does, and on a column whose fence
    #: falls below its own minimum it would reach into empty space.
    whisker_low: float | None
    whisker_high: float | None
    smallest: tuple[float, ...]
    largest: tuple[float, ...]
    bins: tuple[Bin, ...]
    #: (proportion, value) at each step of `ECDF_POINTS`.
    ecdf: tuple[tuple[float, float], ...]
    #: `(value, count)` per distinct value, in value order (D-074). Not a
    #: histogram: nothing is bucketed, so a column that only ever holds
    #: multiples of five shows five-wide gaps between its ticks and a truly
    #: continuous one shows a smear.
    rug: tuple[tuple[float, int], ...]
    #: 1 when every distinct value is on the rug. Higher when the column had
    #: more than `RUG_POINTS` of them and the rug is one tick in `rug_stride`,
    #: which the panel says out loud rather than drawing a thinned figure that
    #: looks complete.
    rug_stride: int


@dataclass(frozen=True, slots=True)
class CategoricalStats:
    top: tuple[TopValue, ...]
    others_count: int
    others_distinct: int
    top5_share: float
    rare_categories: int
    #: `(rank, cumulative share)` over **every** category, sampled.
    #:
    #: The honest form of a Pareto chart for a column whose table shows ten of
    #: two hundred. Bars plus a cumulative line over the top ten would draw the
    #: head and say nothing about the tail — while looking exactly like a chart
    #: that had. This is the line component computed over all of them.
    concentration: tuple[tuple[int, float], ...]


@dataclass(frozen=True, slots=True)
class TextStats:
    """§11.7.3 for a text column, in four parts (D-070).

    **Structure** — how long the values are, in characters and in words.
    **Composition** — what the characters *are*, which is what sorts a text
    column into the three things it is ever actually one of: a mistyped code, a
    label, or prose.
    **Values** — the whole strings that repeat, which is where a column of
    `unknown` or `N/A` gives itself away.
    **Vocabulary** — terms, pairs and triples, and how concentrated they are.

    ⚠️ **The vocabulary block crosses a boundary §11.7.3 drew** and D-071
    records the crossing. Tokens are split on non-alphanumerics and lowercased
    and **nothing else is done to them**: no stopword list, no stemming, no
    language. That is deliberate — a stopword list is a language, and the
    product has no notion of one, so the honest choice is to remove nothing and
    let the composition block above say whether the terms mean anything.
    """

    length_min: int | None
    length_median: float | None
    length_mean: float | None
    length_max: int | None
    words_min: int | None
    words_median: float | None
    words_mean: float | None
    words_max: int | None
    length_bins: tuple[Bin, ...]
    word_bins: tuple[Bin, ...]

    share_numeric: float
    share_dateish: float
    share_with_digit: float
    share_padded: float
    share_upper: float
    share_punct: float
    share_url: float
    share_non_ascii: float

    top: tuple[TopValue, ...]
    others_count: int
    others_distinct: int

    tokens_total: int
    tokens_distinct: int
    top_words: tuple[TopValue, ...]
    top_pairs: tuple[TopValue, ...]
    top_triples: tuple[TopValue, ...]
    #: The same single terms as `top_words`, sixty deep instead of twelve, for
    #: the cloud (D-073). One query serves both: `top_words` is this list's
    #: head, so the two can never disagree about a count or a rank.
    cloud: tuple[TopValue, ...]
    #: `(rank, cumulative share)` over the whole vocabulary, sampled — the same
    #: curve the categorical panel draws over categories.
    vocabulary: tuple[tuple[int, float], ...]

    samples: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DateStats:
    """§11.7.3 for a date column, on calendar boundaries rather than on epoch.

    **The timeline used to be binned on epoch seconds** and this is where that
    ended (D-069). Twenty equal slices of a 900-day span are 45-day buckets
    aligned to nothing, and nobody reads time in units of 45 days. Every series
    here falls on a boundary somebody thinks in.

    **Every series is zero-filled across its own domain.** A month with no rows
    is a gap in the data and has to be drawn as one; a series that simply omits
    it closes the gap up and reports a column that is denser than it is. The
    same goes for a weekday nobody trades on.
    """

    conforming: int
    earliest: str | None
    latest: str | None
    span_days: int | None
    granularity: str
    #: Days holding at least one value, against the days the span covers. The
    #: gap between them is *"missing dates"*, and a count says it better than a
    #: picture of dark squares does.
    days_seen: int
    days_in_span: int
    #: Calendar buckets, zero-filled. `by_day` is empty past
    #: `DAILY_GRAIN_LIMIT`.
    by_year: tuple[tuple[str, int], ...]
    by_month: tuple[tuple[str, int], ...]
    by_day: tuple[tuple[str, int], ...]
    #: Cyclic distributions, folded across the whole span. Always the full
    #: domain: seven weekdays, twelve months, and twenty-four hours when the
    #: column carries a time at all.
    by_weekday: tuple[tuple[str, int], ...]
    by_month_of_year: tuple[tuple[str, int], ...]
    by_hour: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class BooleanStats:
    true_count: int
    false_count: int
    other_count: int


@dataclass(frozen=True, slots=True)
class ColumnDetail:
    """The bundle §11.7.2 describes, minus `warnings` (D-041)."""

    column: str
    logical_type: str
    physical_type: str
    completeness: Completeness
    presence: Presence
    cardinality: Cardinality
    numeric: NumericStats | None
    categorical: CategoricalStats | None
    text: TextStats | None
    date: DateStats | None
    boolean: BooleanStats | None
    narrative: str


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _fit(template: str, name: str) -> str:
    """One of `profile.py`'s SQL fragments, aimed at a column."""
    return template.replace("@@col@@", _quote(name))


class ColumnReader:
    """§11.7's bundle for one column.

    Takes the engine the same way `ProfileReader` does, and for the same reason:
    `TableEngine` is the protocol §13.3.1 L3 narrows to `DataHandle`, and a
    method only one panel uses does not belong on every implementer.
    """

    def __init__(self, engine: DuckDBEngine) -> None:
        self._engine = engine

    def profile(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        column: str,
        top_n: int,
        n_bins: int,
        samples: int,
    ) -> ColumnDetail:
        spec = next((c for c in contract.columns if c.name == column), None)
        if spec is None:
            raise EngineError(f"{column!r} is not a column of this dataset")

        source = self._engine._source(handle)
        logical = spec.logical_type
        completeness, distinct, present, total = self._completeness(source, column, logical)

        numeric: NumericStats | None = None
        categorical: CategoricalStats | None = None
        text: TextStats | None = None
        date: DateStats | None = None
        boolean: BooleanStats | None = None

        # A column with nothing in it gets no shape at all, which is the same
        # call §11.8.3 makes for the overview card: a histogram of a column that
        # is 100% null is one empty frame, and it looks like a finding.
        if present == 0:
            pass
        elif logical == LogicalType.NUMERICAL:
            numeric = self._numeric(source, column, present, n_bins)
        elif logical == LogicalType.CATEGORICAL:
            categorical = self._categorical(source, column, present, distinct, top_n)
        elif logical == LogicalType.DATE:
            date = self._date(source, column)
        elif logical == LogicalType.BOOLEAN:
            boolean = self._boolean(source, column, present)
        else:
            text = self._text(source, column, present, distinct, samples)

        bundle = ColumnDetail(
            column=column,
            logical_type=str(logical),
            physical_type=spec.physical_type,
            completeness=completeness,
            presence=self._presence(source, column, total),
            cardinality=Cardinality.of(distinct, present),
            numeric=numeric,
            categorical=categorical,
            text=text,
            date=date,
            boolean=boolean,
            narrative="",
        )
        return _with_narrative(bundle, total)

    # ------------------------------------------------------------------ parts --

    def _completeness(
        self, source: str, name: str, logical: LogicalType
    ) -> tuple[Completeness, int, int, int]:
        column = _quote(name)
        present = _fit(_PRESENT, name)
        trimmed = _fit(_TRIM, name)
        number = _fit(_AS_NUMBER, name)
        numeric = logical == LogicalType.NUMERICAL

        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*), count(*) FILTER (WHERE {present}),"  # noqa: S608
                f" count(*) FILTER (WHERE {column} IS NULL),"
                f" count(*) FILTER (WHERE {column} IS NOT NULL AND {trimmed} = ''),"
                f" count(DISTINCT {trimmed}) FILTER (WHERE {present}),"
                f" count(*) FILTER (WHERE {number} = 0),"
                f" count(*) FILTER (WHERE {number} < 0)"
                f" FROM read_parquet(?)",
                [source],
            )
            .fetchone()
        )
        assert row is not None
        total, present_n, nulls, empty, distinct, zeros, negatives = (int(v) for v in row)
        return (
            Completeness(
                total=total,
                present=present_n,
                nulls=nulls,
                empty=empty,
                # Zero and negative counts describe a quantity. On a text column
                # they would be a number about something that is not a number.
                zeros=zeros if numeric else None,
                negatives=negatives if numeric else None,
            ),
            distinct,
            present_n,
            total,
        )

    def _presence(self, source: str, name: str, total: int) -> Presence:
        """One scan in file order, bucketed into `MATRIX_SLOTS`.

        Computed for **every** logical type, not only the ones that draw it
        today. Completeness is the one thing every column has, and a bundle
        whose shape depends on which surfaces happen to exist is a bundle that
        changes every time a surface does.
        """
        if total == 0:
            return Presence(rows_per_slot=1, slots=())

        size = max(1, -(-total // MATRIX_SLOTS))  # ceil, without importing math
        last = -(-total // size) - 1
        marker = _fit(_PRESENT, name)
        rows = (
            self._engine._cursor()
            .execute(
                # `file_row_number` rather than `row_number() OVER ()`: the
                # window has no defined order over a parallel scan, and the
                # buckets have to be the same on every read (INV-6).
                f"SELECT least(cast(floor(file_row_number / ?) AS INTEGER), ?) AS b,"  # noqa: S608
                f" count(*), count(*) FILTER (WHERE {marker})"
                f" FROM read_parquet(?, file_row_number=true) GROUP BY b ORDER BY b",
                [size, last, source],
            )
            .fetchall()
        )
        found = {int(b): (int(n), int(seen)) for b, n, seen in rows}
        return Presence(
            rows_per_slot=size,
            slots=tuple(found.get(index, (0, 0)) for index in range(last + 1)),
        )

    def _numeric(self, source: str, name: str, present: int, n_bins: int) -> NumericStats:
        """Everything the descriptive table and the three charts read.

        Two statements rather than one, and the split is forced rather than
        chosen: the fence is a function of the quartiles, so nothing that
        depends on the fence — the outlier count, and where each whisker stops
        — can be asked for in the same breath that computes them.
        """
        number = _fit(_AS_NUMBER, name)
        picks = ", ".join(f"quantile_cont({number}, {q})" for q in QUANTILES)
        # One list argument rather than 101 scalar calls: DuckDB returns a LIST
        # of positions in a single aggregate, over the same scan as everything
        # beside it.
        grid = ", ".join(f"{step / ECDF_POINTS:.10g}" for step in range(ECDF_POINTS + 1))
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count({number}), avg({number}), median({number}),"  # noqa: S608
                f" mode({number}), stddev_samp({number}), min({number}), max({number}),"
                f" skewness({number}), var_samp({number}), kurtosis({number}),"
                f" quantile_cont({number}, [{grid}]), {picks} FROM read_parquet(?)",
                [source],
            )
            .fetchone()
        )
        assert row is not None
        conforming = int(row[0])
        head = [None if v is None else float(v) for v in row[1:10]]
        mean, median, mode, std, low, high, skew, variance, kurtosis = head
        curve = row[10]
        quantiles = tuple(
            (q, float(v)) for q, v in zip(QUANTILES, row[11:], strict=True) if v is not None
        )

        table = dict(quantiles)
        p25, p75 = table.get(0.25), table.get(0.75)
        iqr = None if p25 is None or p75 is None else p75 - p25
        fence_low = None if p25 is None or iqr is None else p25 - IQR_K * iqr
        fence_high = None if p75 is None or iqr is None else p75 + IQR_K * iqr

        outliers = 0
        # A column with no fence has no outliers to be outside it, and its
        # whiskers are simply its ends.
        whisker_low, whisker_high = low, high
        if fence_low is not None and fence_high is not None:
            found = (
                self._engine._cursor()
                .execute(
                    f"SELECT count(*) FILTER (WHERE {number} < ? OR {number} > ?),"  # noqa: S608
                    f" min({number}) FILTER (WHERE {number} >= ?),"
                    f" max({number}) FILTER (WHERE {number} <= ?)"
                    f" FROM read_parquet(?)",
                    [fence_low, fence_high, fence_low, fence_high, source],
                )
                .fetchone()
            )
            if found is not None:
                outliers = int(found[0])
                whisker_low = low if found[1] is None else float(found[1])
                whisker_high = high if found[2] is None else float(found[2])

        rug, stride = self._rug(source, name)
        return NumericStats(
            conforming=conforming,
            mean=mean,
            median=median,
            mode=mode,
            std=std,
            variance=variance,
            minimum=low,
            maximum=high,
            value_range=None if low is None or high is None else high - low,
            iqr=iqr,
            skewness=skew,
            kurtosis=kurtosis,
            quantiles=quantiles,
            outlier_low=fence_low,
            outlier_high=fence_high,
            outlier_count=outliers,
            whisker_low=whisker_low,
            whisker_high=whisker_high,
            smallest=self._edge(source, name, ascending=True),
            largest=self._edge(source, name, ascending=False),
            bins=self._bins(source, name, low, high, n_bins),
            ecdf=(
                ()
                if curve is None
                else tuple(
                    (step / ECDF_POINTS, float(value))
                    for step, value in enumerate(curve)
                    if value is not None
                )
            ),
            rug=rug,
            rug_stride=stride,
        )

    def _rug(self, source: str, name: str) -> tuple[tuple[tuple[float, int], ...], int]:
        """Every distinct value and how often it occurs, in value order (D-074).

        **This is the one figure on the numerical panel that is not binned**,
        and that is the whole point of it. A histogram answers *how many fall
        near here*; twenty bars over `age` look smooth whether the column holds
        every age or only the ones ending in 0 and 5. The rug answers *which
        values does this column actually contain*, and rounding, unit changes
        and coded placeholders are all visible in the answer.

        Thinned by rank rather than truncated when a column carries more than
        `RUG_POINTS` distinct values: cutting the tail would move the axis, and
        the lattice survives striding (every third multiple of five is still
        evenly spaced) where it would not survive bucketing.
        """
        number = _fit(_AS_NUMBER, name)
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(DISTINCT {number}) FROM read_parquet(?)",  # noqa: S608
                [source],
            )
            .fetchone()
        )
        distinct = 0 if row is None or row[0] is None else int(row[0])
        if distinct == 0:
            return (), 1

        stride = max(1, -(-distinct // RUG_POINTS))
        rows = (
            self._engine._cursor()
            .execute(
                f"WITH v AS (SELECT {number} AS x, count(*) AS n"  # noqa: S608
                f" FROM read_parquet(?) WHERE {number} IS NOT NULL GROUP BY 1),"
                f" r AS (SELECT x, n, row_number() OVER (ORDER BY x) AS i FROM v)"
                # `OR i = ?` keeps the largest value whatever the stride did.
                # Without it the rug ends at whichever rank happened to land on
                # the stride: on `amount` that is 1,336,300 under an axis that
                # runs to 2,304,000, so the figure stops at 58% of a scale the
                # histogram and the box beside it use all of. A rug that ends
                # before its own axis says the column does too.
                f" SELECT x, n FROM r WHERE (i - 1) % ? = 0 OR i = ? ORDER BY x",
                [source, stride, distinct],
            )
            .fetchall()
        )
        return tuple((float(x), int(n)) for x, n in rows), stride

    def _edge(self, source: str, name: str, *, ascending: bool) -> tuple[float, ...]:
        """The five smallest or largest values that are really numbers."""
        number = _fit(_AS_NUMBER, name)
        direction = "ASC" if ascending else "DESC"
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT {number} AS v FROM read_parquet(?)"  # noqa: S608
                f" WHERE {number} IS NOT NULL ORDER BY v {direction} LIMIT ?",
                [source, EXTREMES],
            )
            .fetchall()
        )
        return tuple(float(v) for (v,) in rows)

    def _bins(
        self, source: str, name: str, low: float | None, high: float | None, n_bins: int
    ) -> tuple[Bin, ...]:
        """Edges computed here and sent in, never chosen by the database.

        The same rule §11.8.6(c) states for the overview, and for the same
        reason: a database that picks its own boundaries makes two calls with
        one fingerprint disagree about where the bars fall — INV-6 broken
        somewhere nobody would look.
        """
        if low is None or high is None:
            return ()
        number = _fit(_AS_NUMBER, name)
        if high == low:
            row = (
                self._engine._cursor()
                .execute(
                    f"SELECT count({number}) FROM read_parquet(?)",  # noqa: S608
                    [source],
                )
                .fetchone()
            )
            return (Bin(lower=low, upper=high, count=int(row[0]) if row else 0),)

        width = (high - low) / n_bins
        edges = [low + width * index for index in range(n_bins)] + [high]
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT least(cast(floor(({number} - ?) / ?) AS INTEGER), ?) AS b,"  # noqa: S608
                f" count(*) FROM read_parquet(?) WHERE {number} IS NOT NULL"
                f" GROUP BY b ORDER BY b",
                [low, width, n_bins - 1, source],
            )
            .fetchall()
        )
        counts = {int(b): int(n) for b, n in rows}
        return tuple(
            Bin(lower=edges[index], upper=edges[index + 1], count=counts.get(index, 0))
            for index in range(n_bins)
        )

    def _categorical(
        self, source: str, name: str, present: int, distinct: int, top_n: int
    ) -> CategoricalStats:
        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT trim({column}) AS v, count(*) AS n FROM read_parquet(?)"  # noqa: S608
                f" WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                # The tiebreak is not decoration: two categories with equal
                # counts would otherwise come back in scan order, and two calls
                # with one fingerprint would disagree.
                f" GROUP BY v ORDER BY n DESC, v ASC LIMIT ?",
                [source, top_n],
            )
            .fetchall()
        )
        top = tuple(TopValue(value=str(v), count=int(n)) for v, n in rows)
        counted = sum(item.count for item in top)

        rare = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*) FROM (SELECT trim({column}) AS v, count(*) AS n"  # noqa: S608
                f" FROM read_parquet(?) WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                f" GROUP BY v HAVING n < ?)",
                [source, RARE_BELOW],
            )
            .fetchone()
        )
        head = sum(item.count for item in top[:5])
        return CategoricalStats(
            top=top,
            others_count=present - counted,
            others_distinct=max(0, distinct - len(top)),
            top5_share=0.0 if present == 0 else head / present,
            rare_categories=int(rare[0]) if rare else 0,
            concentration=self._concentration(source, name, present, distinct),
        )

    def _concentration(
        self, source: str, name: str, present: int, distinct: int
    ) -> tuple[tuple[int, float], ...]:
        """Cumulative share against rank, over every category in the column.

        **The window's `ORDER BY` is the same one the top-N table uses**, down
        to the `v ASC` tie-break — so rank 1 on this curve is the row at the top
        of that table, and rank 5's height is the `top 5 cover` figure. Two
        orderings would put two different categories at rank 1 and neither
        would be wrong.

        That tie-break is also what makes the curve deterministic: equal counts
        would otherwise come back in scan order, and two calls with one
        fingerprint would draw different curves (INV-6).
        """
        if present == 0 or distinct == 0:
            return ()

        # Every rank through the head, then evenly through the tail. `step` is
        # 1 whenever the column is small enough that no sampling is needed.
        tail = max(0, distinct - CONCENTRATION_HEAD)
        room = max(1, CONCENTRATION_POINTS - CONCENTRATION_HEAD)
        step = max(1, -(-tail // room))

        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                f"WITH counts AS ("  # noqa: S608
                f" SELECT trim({column}) AS v, count(*) AS n FROM read_parquet(?)"
                f" WHERE {column} IS NOT NULL AND trim({column}) <> '' GROUP BY v),"
                f" ranked AS ("
                f" SELECT row_number() OVER (ORDER BY n DESC, v ASC) AS r,"
                f" sum(n) OVER (ORDER BY n DESC, v ASC ROWS UNBOUNDED PRECEDING) AS c"
                f" FROM counts)"
                f" SELECT r, c FROM ranked WHERE r <= ? OR r % ? = 0 OR r = ? ORDER BY r",
                [source, CONCENTRATION_HEAD, step, distinct],
            )
            .fetchall()
        )
        return tuple((int(rank), float(cumulative) / present) for rank, cumulative in rows)

    def _text(self, source: str, name: str, present: int, distinct: int, samples: int) -> TextStats:
        column = _quote(name)
        marker = _fit(_PRESENT, name)
        trimmed = _fit(_TRIM, name)
        number = _fit(_AS_NUMBER, name)
        moment = _fit(_AS_MOMENT, name)
        words = _tokens(name)

        row = (
            self._engine._cursor()
            .execute(
                f"SELECT min(length({trimmed})) FILTER (WHERE {marker}),"  # noqa: S608
                f" quantile_cont(length({trimmed}), 0.5) FILTER (WHERE {marker}),"
                f" avg(length({trimmed})) FILTER (WHERE {marker}),"
                f" max(length({trimmed})) FILTER (WHERE {marker}),"
                f" min(len({words})) FILTER (WHERE {marker}),"
                f" quantile_cont(len({words}), 0.5) FILTER (WHERE {marker}),"
                f" avg(len({words})) FILTER (WHERE {marker}),"
                f" max(len({words})) FILTER (WHERE {marker}),"
                f" count({number}), count({moment}),"
                f" count(*) FILTER (WHERE {marker} AND regexp_matches({trimmed}, '[0-9]')),"
                f" count(*) FILTER (WHERE {marker} AND {column} <> {trimmed}),"
                # All-caps *and* holding a letter: `12345` is not shouting.
                f" count(*) FILTER (WHERE {marker} AND {trimmed} = upper({trimmed})"
                f"   AND regexp_matches({trimmed}, '[A-Za-z]')),"
                f" count(*) FILTER (WHERE {marker} AND regexp_matches({trimmed}, '[[:punct:]]')),"
                f" count(*) FILTER (WHERE {marker} AND regexp_matches({trimmed}, 'https?://|www\\.')),"
                # Bytes against characters — `strlen` counts bytes in DuckDB
                # and `length` counts characters, so `cafe` with an acute is 5
                # against 4. No regex, and it catches accents, CJK, emoji and
                # mojibake alike.
                f" count(*) FILTER (WHERE {marker} AND strlen({trimmed}) <> length({trimmed}))"
                f" FROM read_parquet(?)",
                [source],
            )
            .fetchone()
        )
        assert row is not None

        def share(value: object) -> float:
            assert isinstance(value, int)
            return 0.0 if present == 0 else value / present

        length_min = None if row[0] is None else int(row[0])
        length_max = None if row[3] is None else int(row[3])
        words_min = None if row[4] is None else int(row[4])
        words_max = None if row[7] is None else int(row[7])

        top = self._top_values(source, name, TOP_VALUES)
        counted = sum(item.count for item in top)
        tokens_total, tokens_distinct = self._token_totals(source, name)

        cloud = self._terms(source, name, width=1, limit=CLOUD_TERMS)
        return TextStats(
            length_min=length_min,
            length_median=None if row[1] is None else float(row[1]),
            length_mean=None if row[2] is None else float(row[2]),
            length_max=length_max,
            words_min=words_min,
            words_median=None if row[5] is None else float(row[5]),
            words_mean=None if row[6] is None else float(row[6]),
            words_max=words_max,
            length_bins=self._measure_bins(
                source, f"length({trimmed})", marker, length_min, length_max
            ),
            word_bins=self._measure_bins(source, f"len({words})", marker, words_min, words_max),
            share_numeric=share(row[8]),
            share_dateish=share(row[9]),
            share_with_digit=share(row[10]),
            share_padded=share(row[11]),
            share_upper=share(row[12]),
            share_punct=share(row[13]),
            share_url=share(row[14]),
            share_non_ascii=share(row[15]),
            top=top,
            others_count=max(0, present - counted),
            others_distinct=max(0, distinct - len(top)),
            tokens_total=tokens_total,
            tokens_distinct=tokens_distinct,
            top_words=cloud[:TOP_TERMS],
            top_pairs=self._terms(source, name, width=2),
            top_triples=self._terms(source, name, width=3),
            cloud=cloud,
            vocabulary=self._vocabulary(source, name, tokens_total, tokens_distinct),
            samples=self._samples(source, name, samples),
        )

    def _measure_bins(
        self, source: str, measure: str, marker: str, low: int | None, high: int | None
    ) -> tuple[Bin, ...]:
        """A histogram over a derived measure, on edges computed here.

        Integer measures, so the bin count is capped at the number of distinct
        values a measure can take: a column whose values are all 5 or 6
        characters long gets two bars rather than twenty, eighteen of them
        empty.
        """
        if low is None or high is None:
            return ()
        if high == low:
            row = (
                self._engine._cursor()
                .execute(
                    f"SELECT count(*) FROM read_parquet(?) WHERE {marker}",  # noqa: S608
                    [source],
                )
                .fetchone()
            )
            return (Bin(lower=low, upper=high, count=int(row[0]) if row else 0),)

        count = min(20, high - low + 1)
        width = (high - low) / count
        edges = [low + width * index for index in range(count)] + [float(high)]
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT least(cast(floor(({measure} - ?) / ?) AS INTEGER), ?) AS b,"  # noqa: S608
                f" count(*) FROM read_parquet(?) WHERE {marker} GROUP BY b ORDER BY b",
                [low, width, count - 1, source],
            )
            .fetchall()
        )
        found = {int(bucket): int(n) for bucket, n in rows}
        return tuple(
            Bin(lower=edges[index], upper=edges[index + 1], count=found.get(index, 0))
            for index in range(count)
        )

    def _top_values(self, source: str, name: str, limit: int) -> tuple[TopValue, ...]:
        """The whole strings that repeat, which is where `unknown` gives itself away.

        A `postal_code` column reading 94.8% numeric has 62 rows holding the
        word `unknown`, and the product reports it as 0% null. Nothing else on
        the panel finds that; this does, in one row.
        """
        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT trim({column}) AS v, count(*) AS n FROM read_parquet(?)"  # noqa: S608
                f" WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                # The tiebreak is what makes two calls with one fingerprint
                # return one answer.
                f" GROUP BY v ORDER BY n DESC, v ASC LIMIT ?",
                [source, limit],
            )
            .fetchall()
        )
        return tuple(TopValue(value=str(value), count=int(count)) for value, count in rows)

    def _token_totals(self, source: str, name: str) -> tuple[int, int]:
        words = _tokens(name)
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*), count(DISTINCT w) FROM"  # noqa: S608
                f" (SELECT unnest({words}) AS w FROM read_parquet(?))",
                [source],
            )
            .fetchone()
        )
        return (int(row[0]), int(row[1])) if row else (0, 0)

    def _terms(
        self, source: str, name: str, *, width: int, limit: int = TOP_TERMS
    ) -> tuple[TopValue, ...]:
        """The commonest terms at one n-gram width.

        **Nothing is removed.** No stopword list, because a stopword list is a
        language and this product has no notion of one — so on English prose the
        head of this is `the`, `on`, `and`, and that is the truth about the
        column rather than a defect in the count. The composition block is what
        tells a reader whether to expect terms that mean something.
        """
        words = _tokens(name)
        if width == 1:
            inner = f"SELECT unnest({words}) AS g FROM read_parquet(?)"  # noqa: S608
        else:
            joined = " || ' ' || ".join(f"t[i + {offset}]" for offset in range(width))
            inner = (
                f"WITH k AS (SELECT {words} AS t FROM read_parquet(?))"  # noqa: S608
                f" SELECT unnest(list_transform(generate_series(1, len(t) - {width - 1}),"
                f" i -> {joined})) AS g FROM k WHERE len(t) >= {width}"
            )
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT g, count(*) AS n FROM ({inner})"  # noqa: S608
                f" GROUP BY g ORDER BY n DESC, g ASC LIMIT ?",
                [source, limit],
            )
            .fetchall()
        )
        return tuple(TopValue(value=str(term), count=int(count)) for term, count in rows)

    def _vocabulary(
        self, source: str, name: str, total: int, distinct: int
    ) -> tuple[tuple[int, float], ...]:
        """Cumulative share against term rank — vocabulary concentration.

        The same curve the categorical panel draws over categories, and it
        answers the same question one level down: how many words it takes to
        cover most of the column. A long flat tail is Zipf-shaped behaviour
        without claiming a fit to Zipf's law, which is a test and not a picture.
        """
        if total == 0 or distinct == 0:
            return ()
        words = _tokens(name)
        tail = max(0, distinct - CONCENTRATION_HEAD)
        room = max(1, CONCENTRATION_POINTS - CONCENTRATION_HEAD)
        step = max(1, -(-tail // room))
        rows = (
            self._engine._cursor()
            .execute(
                f"WITH counts AS (SELECT w, count(*) AS n FROM"  # noqa: S608
                f" (SELECT unnest({words}) AS w FROM read_parquet(?)) GROUP BY w),"
                f" ranked AS (SELECT row_number() OVER (ORDER BY n DESC, w ASC) AS r,"
                f" sum(n) OVER (ORDER BY n DESC, w ASC ROWS UNBOUNDED PRECEDING) AS c"
                f" FROM counts)"
                f" SELECT r, c FROM ranked WHERE r <= ? OR r % ? = 0 OR r = ? ORDER BY r",
                [source, CONCENTRATION_HEAD, step, distinct],
            )
            .fetchall()
        )
        return tuple((int(rank), float(cumulative) / total) for rank, cumulative in rows)

    def _samples(self, source: str, name: str, samples: int) -> tuple[str, ...]:
        column = _quote(name)
        rows = (
            self._engine._cursor()
            .execute(
                # Ordered by the value rather than seeded: §11.7.3 asks for a
                # stable sample, and ordering needs nothing to seed and nothing
                # to remember. It also keeps the examples steady when the file
                # grows at the end, which is what makes two runs comparable.
                f"SELECT DISTINCT trim({column}) AS v FROM read_parquet(?)"  # noqa: S608
                f" WHERE {column} IS NOT NULL AND trim({column}) <> ''"
                f" ORDER BY v LIMIT ?",
                [source, samples],
            )
            .fetchall()
        )
        return tuple(str(value) for (value,) in rows)

    def _date(self, source: str, name: str) -> DateStats:
        moment = _fit(_AS_MOMENT, name)
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count({moment}), min({moment}), max({moment}),"  # noqa: S608
                f" count(DISTINCT date_trunc('day', {moment})),"
                f" count(DISTINCT date_trunc('month', {moment})),"
                f" count(*) FILTER (WHERE {moment} IS NOT NULL"
                f"   AND ({moment}) <> date_trunc('day', {moment}))"
                f" FROM read_parquet(?)",
                [source],
            )
            .fetchone()
        )
        assert row is not None
        conforming = int(row[0])
        earliest, latest = row[1], row[2]
        days, months, with_time = int(row[3]), int(row[4]), int(row[5])

        # Granularity read from what the values *are*, not from their type. A
        # column where every value sits at midnight is a daily series however it
        # is stored, and one with 12 distinct days across 12 months is monthly.
        if with_time > 0:
            granularity = "hourly"
        elif months > 0 and days <= months:
            granularity = "monthly"
        else:
            granularity = "daily"

        span = None
        covered = 0
        if isinstance(earliest, datetime) and isinstance(latest, datetime):
            span = (latest.date() - earliest.date()).days
            covered = span + 1

        return DateStats(
            conforming=conforming,
            earliest=None if earliest is None else str(earliest),
            latest=None if latest is None else str(latest),
            span_days=span,
            granularity=granularity,
            days_seen=days,
            days_in_span=covered,
            by_year=self._calendar(source, name, "year", earliest, latest),
            by_month=self._calendar(source, name, "month", earliest, latest),
            by_day=(
                self._calendar(source, name, "day", earliest, latest)
                if covered and covered <= DAILY_GRAIN_LIMIT
                else ()
            ),
            by_weekday=self._cycle(source, name, "isodow", _WEEKDAYS, base=1),
            by_month_of_year=self._cycle(source, name, "month", _MONTHS, base=1),
            by_hour=(
                self._cycle(source, name, "hour", _HOURS, base=0) if granularity == "hourly" else ()
            ),
        )

    def _calendar(
        self, source: str, name: str, grain: str, earliest: object, latest: object
    ) -> tuple[tuple[str, int], ...]:
        """One bucket per calendar unit across the span, **including the empty ones**.

        A month with no rows is a gap in the data. A series that simply leaves
        it out closes the gap up and draws a column that is denser than it is —
        which is the one thing a timeline is read to find.
        """
        if not isinstance(earliest, datetime) or not isinstance(latest, datetime):
            return ()

        moment = _fit(_AS_MOMENT, name)
        pattern = {"year": "%Y", "month": "%Y-%m", "day": "%Y-%m-%d"}[grain]
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT strftime({moment}, '{pattern}') AS k, count(*)"  # noqa: S608
                f" FROM read_parquet(?) WHERE {moment} IS NOT NULL GROUP BY k",
                [source],
            )
            .fetchall()
        )
        found = {str(key): int(count) for key, count in rows}
        return tuple((key, found.get(key, 0)) for key in _sequence(grain, earliest, latest))

    def _cycle(
        self, source: str, name: str, part: str, labels: tuple[str, ...], *, base: int
    ) -> tuple[tuple[str, int], ...]:
        """A cyclic distribution over its **whole** domain, folded across the span.

        Seven weekdays whatever the data does, because *"nothing on Sunday"* is
        a finding and a series of six bars is a chart that lost one. Ordered by
        the number DuckDB returns rather than by the label, which is what the
        weekday series got wrong from D-050 until here: `strftime('%a')` sorted
        alphabetically, so a week began on Friday.
        """
        moment = _fit(_AS_MOMENT, name)
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT {part}({moment}) AS k, count(*) FROM read_parquet(?)"  # noqa: S608
                f" WHERE {moment} IS NOT NULL GROUP BY k",
                [source],
            )
            .fetchall()
        )
        found = {int(key): int(count) for key, count in rows}
        return tuple((label, found.get(index + base, 0)) for index, label in enumerate(labels))

    def _boolean(self, source: str, name: str, present: int) -> BooleanStats:
        marker = _fit(_PRESENT, name)
        trimmed = _fit(_TRIM, name)
        # The vocabulary comes from `profile.py` rather than being written out
        # again here. It **was** written out again here, which meant two places
        # had to agree about what `true` means and only one of them was found
        # when the list changed (D-068).
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*) FILTER (WHERE {marker} AND lower({trimmed})"  # noqa: S608
                f"   IN {_TRUE_WORDS}),"
                f" count(*) FILTER (WHERE {marker} AND lower({trimmed})"
                f"   IN {_FALSE_WORDS}) FROM read_parquet(?)",
                [source],
            )
            .fetchone()
        )
        assert row is not None
        true_count, false_count = int(row[0]), int(row[1])
        return BooleanStats(
            true_count=true_count,
            false_count=false_count,
            # A boolean column may hold a word that is neither, and saying so is
            # the same rule §11.8.4 applies to numbers that do not parse.
            other_count=present - true_count - false_count,
        )


def _number(value: float) -> str:
    """A number as §11.7.7 writes them: grouped, and no longer than it has to be.

    `f"{v:,.4g}"` was the first attempt and it renders 98400 as `9.84e+04`.
    Scientific notation is correct and unreadable in a sentence a person is
    supposed to skim, and the example in §11.7.7 spells its figures out —
    `Median 890,000; rata-rata 1,247,300`.

    Whole numbers lose their decimals entirely; fractions keep up to four and
    drop trailing zeros, so `0.2` stays `0.2` rather than becoming `0.2000`.
    """
    if value != value or value in (float("inf"), float("-inf")):  # NaN, ±inf
        return str(value)
    if abs(value - round(value)) < 1e-9:
        return f"{round(value):,}"
    return f"{value:,.4f}".rstrip("0").rstrip(".")


def _with_narrative(bundle: ColumnDetail, total: int) -> ColumnDetail:
    """§11.7.7 — the same numbers, said out loud, by template.

    §11.7.6(c) settled that this is a template and never an LLM: the shape of a
    profile is always the same, so a template is **100% correct, free and
    instant**, and a model here would add cost and a chance of misreading. It
    also means the whole sentence inherits one `computation_id` and satisfies P3
    without a model being involved.

    The example in §11.7.7 ends on a quality warning. That line is gone with
    D-041, and nothing replaced it.

    **Sentences, joined by one space.** The first version built a list of
    fragments and joined them with two, which reads correctly in a terminal and
    collapses to one in HTML, so the panel rendered
    *"1,200 distinct Median 600.5"* with no punctuation between two different
    facts. Each part now ends in a full stop and carries its own meaning.

    **No em dash anywhere in here** (D-065), at the product owner's request. It
    stood in three places: between a column's name and its type, before the
    skew reading, and before the note that a text column looks numeric. A
    middle dot, a comma and a comma. The rule is a house style rather than a
    correction, and it is enforced by `test_no_em_dash_reaches_the_screen`
    because a template is exactly where one comes back unnoticed.
    """
    done = bundle.completeness
    # `null`, not `empty`. The figure is `nulls / total`, and calling it empty
    # made a column of empty strings say *"0.0% empty. Every row is empty."* —
    # two true statements about two different things, reading as a
    # contradiction. This panel is the only surface that separates a NULL from
    # a `""`, so it is the last place that should blur them.
    head = (
        f"{bundle.column} · {bundle.logical_type}."
        f" {done.present:,} values, {done.null_share:.1%} null,"
        f" {bundle.cardinality.distinct:,} distinct."
    )
    if done.present == 0:
        if done.nulls == done.total:
            return replace(bundle, narrative=f"{head} Every row is null.")
        if done.empty == done.total:
            return replace(bundle, narrative=f"{head} Every row is an empty string.")
        return replace(bundle, narrative=f"{head} No row has a value.")

    parts: list[str] = []
    numeric, categorical = bundle.numeric, bundle.categorical
    date, boolean, text = bundle.date, bundle.boolean, bundle.text

    if numeric is not None and numeric.median is not None:
        line = f"Median {_number(numeric.median)}"
        if numeric.mean is not None:
            line += f", mean {_number(numeric.mean)}"
        skew = numeric.skewness
        if skew is not None and abs(skew) >= 0.5:
            line += f", skewed {'right' if skew > 0 else 'left'} ({skew:.1f})"
        parts.append(line + ".")
        low, high = numeric.outlier_low, numeric.outlier_high
        if low is not None and high is not None:
            parts.append(
                f"{numeric.outlier_count:,} values fall outside the IQR fence"
                f" [{_number(low)}, {_number(high)}]."
            )
    elif categorical is not None and categorical.top:
        leader = categorical.top[0]
        share = leader.count / done.present
        parts.append(f"Most frequent {leader.value!r} at {share:.1%}.")
        parts.append(f"The top five cover {categorical.top5_share:.1%}.")
        if categorical.rare_categories:
            parts.append(
                f"{categorical.rare_categories:,} categories appear fewer than {RARE_BELOW} times."
            )
    elif date is not None and date.earliest is not None:
        first, last = date.earliest[:10], (date.latest or "n/a")[:10]
        parts.append(f"{first} to {last}, {date.granularity}.")
        if date.span_days is not None:
            parts.append(f"Spanning {date.span_days:,} days.")
    elif boolean is not None:
        seen = boolean.true_count + boolean.false_count
        parts.append(f"{0 if seen == 0 else boolean.true_count / seen:.1%} true.")
        if boolean.other_count:
            parts.append(f"{boolean.other_count:,} values are neither.")
    elif text is not None and text.length_min is not None:
        parts.append(f"Lengths run {text.length_min} to {text.length_max} characters.")
        if text.share_numeric >= 0.9:
            parts.append(
                f"{text.share_numeric:.0%} of values are numbers held as text,"
                f" so this may be a numerical column."
            )

    return replace(bundle, narrative=" ".join([head, *parts]))


__all__ = [
    "BooleanStats",
    "Cardinality",
    "CategoricalStats",
    "ColumnDetail",
    "ColumnReader",
    "Completeness",
    "DateStats",
    "NumericStats",
    "Presence",
    "TextStats",
]
