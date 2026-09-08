"""Correcting a schema (FR-C.2, FR-C.3, INV-3, P0-15).

A correction never edits anything. It reads the current contract, applies what
the user changed, and writes the result as the **next version** pointing at its
predecessor. That is INV-3, and the database enforces it independently.

**The user is the authority, and we still refuse to be silent.** §10.2 says
schema inference is deliberately not responsible for deciding — the person who
knows what the column means decides. But D-029 exists because typing a column
in a way that discards values is data loss, and that stays true when a human
asks for it. So an override that would not fit every value is **accepted and
recorded**: it succeeds, and the contract says in plain words how many values
do not conform.

That is the honest middle. Refusing would override FR-C.2 and make the product
argue with someone who knows more than it does; accepting quietly would repeat
the exact failure the detector was built to avoid.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from app.domain.data import ColumnSpec, SchemaContract
from app.domain.enums import LogicalType
from app.domain.errors import DomainError
from app.domain.ids import SchemaContractId, UserId
from app.storage.engine import ColumnStatistics


class SchemaOverrideRejected(DomainError):
    """The correction cannot be applied as asked (P6: say which, and why)."""


@dataclass(frozen=True, slots=True)
class ColumnOverride:
    """What a user changed about one column.

    Only interpretation is changeable. ``name``, ``ordinal`` and
    ``physical_type`` are facts about the file, not opinions about it — a
    contract that disagreed with the Parquet underneath would describe a table
    that does not exist.
    """

    name: str
    logical_type: LogicalType | None = None
    null_markers: tuple[str, ...] | None = None
    format_hint: str | None = None

    @property
    def changes_anything(self) -> bool:
        return any(
            value is not None for value in (self.logical_type, self.null_markers, self.format_hint)
        )


def conforming_count(stats: ColumnStatistics, logical_type: LogicalType) -> int | None:
    """How many present values fit ``logical_type``.

    ``None`` where the question does not apply — ``text`` holds anything, and
    ``categorical`` is about cardinality rather than shape, so neither can
    discard a value. Returning ``None`` rather than ``non_null`` keeps "cannot
    lose data" distinct from "happens to lose none this time".
    """
    match logical_type:
        case LogicalType.NUMERICAL:
            return stats.integer_like + stats.decimal_like
        case LogicalType.BOOLEAN:
            return stats.boolean_like
        # A timestamp is a date with a time on it, so both counts conform. Adding
        # them rather than taking `date_like` alone is what stops a correction to
        # `date` on a timestamp column reporting every row as a value it would
        # discard — which it would not.
        case LogicalType.DATE:
            return stats.date_like + stats.datetime_like
        case _:
            return None


def _override_reason(
    stats: ColumnStatistics | None, logical_type: LogicalType, actor: UserId
) -> str:
    """What the contract records about a human decision.

    ``detection_reason`` answers "why is this column this type?", and for an
    overridden column the honest answer names the person and the cost. Storing
    only "set by user" would lose the one fact anybody would want later.
    """
    del actor  # named in `overridden_by`; §13.7.1 keeps identities out of prose
    if stats is None:
        return f"set to {logical_type.value} by a user"

    fitting = conforming_count(stats, logical_type)
    if fitting is None or fitting >= stats.non_null:
        return f"set to {logical_type.value} by a user; every value conforms"
    return (
        f"set to {logical_type.value} by a user; {stats.non_null - fitting} of "
        f"{stats.non_null} values do not conform and will not survive conversion"
    )


def apply(
    current: SchemaContract,
    overrides: Sequence[ColumnOverride],
    *,
    actor: UserId,
    now: datetime,
    statistics: Mapping[str, ColumnStatistics] | None = None,
) -> SchemaContract:
    """Produce the next contract version (FR-C.3).

    Columns nobody touched are carried over **unchanged**, including whatever
    the detector originally said and whoever overrode them before. A correction
    is a correction, not a re-detection: re-running inference here would quietly
    undo an earlier decision the moment someone edited an unrelated column.
    """
    if not overrides:
        raise SchemaOverrideRejected("no changes were requested")

    by_name = {column.name: column for column in current.columns}
    unknown = sorted({o.name for o in overrides} - set(by_name))
    if unknown:
        raise SchemaOverrideRejected(
            f"no such column: {', '.join(unknown)}. The contract describes {len(by_name)} columns."
        )

    seen: set[str] = set()
    for override in overrides:
        if override.name in seen:
            raise SchemaOverrideRejected(f"column {override.name!r} appears twice in the request")
        seen.add(override.name)
        if not override.changes_anything:
            raise SchemaOverrideRejected(f"column {override.name!r} has nothing to change")

    applied = {o.name: o for o in overrides}
    columns = tuple(
        _apply_one(column, applied.get(column.name), actor, statistics)
        for column in sorted(current.columns, key=lambda c: c.ordinal)
    )

    return SchemaContract(
        id=SchemaContractId(uuid.uuid4()),
        dataset_id=current.dataset_id,
        version_no=current.version_no + 1,
        columns=columns,
        created_at=now,
        created_by=actor,
        derived_from=current.id,
    )


def _apply_one(
    column: ColumnSpec,
    override: ColumnOverride | None,
    actor: UserId,
    statistics: Mapping[str, ColumnStatistics] | None,
) -> ColumnSpec:
    if override is None:
        return column

    logical_type = override.logical_type or column.logical_type
    stats = None if statistics is None else statistics.get(column.name)

    return ColumnSpec(
        name=column.name,
        ordinal=column.ordinal,
        physical_type=column.physical_type,
        logical_type=logical_type,
        format_hint=(
            override.format_hint if override.format_hint is not None else column.format_hint
        ),
        null_markers=(
            override.null_markers if override.null_markers is not None else column.null_markers
        ),
        # A human decision is not a detection, and pretending otherwise would
        # let a 0.6 from the detector sit under a type the user is certain of.
        detection_confidence=1.0,
        detection_reason=_override_reason(stats, logical_type, actor),
        overridden_by=actor,
    )


__all__ = ["ColumnOverride", "SchemaOverrideRejected", "apply", "conforming_count"]
