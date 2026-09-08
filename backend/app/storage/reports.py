"""The reading behind the five `report` analyzers (§11.4 layer 2).

## One shape, five tools

Every one of them returns a **ranked list with one reason per row** — that is
what §11.4.1 says `report` means, and holding all five to it buys something
concrete: the planner learns the shape once (`summarise`'s allowlist), the
frontend renders it once, and a sixth report costs neither of them a change.

The subject of a row is usually a column and sometimes the table itself, which
is why the field is `subject` rather than `column`: `duplicate_report` has one
finding about the whole table, and forcing it into a per-column shape would
have been the shape lying about what was measured.

## Why three of these are free

`missingness`, `cardinality` and `type_consistency` are read straight off
`DuckDBEngine.column_statistics` — the same single whole-file pass ingest
already runs. Two things follow, and the second matters more:

* it is one pass rather than three;
* **there is one definition of *present* in this system**, and these reports
  cannot drift from the one the Profile tab and schema inference use. Writing
  a leaner `count(*) FILTER (WHERE col IS NOT NULL)` here would have been
  cheaper per query and would have quietly disagreed with every completeness
  number already on screen, because a blank string is not a value (§FR-B.3).

The honest cost, stated rather than buried: a report that needs one aggregate
pays for seven. Against a whole-file scan that is noise, and it is the right
trade until a measurement says otherwise.

## What is not here

No cleaning, no `action`, no `keep` (D-048). These scan and rank; deciding what
survives is repair, and repair is out of the MVP. `outlier_scan` in particular
takes bounds and returns counts, and there is nowhere in it to put a fix.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from app.domain.data import SchemaContract
from app.domain.enums import LogicalType
from app.storage.engine import ColumnStatistics, DuckDBEngine, EngineError, _quote
from app.storage.profile import _AS_NUMBER, _SLOT

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle

#: How many columns `co_missing` will pair up. Every pair is a filtered count
#: in one projection, so the work is quadratic in this number and nothing else
#: bounds it — 12 columns is 66 pairs, and 40 columns would be 780.
MAX_CO_MISSING_COLUMNS = 12

#: How many example groups a report carries. They are data values, so the
#: Privacy Gate has the last word on whether any of them leave; this only
#: bounds what the bundle stores.
MAX_EXAMPLES = 10

#: Which shape counts prove a column is what the contract says it is. Text and
#: categorical are absent on purpose: **anything is text**, so a conformance
#: figure for them would always be 1.0 and would mean nothing.
#: Types you would plausibly group by, and therefore the only ones the
#: `max_dimension` rule applies to.
#:
#: WARNING: without this the rule floods. On `messy_sales` six of seven
#: findings were the dimension rule and four of those were numeric or date
#: columns: `amount` holding 4,661 distinct values is not a grouping
#: mistake waiting to happen, it is a continuous quantity, and the answer
#: for it is `bin_column` rather than *do not group*. A report that is 85%
#: noise is a report nobody finishes, and the two rules that matter -- one
#: value throughout, every value different -- were buried under it. Those
#: two still apply to every type, because an identifier is a mistake
#: whatever it happens to be made of.
_GROUPABLE_TYPES = (LogicalType.CATEGORICAL, LogicalType.BOOLEAN, LogicalType.TEXT)

_CONFORMING: dict[LogicalType, tuple[str, ...]] = {
    LogicalType.NUMERICAL: ("integer_like", "decimal_like"),
    LogicalType.BOOLEAN: ("boolean_like",),
    LogicalType.DATE: ("date_like", "datetime_like"),
}


@dataclass(frozen=True, slots=True)
class Finding:
    """One row of a report: what, why, and the numbers behind the why."""

    subject: str
    #: Prose the tool computed, not the model. It carries the numbers in
    #: `measures` and **never a value out of the data** — a reason is about a
    #: column, which is K1, and a value would smuggle K3 past the category the
    #: gate would have judged it under.
    reason: str
    measures: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Report:
    """A ranked list, and what it was ranked out of."""

    total_rows: int
    scanned: int
    findings: tuple[Finding, ...] = ()
    #: Example values, when the finding is about values. Shaped `{value, count}`
    #: so the gate applies k-anonymity to it the way it does to any other group.
    examples: tuple[dict[str, object], ...] = ()
    #: Said out loud when a report looked at less than it was asked to.
    note: str = ""

    def as_json(self) -> dict[str, object]:
        """The bundle as JSONB holds it, and as the wire carries it.

        A method rather than a function in some other module, because the last
        time a shape and its serialiser lived apart a field was added to one
        and not the other: a pair crossed as a two-element list, the panel read
        `.value` off an array, and every tick positioned itself at `NaN%`
        (INV-4, sixth occurrence). Next to the dataclass, forgetting is harder.

        `tuple` is spelled `list` deliberately. `dataclasses.asdict` leaves
        tuples as tuples, `json` renders both as arrays, and the difference is
        invisible until something type-checks the result — which is exactly how
        that defect stayed hidden.
        """
        return {
            "total_rows": self.total_rows,
            "scanned": self.scanned,
            "findings": [
                {
                    "subject": finding.subject,
                    "reason": finding.reason,
                    "measures": dict(finding.measures),
                }
                for finding in self.findings
            ],
            "examples": [dict(example) for example in self.examples],
            "note": self.note,
        }


def _count(row: tuple[object, ...], index: int) -> int:
    """A COUNT out of the driver, narrowed.

    DuckDB hands back `object` and returns `Decimal` for some aggregates, so
    the conversion is real rather than a cast. `profile.py` narrows the same
    way for the same reason; the ignore comments mark the one place the
    driver's typing and ours disagree.
    """
    value: int = int(row[index])  # type: ignore[call-overload]
    return value


def _number(row: tuple[object, ...], index: int) -> float:
    return float(row[index])  # type: ignore[arg-type]


def _share(part: int, whole: int) -> float:
    """The proportion, rounded to what `measures` will store.

    Rounded **here** rather than at the call site, so the number in the reason
    string and the number in `measures` are the same number. They were not, in
    the first draft: the reason formatted `part / whole` directly while the
    measure stored it at four places, and the two could disagree in the last
    decimal. The planner derives the percentage it validates against from the
    stored measure, so that disagreement would surface as the validator failing
    a sentence the tool itself wrote — which is the false positive this project
    has already chased three times.
    """
    return 0.0 if whole <= 0 else round(part / whole, 4)


def _pct(share: float) -> str:
    """A stored share as the reason prints it. Takes the share, never the pair."""
    return f"{share * 100:.1f}%"


class ReportReader:
    """Reads the five report-shaped analyzers out of one dataset version.

    Takes the engine rather than living inside it, for the reason
    `ProfileReader` does: `TableEngine` is the protocol §13.3.1 L3 constrains
    to a `DataHandle`, and widening it with methods only the catalogue uses
    would make every implementer carry them.
    """

    def __init__(self, engine: DuckDBEngine) -> None:
        self._engine = engine

    # ------------------------------------------------------------ missingness --

    def missingness(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        min_share: float = 0.0,
        co_missing: bool = True,
    ) -> Report:
        """Which columns are empty, and how often they are empty together."""
        stats = self._statistics(handle, contract)
        total = stats[0].total if stats else 0

        findings = []
        for stat in stats:
            missing = stat.total - stat.non_null
            share = _share(missing, stat.total)
            if missing == 0 or share < min_share:
                continue
            findings.append(
                Finding(
                    subject=stat.name,
                    reason=(f"{missing:,} of {stat.total:,} values are missing ({_pct(share)})"),
                    measures={
                        "missing": float(missing),
                        "present": float(stat.non_null),
                        "missing_share": share,
                    },
                )
            )
        findings.sort(key=lambda f: (-f.measures["missing"], f.subject))

        note = ""
        if co_missing and len(findings) >= 2:
            pairs, note = self._co_missing(handle, [f.subject for f in findings])
            findings.extend(pairs)

        return Report(total_rows=total, scanned=len(stats), findings=tuple(findings), note=note)

    def _co_missing(self, handle: DataHandle, names: list[str]) -> tuple[list[Finding], str]:
        """Columns that go missing in the same rows.

        Worth its own query because *"`cabin` and `deck` are empty in exactly
        the same 687 rows"* is one fact and *"both are 77% empty"* is two, and
        only the first tells you they are the same absence.
        """
        considered = names[:MAX_CO_MISSING_COLUMNS]
        note = ""
        if len(names) > MAX_CO_MISSING_COLUMNS:
            note = (
                f"co-missing pairs cover the {MAX_CO_MISSING_COLUMNS} emptiest "
                f"columns of {len(names)}"
            )

        pairs = [(a, b) for i, a in enumerate(considered) for b in considered[i + 1 :]]
        if not pairs:
            return ([], note)

        blank = {
            name: f"({_quote(name)} IS NULL OR trim({_quote(name)}) = '')" for name in considered
        }
        projection = ", ".join(
            f"count(*) FILTER (WHERE {blank[a]} AND {blank[b]})" for a, b in pairs
        )
        row = self._row(handle, projection)

        findings = []
        for (a, b), together in zip(pairs, row[1:], strict=True):
            count = _count((together,), 0)
            if count == 0:
                continue
            findings.append(
                Finding(
                    subject=f"{a} + {b}",
                    reason=f"missing together in {count:,} rows",
                    measures={"missing_together": float(count)},
                )
            )
        findings.sort(key=lambda f: (-f.measures["missing_together"], f.subject))
        return (findings, note)

    # -------------------------------------------------------------- duplicates --

    def duplicates(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        subset: list[str] | None = None,
    ) -> Report:
        """Rows that repeat, counted three ways because they answer three questions."""
        columns = self._columns(handle, contract, subset)
        keys = ", ".join(_quote(name) for name in columns)
        source = self._source(handle)

        grouped = f"SELECT count(*) AS n FROM read_parquet(?) GROUP BY {keys} HAVING count(*) > 1"  # noqa: S608
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*), coalesce(sum(n), 0) FROM ({grouped})",  # noqa: S608
                [source],
            )
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("duplicate report returned nothing")

        groups, affected = _count(row, 0), _count(row, 1)
        total = self._engine.row_count(handle)
        # Three numbers, and mixing them up is the classic reporting error:
        # `groups` is how many values repeat, `affected` is how many rows are
        # involved, and `extra` is how many would vanish on a dedupe. Only the
        # last one answers *"how much of this table is redundant"*.
        extra = affected - groups

        scope = "every column" if subset is None or not subset else ", ".join(columns)
        if groups == 0:
            return Report(
                total_rows=total,
                scanned=len(columns),
                findings=(
                    Finding(
                        subject="table",
                        reason=f"no two rows agree on {scope}",
                        measures={"duplicate_groups": 0.0, "duplicate_rows": 0.0},
                    ),
                ),
            )

        duplicate_share = _share(affected, total)
        finding = Finding(
            subject="table",
            reason=(
                f"{affected:,} of {total:,} rows ({_pct(duplicate_share)}) share {scope} "
                f"with another row, across {groups:,} repeated values; "
                f"{extra:,} rows would go if each were kept once"
            ),
            measures={
                "duplicate_groups": float(groups),
                "duplicate_rows": float(affected),
                "redundant_rows": float(extra),
                "duplicate_share": duplicate_share,
            },
        )
        return Report(
            total_rows=total,
            scanned=len(columns),
            findings=(finding,),
            examples=self._repeated(handle, columns),
        )

    def _repeated(self, handle: DataHandle, columns: list[str]) -> tuple[dict[str, object], ...]:
        """The commonest repeated keys, as `{value, count}`.

        Composite keys are joined with a separator rather than nested, because
        the gate reads `{value, count}` and applying k-anonymity to a shape it
        understands is worth more than a tidier structure it would drop.
        """
        keys = ", ".join(_quote(name) for name in columns)
        joined = " || ' | ' || ".join(
            f"coalesce(CAST({_quote(n)} AS VARCHAR), '')" for n in columns
        )
        rows = (
            self._engine._cursor()
            .execute(
                f"SELECT {joined} AS k, count(*) AS n FROM read_parquet(?) "  # noqa: S608
                f"GROUP BY {keys} HAVING count(*) > 1 ORDER BY n DESC, k LIMIT {MAX_EXAMPLES}",
                [self._source(handle)],
            )
            .fetchall()
        )
        return tuple({"value": str(key), "count": _count((count,), 0)} for key, count in rows)

    # -------------------------------------------------------- type consistency --

    def type_consistency(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        min_conformance: float = 0.95,
    ) -> Report:
        """Columns whose values disagree with the type the contract declares.

        **Both directions, and the second is where the findings are.**

        The tight direction — a column declared `numerical` holding values that
        are not numbers — cannot occur on a freshly inferred contract.
        `schema/inference.py` assigns a type only when **every** present value
        conforms, so conformance there is exactly 1.0 by construction. That
        direction only becomes possible after somebody overrides a type
        (FR-C.2), and there it is the most valuable thing in this report: a
        user who declares `legacy_code` an integer has just decided that 150
        values which were never numbers become nulls the moment anything casts
        the column.

        The loose direction is the one that fires on ingest. A column read as
        `text` only because 150 of 5,000 values are not digits **is** a column
        whose values disagree with its type; the declaration is merely the safe
        one. Saying so is how a reader finds the disguised null marker that no
        completeness figure can show, because `unknown` is a value and the
        column reports 0% null while a twentieth of it is missing in fact.
        """
        stats = {stat.name: stat for stat in self._statistics(handle, contract)}
        total = next(iter(stats.values())).total if stats else 0

        findings = []
        scanned = 0
        for spec in sorted(contract.columns, key=lambda c: c.ordinal):
            stat = stats.get(spec.name)
            if stat is None or stat.non_null == 0:
                continue
            scanned += 1
            declared = _CONFORMING.get(spec.logical_type)
            finding = (
                self._declared_but_not(
                    spec.name, spec.logical_type, declared, stat, min_conformance
                )
                if declared is not None
                else self._nearly_something_else(
                    spec.name, spec.logical_type, stat, min_conformance
                )
            )
            if finding is not None:
                findings.append(finding)
        findings.sort(key=lambda f: (f.measures["conformance"], f.subject))

        note = ""
        if scanned == 0:
            note = "no column holds a value, so nothing could disagree with anything"
        return Report(total_rows=total, scanned=scanned, findings=tuple(findings), note=note)

    @staticmethod
    def _declared_but_not(
        name: str,
        declared: LogicalType,
        fields: tuple[str, ...],
        stat: ColumnStatistics,
        min_conformance: float,
    ) -> Finding | None:
        """The tight direction: values that are not what the column says it holds."""
        conforming = sum(int(getattr(stat, field)) for field in fields)
        share = _share(conforming, stat.non_null)
        if share >= min_conformance:
            return None
        odd = stat.non_null - conforming
        return Finding(
            subject=name,
            reason=(
                f"declared {declared.value}, but {odd:,} of {stat.non_null:,} present "
                f"values do not read as one ({_pct(share)} conform)"
            ),
            measures={
                "conforming": float(conforming),
                "odd": float(odd),
                "conformance": share,
            },
        )

    @staticmethod
    def _nearly_something_else(
        name: str,
        declared: LogicalType,
        stat: ColumnStatistics,
        min_conformance: float,
    ) -> Finding | None:
        """The loose direction: text that is almost entirely one other type.

        Almost, and never entirely. At a share of exactly 1.0 inference would
        have given the column that type itself, so 1.0 here means somebody
        chose `text` deliberately — a postal code, an order reference — and
        that choice is theirs to keep rather than ours to question.
        """
        best: tuple[float, LogicalType, int] | None = None
        for candidate, fields in _CONFORMING.items():
            matching = sum(int(getattr(stat, field)) for field in fields)
            share = _share(matching, stat.non_null)
            if share < min_conformance or share >= 1.0:
                continue
            if best is None or share > best[0]:
                best = (share, candidate, matching)
        if best is None:
            return None

        share, candidate, matching = best
        odd = stat.non_null - matching
        return Finding(
            subject=name,
            reason=(
                f"declared {declared.value}, but {matching:,} of {stat.non_null:,} present "
                f"values ({_pct(share)}) read as {candidate.value}; the other {odd:,} are "
                f"either the real values or a null marker in disguise"
            ),
            measures={
                "conforming": float(matching),
                "odd": float(odd),
                "conformance": share,
            },
        )

    # -------------------------------------------------------------- cardinality --

    def cardinality(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        max_dimension: int = 50,
    ) -> Report:
        """Columns whose number of distinct values makes them awkward to group by."""
        stats = self._statistics(handle, contract)
        total = stats[0].total if stats else 0
        declared = {spec.name: spec.logical_type for spec in contract.columns}

        findings = []
        for stat in stats:
            if stat.non_null == 0:
                findings.append(
                    Finding(
                        subject=stat.name,
                        reason="no values at all",
                        measures={"distinct": 0.0, "present": 0.0},
                    )
                )
                continue

            measures = {
                "distinct": float(stat.distinct),
                "present": float(stat.non_null),
                "distinct_share": _share(stat.distinct, stat.non_null),
            }
            if stat.distinct == 1:
                reason = "one value throughout, so it cannot separate anything"
            elif stat.distinct == stat.non_null and stat.non_null > 1:
                reason = (
                    f"every one of {stat.non_null:,} values is different, "
                    f"which is an identifier rather than a category"
                )
            elif stat.distinct > max_dimension and declared.get(stat.name) in _GROUPABLE_TYPES:
                reason = (
                    f"{stat.distinct:,} distinct values, past the {max_dimension:,} "
                    f"a grouped result stays readable at"
                )
            else:
                continue
            findings.append(Finding(subject=stat.name, reason=reason, measures=measures))

        findings.sort(key=lambda f: (-f.measures["distinct"], f.subject))

        # **And the columns that passed, by name.**
        #
        # The findings answer *which columns are awkward to group by*, and the
        # question people ask is the inverse. Watched live: `which columns are
        # safe to group by?` got a correct report of the nine that are not,
        # then spent its whole step budget on `describe_dataset` and four
        # `profile_column` calls looking for the fifteen it did not name.
        #
        # `aggregate` already tells a caller that *cardinality_report says
        # which columns are safe to group by* when it refuses one, so this is
        # a promise the catalogue had already made on this tool's behalf.
        #
        # **Counted, not typed.** A column is a usable key when it separates
        # rows into a readable number of groups, and D-085 settled that the
        # count is the real constraint and the logical type only its proxy:
        # `rating` holds five numbers and groups perfectly.
        clean = [
            stat.name for stat in stats if 2 <= stat.distinct <= max_dimension and stat.non_null > 0
        ]
        note = (
            f"{len(clean)} of {len(stats)} columns group into a readable number "
            f"of values: {', '.join(clean)}"
            if clean
            else "no column in this dataset groups into a readable number of values"
        )
        return Report(total_rows=total, scanned=len(stats), findings=tuple(findings), note=note)

    # ------------------------------------------------------------------ outliers --

    def outliers(
        self,
        handle: DataHandle,
        contract: SchemaContract,
        *,
        column: str,
        k: float = 1.5,
        lower: float | None = None,
        upper: float | None = None,
    ) -> Report:
        """How many values fall outside the fence, and where the fence is.

        It scans and stops there (D-048). A `clip` would produce a derived
        table, and that is cleaning.
        """
        numeric = _AS_NUMBER.replace(_SLOT, _quote(column))
        row = self._row(
            handle,
            ", ".join(
                (
                    f"count({numeric})",
                    f"quantile_cont({numeric}, 0.25)",
                    f"quantile_cont({numeric}, 0.75)",
                    f"min({numeric})",
                    f"max({numeric})",
                )
            ),
        )
        total, present = _count(row, 0), _count(row, 1)
        if present == 0:
            return Report(
                total_rows=total,
                scanned=0,
                note=f"{column} holds no values that read as numbers",
            )

        q1, q3 = _number(row, 2), _number(row, 3)
        spread = q3 - q1
        floor = lower if lower is not None else q1 - k * spread
        ceiling = upper if upper is not None else q3 + k * spread

        counted = self._row(
            handle,
            ", ".join(
                (
                    f"count(*) FILTER (WHERE {numeric} < {floor})",
                    f"count(*) FILTER (WHERE {numeric} > {ceiling})",
                )
            ),
        )
        below, above = _count(counted, 1), _count(counted, 2)
        out = below + above

        outlier_share = _share(out, present)
        measures = {
            "below": float(below),
            "above": float(above),
            "outliers": float(out),
            "outlier_share": outlier_share,
            "lower_fence": round(float(floor), 4),
            "upper_fence": round(float(ceiling), 4),
            "q1": round(q1, 4),
            "q3": round(q3, 4),
            "minimum": round(_number(row, 4), 4),
            "maximum": round(_number(row, 5), 4),
        }
        reason = (
            f"{out:,} of {present:,} values ({_pct(outlier_share)}) fall outside "
            f"{floor:g} to {ceiling:g}: {below:,} below and {above:,} above"
        )
        return Report(
            total_rows=total,
            scanned=present,
            findings=(Finding(subject=column, reason=reason, measures=measures),),
        )

    # ------------------------------------------------------------------ shared --

    def _statistics(
        self, handle: DataHandle, contract: SchemaContract
    ) -> tuple[ColumnStatistics, ...]:
        """The one whole-file pass, restricted to columns the contract knows.

        A column in the file that the contract has never heard of is not this
        report's business: the contract is the interpretation, and reporting on
        something outside it would be reporting on data nobody agreed to read.
        """
        known = {spec.name for spec in contract.columns}
        return tuple(stat for stat in self._engine.column_statistics(handle) if stat.name in known)

    def _columns(
        self, handle: DataHandle, contract: SchemaContract, subset: list[str] | None
    ) -> list[str]:
        """The subset, checked against the file, or every column in order."""
        physical = {c.name for c in self._engine.columns(handle)}
        ordered = [
            spec.name
            for spec in sorted(contract.columns, key=lambda c: c.ordinal)
            if spec.name in physical
        ]
        if not subset:
            if not ordered:
                raise EngineError("this dataset has no columns to compare")
            return ordered

        missing = [name for name in subset if name not in physical]
        if missing:
            raise EngineError(f"no column named {missing[0]!r} in this dataset")
        return [name for name in ordered if name in set(subset)]

    def _source(self, handle: DataHandle) -> str:
        return self._engine._source(handle)

    def _row(self, handle: DataHandle, projection: str) -> tuple[object, ...]:
        """`count(*)` first, then the projection. One scan."""
        row = (
            self._engine._cursor()
            .execute(
                f"SELECT count(*), {projection} FROM read_parquet(?)",  # noqa: S608
                [self._source(handle)],
            )
            .fetchone()
        )
        if row is None:  # pragma: no cover - an aggregate always returns a row
            raise EngineError("report query returned nothing")
        return row


__all__ = [
    "MAX_CO_MISSING_COLUMNS",
    "MAX_EXAMPLES",
    "Finding",
    "Report",
    "ReportReader",
]
