"""The one place data is allowed to leave for a model (§13.5, INV-9).

## The contradiction this resolves

*"It is data, so it has to be secure"* sits against an architecture that sends
column names, sample values and aggregate results to a third-party API. Login
does not resolve that at all. §13.5's answer is to make egress **an explicit,
per-account, user-visible policy** rather than a promise — and a policy is only
a policy if code enforces it, because §12.1 is blunt that *prompt is preference,
code is guarantee*.

## What can actually leak

The model never touches the file. It has no Parquet reader, no DuckDB, no
storage credentials. **All it receives is text in a prompt**, so the question is
narrow: which text?

**K1 — structural metadata.** `customer_name: text`, 48,203 rows. Routinely
underrated: a column *name* can be the secret, as `gaji_karyawan`,
`no_rekam_medis` and `nik` all are.

**K2 — aggregate statistics.** `mean(amount)=1.2M`, `corr=0.43`. Safe, except
at small group sizes, which is what PG-1 exists for.

**K3 — category values.** `region: [Jakarta, Surabaya, ...]`. More sensitive
than it looks: for many datasets the list of distinct values **is** the data.

**K4 — raw rows.** One person's record, with their name and their number in it.

## The hole in `balanced`, and why the mitigations are part of the mode

*"Aggregates, no data values"* is not accurate. A group key **is** a data value,
and an aggregate over groups of size 1 **is** a raw row wearing a `sum()`.
`aggregate(group_by=[customer_name], measures=[sum(amount)])` returns 12,405
rows of a person's name beside what they spent — technically an aggregate, and
in practice the table.

So PG-1 (k-anonymity, k=5) and PG-2 (at most 20 rows) are written into the
definition of `balanced` rather than added afterwards.

⚠️ **PG-1 here drops the measures of a suppressed group, not only its key.**
§13.5.3 shows the key being replaced by `[suppressed, n<5]`. Replacing only the
key would leave `sum(amount)` for a group of one on the wire: the name is hidden
and the salary is not, and a second question re-identifies it. Hiding the label
of a row that is still a row does not close the hole PG-1 was written for.

## INV-9 is directional, and that is the whole point

PG-1 and PG-2 apply **only** on the way to the model. The user keeps seeing the
full, uncensored result, because what the UI renders comes from the Computation
and never from the model. A gate that censored the screen would be solving a
different problem badly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.data import SchemaContract
from app.domain.enums import PrivacyMode

#: PG-1. A group smaller than this is not an aggregate, it is a row.
K_ANONYMITY = 5

#: PG-2. A narration does not need 12,405 groups, and sending them is paying
#: for tokens to weaken the policy.
MAX_AGGREGATE_ROWS = 20

#: What a suppressed group looks like on the wire. It says the range rather
#: than the count: `n=1` and `n=4` are both `n<5`, and the exact figure is a
#: fact about the group that PG-1 exists to withhold.
SUPPRESSED = "[suppressed, n<5]"


@dataclass(frozen=True, slots=True)
class Disclosure:
    """What one mode permits, by category (§13.5.2)."""

    schema: bool
    aggregates: bool
    category_values: bool
    raw_rows: bool


#: ⚠️ `strict` is **not** zero disclosure — column names still leave. §13.5
#: says so out loud, and the honest consequence is stated with it: if the
#: column names are themselves the secret, the only answer is `local`.
DISCLOSURE: dict[PrivacyMode, Disclosure] = {
    PrivacyMode.STRICT: Disclosure(
        schema=True, aggregates=False, category_values=False, raw_rows=False
    ),
    PrivacyMode.BALANCED: Disclosure(
        schema=True, aggregates=True, category_values=True, raw_rows=False
    ),
    PrivacyMode.FULL: Disclosure(schema=True, aggregates=True, category_values=True, raw_rows=True),
    #: Nothing leaves, because nothing goes anywhere: the model runs here.
    #: `factory.layers(local_only=True)` is the other half of this row, and it
    #: removes cloud providers rather than ranking them lower.
    PrivacyMode.LOCAL: Disclosure(
        schema=False, aggregates=False, category_values=False, raw_rows=False
    ),
}


@dataclass(frozen=True, slots=True)
class GroupRow:
    """One row of a grouped aggregate, before the gate sees it."""

    key: str
    count: int
    values: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class Filtered:
    """What survived, and what did not — both, because omission must be visible.

    A truncated list that does not say it was truncated is a model narrating
    *"the top region is Jakarta"* over a slice it did not know was a slice.
    """

    rows: tuple[GroupRow, ...]
    suppressed: int
    omitted: int
    #: Rows the shares are out of. Zero means the caller did not say, and then
    #: no share is printed — a percentage of an unknown denominator is worse
    #: than no percentage.
    total: int = 0

    def render(self) -> str:
        """The text that actually goes in the prompt."""
        lines: list[str] = []
        for row in self.rows:
            if row.key == SUPPRESSED:
                lines.append(SUPPRESSED)
                continue
            measures = "".join(f" {value:g}" for value in row.values)
            share = "" if self.total <= 0 else f" ({row.count / self.total * 100:.1f}%)"
            lines.append(f"{row.key}: n={row.count}{share}{measures}")
        if self.omitted:
            lines.append(f"...and {self.omitted} more groups")
        return "\n".join(lines)


class PrivacyGate:
    """One exit. Every payload bound for a model passes through here.

    Constructed from the account's mode rather than reading it, so a caller
    cannot forget to consult the policy — there is no way to build a request
    without having named one.
    """

    def __init__(
        self,
        mode: PrivacyMode,
        *,
        k: int = K_ANONYMITY,
        max_rows: int = MAX_AGGREGATE_ROWS,
    ) -> None:
        self.mode = mode
        self.k = k
        self.max_rows = max_rows

    @property
    def allows(self) -> Disclosure:
        return DISCLOSURE[self.mode]

    # ------------------------------------------------------------ K1 ------

    def schema(self, contract: SchemaContract) -> str:
        """Column names and logical types, or nothing.

        Nothing is what `local` returns, and it is not a degraded mode being
        polite: under `local` the model is on this machine and the gate has
        nothing to guard.
        """
        if not self.allows.schema:
            return ""
        return "\n".join(
            f"{column.name}: {column.logical_type}"
            for column in sorted(contract.columns, key=lambda c: c.ordinal)
        )

    # ------------------------------------------------------------ K2 ------

    def statistic(self, name: str, value: Any) -> str:
        """One aggregate figure, or a refusal that keeps the shape.

        `strict` withholds the number and **keeps the name**, which is what
        §13.5.2 means by *"tool selection stays accurate; the narration cannot
        cite figures"*. A model that knows a mean exists can still decide the
        next step; it just cannot say what it was.
        """
        if not self.allows.aggregates:
            return f"{name}: [withheld by privacy mode]"
        return f"{name}: {value}"

    # ------------------------------------------------------- K3 + PG-1/2 ---

    def groups(self, rows: tuple[GroupRow, ...], *, total: int = 0) -> Filtered:
        """PG-1 then PG-2, in that order, and the order matters.

        Truncating first would let twenty rows of size 1 through untouched and
        suppress nothing — PG-2 would have quietly disabled PG-1. Suppressing
        first means the twenty that survive are twenty that were allowed to.
        """
        if not self.allows.category_values:
            return Filtered(rows=(), suppressed=0, omitted=len(rows), total=total)

        # PG-1. The measures go with the key: a row whose label is hidden and
        # whose `sum(amount)` is not is still one person's number.
        guarded = tuple(
            row
            if row.count >= self.k or self.allows.raw_rows
            else GroupRow(key=SUPPRESSED, count=row.count, values=())
            for row in rows
        )
        suppressed = sum(1 for row in guarded if row.key == SUPPRESSED)

        # PG-2.
        kept = guarded[: self.max_rows]
        return Filtered(
            rows=kept,
            suppressed=suppressed,
            omitted=max(0, len(guarded) - len(kept)),
            total=total,
        )

    # ------------------------------------------------------------ K4 ------

    def rows(self, records: tuple[tuple[Any, ...], ...]) -> tuple[tuple[Any, ...], ...]:
        """Raw records, and only under `full`.

        There is no partial version of this. A sample of raw rows is raw rows;
        the only question the gate asks is whether the mode said yes.
        """
        if not self.allows.raw_rows:
            return ()
        return records[: self.max_rows]


__all__ = [
    "DISCLOSURE",
    "K_ANONYMITY",
    "MAX_AGGREGATE_ROWS",
    "SUPPRESSED",
    "Disclosure",
    "Filtered",
    "GroupRow",
    "PrivacyGate",
]
