"""The planner's step 7, over the machinery the manual path already uses.

## Why this is an adapter and not a second runner

§12.3 step 7 says *run it as a Step, through the Step Executor — the same path
as manual*. The value of that sentence is entirely in **same**: two paths to
running a tool would be two places where caching, fingerprinting and INV-4 have
to agree, and only one of them would be the one anybody tests. So this converts
between two shapes and does nothing else.

## What it does not do, and cannot

It does not choose a tool, does not retry, and does not decide what may be sent
back — those are the planner's, and the planner has no way to reach data except
through here. It also does not open the dataset: it is handed a `DataHandle`,
which §13.3.1 L3 makes proof of authorization rather than a container, so a
planner turn cannot read a dataset its caller was not allowed to open.

⚠️ **`Step` does not exist yet.** The reference this returns is a
`computation_id`, which §12.5 names in its own rule, so citations are already
what the contract asks for. What is missing is the Run Log row above it, and it
arrives with the `step` table in Phase 3's first migration (D-049 put the
copilot ahead of that work on purpose).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.tools.runner import ToolRunner

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle
    from app.domain.data import SchemaContract
    from app.storage.engine import TableEngine


class RunnerExecutor:
    """One dataset, one contract, one engine — bound once, called many times."""

    def __init__(
        self,
        runner: ToolRunner,
        *,
        handle: DataHandle,
        contract: SchemaContract,
        engine: TableEngine,
    ) -> None:
        self._runner = runner
        self._handle = handle
        self._contract = contract
        self._engine = engine

    async def run(self, tool_name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """`(citable reference, bundle)`.

        The arguments arrive already normalised by the planner's step 6, and
        `ToolRunner` normalises again on the way in. That is not waste: the
        runner is also the manual path's entry point and cannot assume its
        caller validated anything, and `args()` is idempotent — normalising
        twice yields the same dict and therefore the same fingerprint.
        """
        computation = await self._runner.run(
            tool_name,
            handle=self._handle,
            contract=self._contract,
            engine=self._engine,
            given=args,
        )
        return (str(computation.id), computation.result)


__all__ = ["RunnerExecutor"]
