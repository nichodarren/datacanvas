"""What every tool declares about itself (§11.2).

One definition produces four things — runtime validation, the manual form, the
spec the LLM is given, and the documentation — and that is what makes
NFR-MAINT.1's *"adding a tool is one file"* achievable and INV-1 nearly free.

## What this file is, and what it is not yet

It is the registry and the declaration. It is **not** the Step executor: there
is no DAG here, no parents, no expression language, no copilot. Those arrive
with Phase 3 proper. What exists is the smallest thing that lets a tool run and
produce a Computation with a real fingerprint, because INV-5 says a number on
screen must come from one — and the Profile tab puts numbers on screen.

`version` and `applies_to` are declared and enforced from the first tool rather
than added later. INV-4 says the version rises whenever output could change, and
a version nobody declared cannot rise.

## Why `execute` takes a handle rather than a path

§13.3.1 L3: `DataHandle` is the only object that can reach bytes, and it is
proof of authorization rather than a container. A tool that accepted a path
would be a hole in the one gate this system has.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from app.domain.errors import DomainError

if TYPE_CHECKING:
    from app.authz.data_access import DataHandle
    from app.domain.data import SchemaContract
    from app.storage.engine import TableEngine
    from app.tools.parameters import Param
    from app.tools.tables import TableInput


@dataclass(frozen=True, slots=True)
class ExecContext:
    """Everything a tool is allowed to touch, handed to it per call (§11.2).

    Passed in rather than held on the tool, and that is the whole of §11.2's
    purity rule in practice: a tool that stored a connection or an engine would
    have state to get stale, and a registry of long-lived stateful objects is a
    registry of things that behave differently on the second call.

    ``handle`` rather than a path — §13.3.1 L3 makes ``DataHandle`` proof of
    authorization, and a tool that accepted a path would be the one hole in the
    one gate.
    """

    handle: DataHandle
    contract: SchemaContract
    engine: TableEngine
    #: The table this call reads, already resolved. For an analyzer that is the
    #: dataset; for a transform in a chain it is whatever the previous step
    #: produced, and its `columns` are what expressions resolve against —
    #: `derive_column` makes a column no contract has ever heard of.
    #:
    #: Resolved by the runner rather than by the tool, because resolving it
    #: needs the database and §11.2 says a tool does no I/O beyond reading its
    #: input table.
    table: TableInput | None = None

    @property
    def source(self) -> TableInput:
        """The input table, or a refusal that is a bug rather than bad input."""
        if self.table is None:  # pragma: no cover - the runner always resolves
            raise ToolError("this tool needs an input table and the runner gave none")
        return self.table


class ToolError(DomainError):
    """A tool could not answer. Never a crash the caller has to interpret."""


class UnknownTool(ToolError):
    """Asked for a tool that is not registered.

    Its own type because the API renders it as 404 while a genuine failure
    inside a tool is a 500 — one is a bad request, the other is our bug.
    """


class Tool(Protocol):
    """The shape every tool has, checked structurally rather than by base class.

    Inheritance would give tools a place to reach into shared state, and §11.2's
    first rule is purity: input in, result out, no I/O beyond reading the table.
    """

    name: str
    version: int
    summary: str

    #: Every argument, with its tier (§11.2, D-019). One declaration feeds the
    #: runtime validation, the spec §12.2 hands the model, and the manual form
    #: — because three hand-written copies of one shape is three things that
    #: must agree, and only one of them is the one that runs.
    parameters: tuple[Param, ...]

    def applies_to(self, contract: SchemaContract) -> bool:
        """Whether this tool is worth offering for this dataset at all.

        **Stage 0 of tool discovery (§12.2), and it is free.** A dataset with
        no datetime column should never see a time-based tool proposed, and
        deciding that here costs nothing and cannot be got wrong by a model.
        It also drives FR-E.3: a disabled tool in the catalogue with a reason
        beside it.
        """
        ...

    def args(self, **given: Any) -> dict[str, Any]:
        """Validate and normalise, returning exactly what enters the fingerprint.

        Normalisation is not cosmetic here. ``canonical_json`` hashes ``1`` and
        ``1.0`` differently, so a tool that lets both through has two cache
        entries for one question. Filling defaults in is part of the same job:
        an argument omitted and an argument given its default value are the same
        computation and must hash the same.
        """
        ...

    def execute(self, ctx: ExecContext, args: dict[str, Any]) -> dict[str, Any]:
        """Run, and return a JSON-serialisable bundle.

        A dict rather than a typed object because the shape belongs to the tool.
        §9.2 stores it as JSONB for the same reason: a `computation` table that
        knew every tool's shape would need a migration per tool, which is what
        NFR-MAINT.1 forbids.
        """
        ...


@dataclass(frozen=True, slots=True)
class Registration:
    """A tool and the metadata the catalogue needs about it."""

    tool: Tool
    category: str
    output_kind: str


class ToolRegistry:
    """Every tool this build ships, by name.

    A module-level dict would do the same and would also be writable from
    anywhere. This is the object `tests/unit/test_tool_registry.py` holds to its
    guarantees, and the object the API asks rather than a global somebody could
    have mutated at import time.
    """

    def __init__(self) -> None:
        self._tools: dict[str, Registration] = {}

    def register(self, tool: Tool, *, category: str, output_kind: str) -> None:
        existing = self._tools.get(tool.name)
        if existing is not None:
            # Two tools under one name is a silent overwrite: the second wins,
            # the first vanishes, and every Computation the first produced now
            # carries a name that resolves to different behaviour. INV-4 makes
            # (name, version) a promise, and this is where the promise is kept.
            raise ToolError(
                f"{tool.name!r} is already registered at version {existing.tool.version}"
            )
        if tool.version < 1:
            raise ToolError(f"{tool.name!r} declares version {tool.version}; versions start at 1")
        self._tools[tool.name] = Registration(tool=tool, category=category, output_kind=output_kind)

    def get(self, name: str) -> Registration:
        found = self._tools.get(name)
        if found is None:
            raise UnknownTool(name)
        return found

    def all(self) -> tuple[Registration, ...]:
        """Sorted by name, so a catalogue listing never depends on import order."""
        return tuple(self._tools[name] for name in sorted(self._tools))


#: The registry this build uses. Populated by `app.tools.__init__`.
REGISTRY = ToolRegistry()


def tool(*, category: str, output_kind: str) -> Callable[[type], type]:
    """Register a tool class at import time.

    A decorator rather than a call at the bottom of each module: the
    registration sits next to the definition, so a tool that exists and a tool
    that is reachable cannot drift apart — which is the same class of defect
    `test_frontend_wiring.py` catches one layer up.
    """

    def register(cls: type) -> type:
        REGISTRY.register(cls(), category=category, output_kind=output_kind)
        return cls

    return register


__all__ = [
    "REGISTRY",
    "ExecContext",
    "Registration",
    "Tool",
    "ToolError",
    "ToolRegistry",
    "UnknownTool",
    "tool",
]
