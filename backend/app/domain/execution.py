"""Computation identity — the fingerprint of §9.4.

One idea produces four properties at once: determinism, caching, correct
invalidation, and reproducibility. All of them fall out of hashing *what
produced a number* rather than the number itself.

```
fingerprint = SHA256(
    tool_name ‖ tool_version ‖ canonical_json(args)
    ‖ dataset_id ‖ schema_contract_id
    ‖ sorted(fingerprint(p) for p in parents)
)
```

## What each ingredient is actually for

``tool_version`` is the one v1 lacked, and its absence was the single strongest
technical argument for rewriting: fixing a bug in a tool left every cached
result of that tool in place, still being served, still wrong.

``schema_contract_id`` is the other. Correct a column's type and every
fingerprint downstream of it changes, so every cached result downstream misses.
**A stale cache entry is not merely unlikely, it is structurally impossible** —
which is a stronger guarantee than any amount of invalidation logic, because
there is no logic to get wrong.

``sorted(...)`` over the parents rather than the order they were given: two
steps with the same inputs in a different order are the same computation, and
sorting is what makes the DAG a Merkle tree rather than a list.

## The trade-off, stated

Cache hit rate is lower than a naive key would give — bump a tool's version and
every cached result of that tool is invalid. That is the feature: better to
recompute than to lie. Cosmetic changes belong in a patch level that does not
enter the fingerprint at all.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from ._checks import ensure_aware, ensure_non_empty
from .errors import InvariantViolation
from .ids import DatasetId, SchemaContractId, UserId


def canonical_json(value: Any) -> str:
    """The one spelling of a JSON document that a hash can rely on.

    Two arguments that mean the same thing must hash the same, so key order is
    fixed, whitespace is removed, and non-ASCII is left alone rather than
    escaped — ``ensure_ascii=True`` would make ``{"kota": "Yogyakarta"}`` and
    the same dict read from a different decoder produce different bytes.

    Floats are the sharp edge here and they are not smoothed over: ``1.0`` and
    ``1`` are different JSON and hash differently. A tool that wants them to
    agree must normalise its own arguments before they get here, because
    guessing which of the two the caller meant is exactly the kind of
    helpfulness that makes a cache serve the wrong answer.
    """
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fingerprint(
    *,
    tool_name: str,
    tool_version: int,
    args: dict[str, Any],
    dataset_id: DatasetId,
    schema_contract_id: SchemaContractId,
    parents: tuple[str, ...] = (),
) -> str:
    """§9.4, written out.

    ``\\x1f`` between the fields — the ASCII unit separator, a byte that cannot
    appear in any of them. Joining on a printable character would let
    ``tool="a", version=1`` collide with ``tool="a1", version=""``: the same
    bytes, a different computation, one cache entry.
    """
    ensure_non_empty(tool_name, "tool_name")
    if tool_version < 1:
        raise InvariantViolation(f"tool_version starts at 1, got {tool_version}")

    parts = (
        tool_name,
        str(tool_version),
        canonical_json(args),
        str(dataset_id),
        str(schema_contract_id),
        canonical_json(sorted(parents)),
    )
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Computation:
    """One tool run, identified by what produced it rather than by when.

    INV-5 says every number on screen comes from one of these. That is the whole
    reason it exists: a figure with no ``computation_id`` is a figure nobody can
    trace, reproduce, or invalidate, and P3 makes that unacceptable regardless of
    how correct the figure happens to be.

    ``result`` holds the tool's output bundle. It is JSON rather than a typed
    column because the shape belongs to the tool, and a table that knew every
    tool's shape would need a migration for every new tool — which is exactly
    what NFR-MAINT.1 forbids.
    """

    id: UUID
    fingerprint: str
    tool_name: str
    tool_version: int
    args: dict[str, Any]
    dataset_id: DatasetId
    schema_contract_id: SchemaContractId
    result: dict[str, Any]
    computed_at: datetime
    computed_by: UserId
    duration_ms: int
    parents: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        ensure_aware(self.computed_at, "computed_at")
        ensure_non_empty(self.fingerprint, "fingerprint")
        if self.duration_ms < 0:
            raise InvariantViolation("duration_ms cannot be negative")

        expected = fingerprint(
            tool_name=self.tool_name,
            tool_version=self.tool_version,
            args=self.args,
            dataset_id=self.dataset_id,
            schema_contract_id=self.schema_contract_id,
            parents=self.parents,
        )
        if self.fingerprint != expected:
            # Checked on construction rather than trusted from the caller. A
            # Computation whose fingerprint does not describe its own contents
            # is a cache entry that will be served for the wrong question, and
            # it would be found by somebody reading a wrong number months later.
            raise InvariantViolation(
                "fingerprint does not match this computation's own inputs"
                f" — expected {expected[:12]}…, got {self.fingerprint[:12]}…"
            )


__all__ = ["Computation", "canonical_json", "fingerprint"]
