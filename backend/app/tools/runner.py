"""Running a tool so that its numbers have somewhere to come from.

This is the smallest thing that satisfies INV-5. Look it up by fingerprint; if
it is there, return it; if it is not, run the tool and store what it returned.
Four steps, and each one is doing something the invariants asked for:

* the fingerprint is §9.4, so identity comes from the inputs;
* the lookup is the cache, and it is the *whole* cache;
* the insert makes the result referenceable, which is what INV-5 requires;
* the ``tool_version`` row makes the result explicable after the tool changes.

## What this is not

It is not the Step executor. There is no DAG, no parents, no invalidation
sweep, no expression language — ``parents`` is threaded through the fingerprint
because §9.4 defines it that way, and today it is always empty. Phase 3 fills
it in; nothing here has to change when it does, which is the point of building
the identity half first.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from sqlalchemy.ext.asyncio import AsyncConnection

from app.clock import Clock, system_clock
from app.domain.data import ColumnSpec
from app.domain.enums import LogicalType
from app.domain.execution import Computation, fingerprint
from app.repositories.execution import ComputationRepository, ToolVersionRepository
from app.tools.contract import REGISTRY, ExecContext, ToolError, ToolRegistry
from app.tools.tables import BASE, TableInput, base_table, derived

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle
    from app.domain.data import SchemaContract
    from app.storage.engine import TableEngine


class ToolRunner:
    """Cache, run, record — in that order, always."""

    def __init__(
        self,
        connection: AsyncConnection,
        *,
        registry: ToolRegistry = REGISTRY,
        clock: Clock = system_clock,
    ) -> None:
        self._c = connection
        self._registry = registry
        self._now = clock

    async def run(
        self,
        name: str,
        *,
        handle: DataHandle,
        contract: SchemaContract,
        engine: TableEngine,
        given: dict[str, Any] | None = None,
    ) -> Computation:
        """The result for these inputs — computed once, ever.

        ``args()`` is called before the fingerprint rather than after, and the
        order matters: it fills defaults and normalises types, so a request that
        omitted ``top_n`` and one that passed ``top_n=3`` hash the same. Hashing
        the raw request instead would give one question two cache entries and
        make the second caller pay for a computation that already existed.
        """
        registration = self._registry.get(name)
        tool = registration.tool
        args = tool.args(**(given or {}))

        computations = ComputationRepository(self._c)
        table, parents = await self._resolve(args, contract, computations)

        digest = fingerprint(
            tool_name=tool.name,
            tool_version=tool.version,
            args=args,
            dataset_id=contract.dataset_id,
            schema_contract_id=contract.id,
            parents=parents,
        )

        cached = await computations.find(digest)
        if cached is not None:
            return cached

        started = time.perf_counter()
        result = tool.execute(
            ExecContext(handle=handle, contract=contract, engine=engine, table=table), args
        )
        elapsed = int((time.perf_counter() - started) * 1000)

        now = self._now()
        await ToolVersionRepository(self._c).ensure(
            name=tool.name, version=tool.version, summary=tool.summary, now=now
        )
        return await computations.create(
            Computation(
                id=uuid.uuid4(),
                fingerprint=digest,
                tool_name=tool.name,
                tool_version=tool.version,
                args=args,
                dataset_id=contract.dataset_id,
                schema_contract_id=contract.id,
                result=result,
                computed_at=now,
                computed_by=handle.principal.user_id,
                duration_ms=elapsed,
                parents=parents,
            )
        )

    async def _resolve(
        self,
        args: dict[str, Any],
        contract: SchemaContract,
        computations: ComputationRepository,
    ) -> tuple[TableInput, tuple[str, ...]]:
        """What `table` names, and what that makes this computation a child of.

        Resolved **here rather than in the tool**, because reading a parent
        needs the database and §11.2's first rule is that a tool does no I/O
        beyond reading its input table. It is also the only place that can
        check the parent belongs to the dataset the caller was authorized for.

        A tool with no `table` argument gets the base dataset and no parents —
        the eight analyzers, which read the file and nothing else.
        """
        named = args.get("table", BASE)
        if named == BASE:
            return (base_table(contract), ())

        try:
            identifier = uuid.UUID(str(named))
        except ValueError as bad:
            raise ToolError(
                f"{named!r} is not a table; use {BASE!r} or the id of an earlier step"
            ) from bad

        parent = await computations.within(identifier, contract.dataset_id)
        if parent is None:
            # **Not found rather than forbidden**, and the dataset is in the
            # query rather than checked after it: a 403 here would confirm that
            # somebody else's computation exists (§13.3.1).
            raise ToolError(f"there is no step called {named!r} in this dataset")

        stored = parent.result.get("sql")
        if not isinstance(stored, str) or not stored:
            raise ToolError(
                f"{parent.tool_name} does not produce a table, so nothing can read from it"
            )
        # **Carried, not re-decided.** Whether these rows were computed is a
        # fact about the step that made them, and every step downstream
        # inherits it: filtering an aggregate leaves an aggregate.
        preview = parent.result.get("preview")
        marked = preview if isinstance(preview, dict) else {}
        size = marked.get("size_column")
        return (
            TableInput(
                sql=stored,
                columns=_columns_of(parent, contract),
                derived=bool(marked.get("derived")),
                size_column=size if isinstance(size, str) else None,
                ordered=bool(marked.get("ordered")),
            ),
            (parent.fingerprint,),
        )


def _columns_of(parent: Computation, contract: SchemaContract) -> tuple[ColumnSpec, ...]:
    """The schema of a table an earlier step produced.

    Read from the stored result rather than from the contract, because that is
    the whole point of a chain: after `derive_column` the table holds a column
    the contract has never heard of, and the step after it has to be able to
    name it.

    A column the contract *does* know keeps its real `ColumnSpec` — its
    detection reason and confidence are facts about the file that survive being
    filtered. Only genuinely new columns are marked as derived.
    """
    known = {spec.name: spec for spec in contract.columns}
    out: list[ColumnSpec] = []
    for ordinal, entry in enumerate(parent.result.get("columns") or ()):
        if not isinstance(entry, dict):  # pragma: no cover - our own shape
            continue
        name = str(entry.get("name", ""))
        existing = known.get(name)
        if existing is not None:
            out.append(replace(existing, ordinal=ordinal))
            continue
        try:
            logical = LogicalType(str(entry.get("logical_type")))
        except ValueError:  # pragma: no cover - our own vocabulary
            logical = LogicalType.UNSUPPORTED
        out.append(derived(name, logical, ordinal))
    return tuple(out)


__all__ = ["ToolRunner"]
