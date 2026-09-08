"""One parameter declaration, four readers (§11.2, D-019).

§11.2's consequence is stated as a sentence and had never been made true: *one
tool definition produces runtime validation, the manual form, the spec the LLM
is given, and the documentation*. Until this file there was one — `args()`
validated imperatively, and nothing else could read it. Tool discovery needs
the second (§12.2 stage 2 sends full specs), so the declaration arrives now
rather than as a copy of the validation written a second time and kept in step
by hand.

## Tiers are an egress rule, not a UI hint

| Tier | What it is | LLM sees it | Manual form |
|---|---|---|---|
| 1 | No default exists (the column, the target) | yes | always |
| 2 | Sensible default (`n_bins`, `top_n`) | yes | always, prefilled |
| 3 | Null policy, tie-breaking, precision, edge handling | **never** | under *Advanced* |

Tier 3 is withheld from the model on purpose (§11.5 Mechanism 5): depth stays
available to a person who knows what they are doing without widening the
surface where a model can be quietly wrong. `plot.transform` is the sharp case
— it reaches Vega-Lite's `aggregate`/`bin`/`calculate`, so a model that could
set it would compute numbers outside a Computation, which is INV-5.

## Normalisation is part of the fingerprint, not decoration

An argument left out and the same argument passed at its default are the same
question. `canonical_json` hashes them differently unless the default is filled
in here, and then the cache answers one question twice (§9.4).

**Every kind added here inherits that obligation, and two of them nearly broke
it.** `number` normalises to `float` because `canonical_json` hashes `0` and
`0.0` differently, so `min_share=0` and `min_share=0.0` would be two cache
entries for one question. `column_list` sorts and de-duplicates because
`subset=["b","a"]`, `["a","b"]` and `["a","a","b"]` all ask `duplicate_report`
the same thing — a subset is a set, and hashing it as a sequence would let the
same question be asked three ways and answered three times.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.expressions.grammar import ExpressionError, canonical, parse
from app.tools.contract import ToolError

Tier = Literal[1, 2, 3]
Kind = Literal[
    "column",
    "column_list",
    "text_list",
    "table",
    "expression",
    "integer",
    "number",
    "boolean",
    "enum",
]


@dataclass(frozen=True, slots=True)
class Param:
    """One argument, as every reader of it needs to see it."""

    name: str
    tier: Tier
    #: Written for the model as much as for the form. It is the only thing
    #: standing between `top_n=3` and a model that reads it as a row limit.
    description: str
    kind: Kind = "integer"
    #: `None` means tier 1: there is no value this could sensibly mean if the
    #: caller did not say. Paired with `optional=True` it means the opposite —
    #: absence is itself the answer.
    default: Any = None
    low: float | None = None
    high: float | None = None
    #: `enum` only. The complete set of accepted values.
    choices: tuple[str, ...] = field(default_factory=tuple)
    #: An argument whose absence is meaningful rather than missing.
    #: `outlier_scan.lower` is the case: not given means *no floor*, which is a
    #: different instruction from any number a default could pick.
    optional: bool = False

    @property
    def required(self) -> bool:
        return self.default is None and not self.optional


def validate(tool_name: str, params: tuple[Param, ...], given: dict[str, Any]) -> dict[str, Any]:
    """Everything the fingerprint will see, or a refusal that says which argument.

    Refusals name the argument rather than the type, because §12.3 step 6 hands
    this message back to the model and *"got str"* is not something a model can
    act on.
    """
    known = {param.name for param in params}
    unknown = sorted(set(given) - known)
    if unknown:
        raise ToolError(f"{tool_name} takes no argument named {unknown[0]!r}")

    out: dict[str, Any] = {}
    for param in params:
        supplied = given.get(param.name, param.default)

        if supplied is None:
            if param.optional:
                out[param.name] = None
                continue
            if param.kind == "column":
                raise ToolError(f"{tool_name} needs a column name for {param.name!r}")
            raise ToolError(f"{tool_name} needs a value for {param.name!r}")

        out[param.name] = _coerce(tool_name, param, supplied)
    return out


def _coerce(tool_name: str, param: Param, value: Any) -> Any:
    """One value, in the exact form the fingerprint will hash."""
    if param.kind == "column":
        if not isinstance(value, str) or not value:
            raise ToolError(f"{tool_name} needs a column name for {param.name!r}")
        return value

    if param.kind == "expression":
        # **Canonicalised here, and this is the whole reason `canonical` exists.**
        # §9.4 hashes `args`, so storing the raw text would make `[qty]>4` and
        # `[qty] > 4` two computations for one question. Parsing needs no schema
        # — only `analyse` does — so the normalisation can happen at the one
        # place every caller already goes through.
        if not isinstance(value, str) or not value.strip():
            raise ToolError(f"{param.name} cannot be empty")
        try:
            return canonical(parse(value))
        except ExpressionError as bad:
            raise ToolError(str(bad)) from bad

    if param.kind == "table":
        # A reference, not a name: either the base dataset or the id of a
        # Computation this chain already produced. The runner resolves it,
        # because resolving it needs the database and a tool may not have one.
        if not isinstance(value, str) or not value.strip():
            raise ToolError(f"{param.name} must name a table")
        return value.strip()

    if param.kind == "text_list":
        # **Order is kept and duplicates are kept**, unlike `column_list`.
        # A subset is a set; a list of measures is a layout. `[mean(a), sum(b)]`
        # and `[sum(b), mean(a)]` build the same groups and different columns,
        # and sorting them would quietly rearrange somebody's output.
        if not isinstance(value, list | tuple) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ToolError(f"{param.name} must be a list of names, got {value!r}")
        return [str(item).strip() for item in value]

    if param.kind == "column_list":
        if not isinstance(value, list | tuple) or any(
            not isinstance(item, str) or not item for item in value
        ):
            raise ToolError(f"{param.name} must be a list of column names, got {value!r}")
        # Sorted and de-duplicated: a subset is a set, and three spellings of
        # one question must not become three cache entries (§9.4).
        return sorted(set(value))

    if param.kind == "boolean":
        if not isinstance(value, bool):
            raise ToolError(f"{param.name} must be true or false, got {value!r}")
        return value

    if param.kind == "enum":
        if not isinstance(value, str):
            raise ToolError(f"{param.name} must be one of {', '.join(param.choices)}")
        lowered = value.strip().lower()
        if lowered not in param.choices:
            raise ToolError(
                f"{param.name} must be one of {', '.join(param.choices)}, got {value!r}"
            )
        return lowered

    if param.kind == "number":
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise ToolError(f"{param.name} must be a number, got {value!r}")
        # `float` always, never the `int` a caller may have written: §9.4 hashes
        # `0` and `0.0` differently and they are the same instruction.
        return _ranged(float(value), param)

    return _whole(value, param)


def _whole(value: Any, param: Param) -> int:
    """An integer inside its range, or a refusal that says which.

    ``bool`` is rejected before ``int`` because ``isinstance(True, int)`` is
    true in Python, and `top_n=True` silently meaning `top_n=1` is the kind of
    accepted nonsense that shows up as a wrong chart rather than an error.
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolError(f"{param.name} must be a whole number, got {value!r}")
    return int(_ranged(value, param))


def _ranged(value: float, param: Param) -> float:
    """Inside its bounds, or a refusal naming the whole range.

    Both ends are quoted when both exist, rather than only the one that was
    broken. §12.3 step 6 hands this back to the model as its one chance to
    correct itself, and *"at most 50"* teaches it nothing about the floor it is
    about to hit on the retry.
    """
    if param.low is None and param.high is None:
        return value
    if (param.low is not None and value < param.low) or (
        param.high is not None and value > param.high
    ):
        if param.low is not None and param.high is not None:
            span = f"between {_plain(param.low)} and {_plain(param.high)}"
        elif param.low is not None:
            span = f"at least {_plain(param.low)}"
        else:
            assert param.high is not None
            span = f"at most {_plain(param.high)}"
        raise ToolError(f"{param.name} must be {span}, got {_plain(value)}")
    return value


def _plain(value: float) -> str:
    """`50` rather than `50.0` in a message a model has to act on."""
    return f"{value:g}"


def json_schema(params: tuple[Param, ...], *, for_llm: bool = True) -> dict[str, Any]:
    """JSON Schema for these parameters, tier 3 withheld when the reader is a model."""
    shown = tuple(param for param in params if not (for_llm and param.tier == 3))
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param in shown:
        properties[param.name] = _property(param)
        if param.required:
            required.append(param.name)

    return {
        "type": "object",
        "properties": properties,
        "required": required,
        # A model that invents an argument name should be told, not guessed at.
        # §12.3 step 6 rejects on schema, and this is what makes it able to.
        "additionalProperties": False,
    }


def _property(param: Param) -> dict[str, Any]:
    entry: dict[str, Any] = {"description": param.description}

    if param.kind in ("column", "table", "expression"):
        entry["type"] = "string"
    elif param.kind in ("column_list", "text_list"):
        entry["type"] = "array"
        entry["items"] = {"type": "string"}
    elif param.kind == "boolean":
        entry["type"] = "boolean"
    elif param.kind == "enum":
        entry["type"] = "string"
        entry["enum"] = list(param.choices)
    else:
        entry["type"] = "integer" if param.kind == "integer" else "number"
        if param.low is not None:
            entry["minimum"] = param.low
        if param.high is not None:
            entry["maximum"] = param.high

    if param.default is not None:
        # The default as `validate` will store it, not as it was declared. A
        # schema announcing `()` while the fingerprint holds `[]` tells the
        # model one thing and the Run Log another, and the two are read by
        # people trying to explain the same call.
        entry["default"] = (
            sorted(set(param.default))
            if param.kind == "column_list"
            else list(param.default)
            if param.kind == "text_list"
            else param.default
        )
    return entry


__all__ = ["Kind", "Param", "Tier", "json_schema", "validate"]
