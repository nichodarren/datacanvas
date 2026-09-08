"""The semantic half of §11.3: a tree, a schema, and the SQL it may become.

## Why this is separate from the parser

`grammar.py` cannot produce SQL at all — it has no function that returns a
query, and no access to a column name that exists. **Everything that reaches
the database goes through here, and only for a tree that type-checked against
a real `SchemaContract` first.** That split is the point: a valid sentence in
the language and a meaningful one are different questions, and the second
needs the schema.

## The fact that decides the whole compiler

**Every column in a normalised Parquet file is physically `VARCHAR.**` Logical
type is our interpretation, stored in the contract; the bytes are text. So
`[Age] < 18` compiled to `"Age" < 18` would compare strings, and `"9" > "18"`
lexicographically. Not an error — a **wrong answer that looks right**, which is
the failure this project spends most of its effort refusing.

So a column reference compiles to the same guarded read the Profile tab uses:
the shape rule first, then the cast, and `NULL` for anything that does not
match. `age` holding `unknown` yields `NULL` in an expression exactly as it
yields nothing in a profile — one definition of what a column's values are,
shared rather than reimplemented (`storage/profile.py`).

## Division cannot raise

`x / 0` compiles with a `NULLIF` guard, so it is `NULL` rather than an error.
An expression that raises takes the whole tool call with it, and a tool call
that dies has no result to cite; a row that cannot be computed is a missing
value, which the rest of the system already knows how to say.

## What a type error buys

`[Name] < 18` is refused **here**, with a message naming the column and its
type, and never reaches the database. §12.3 step 6 hands that message back to
the model, so a wrong guess costs one rejection instead of a dead turn.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.domain.data import ColumnSpec
from app.domain.enums import LogicalType
from app.expressions.grammar import (
    FUNCTIONS,
    Between,
    Binary,
    Call,
    Column,
    ExpressionError,
    In,
    IsNull,
    Literal,
    Node,
    Unary,
    canonical,
    parse,
)
from app.storage.engine import _quote
from app.storage.profile import (
    _AS_MOMENT,
    _AS_NUMBER,
    _FALSE_WORDS,
    _PRESENT,
    _SLOT,
    _TRIM,
    _TRUE_WORDS,
)

#: The five types an expression deals in. `null` is the type of `null` alone:
#: it unifies with anything, which is what lets `coalesce([a], null)` mean what
#: a reader expects without a type variable machinery nobody needs here.
NUMBER = "number"
TEXT = "text"
BOOLEAN = "boolean"
DATE = "date"
NULL = "null"

#: How a column's logical type reads inside an expression. `categorical` and
#: `text` are both text: the distinction drives which tools are *offered*
#: (§FR-C rationale), not what a comparison means.
_AS_TYPE: dict[LogicalType, str] = {
    LogicalType.NUMERICAL: NUMBER,
    LogicalType.CATEGORICAL: TEXT,
    LogicalType.TEXT: TEXT,
    LogicalType.DATE: DATE,
    LogicalType.BOOLEAN: BOOLEAN,
}

#: `name -> (argument types, result)`. `None` in place of a type means *any*,
#: and a trailing `...` means the last type repeats.
#:
#: Exactly §11.3's list. Two of them needed a decision the document leaves
#: open, and both are stated rather than guessed at silently:
#:
#: * **`log` is the natural logarithm** (DuckDB `ln`), not base 10. In data
#:   work *log transform* means natural log almost without exception, and
#:   DuckDB's own `log` means base 10 — so the name had to be bound to one of
#:   them here rather than inherited by accident.
#: * **`weekday` is ISO** (1 = Monday … 7 = Sunday), because DuckDB's
#:   `dayofweek` starts the week on Sunday at 0 and half the world disagrees
#:   about which day that is. ISO has one answer.
#: * **`date_diff` counts whole days**, second argument minus first.
_SIGNATURES: dict[str, tuple[tuple[str | None, ...], str, bool]] = {
    "abs": ((NUMBER,), NUMBER, False),
    "round": ((NUMBER, NUMBER), NUMBER, False),
    "floor": ((NUMBER,), NUMBER, False),
    "ceil": ((NUMBER,), NUMBER, False),
    "log": ((NUMBER,), NUMBER, False),
    "sqrt": ((NUMBER,), NUMBER, False),
    "lower": ((TEXT,), TEXT, False),
    "upper": ((TEXT,), TEXT, False),
    "trim": ((TEXT,), TEXT, False),
    "length": ((TEXT,), NUMBER, False),
    "contains": ((TEXT, TEXT), BOOLEAN, False),
    "starts_with": ((TEXT, TEXT), BOOLEAN, False),
    "year": ((DATE,), NUMBER, False),
    "month": ((DATE,), NUMBER, False),
    "day": ((DATE,), NUMBER, False),
    "weekday": ((DATE,), NUMBER, False),
    "date_diff": ((DATE, DATE), NUMBER, False),
    "date": ((TEXT,), DATE, False),
    # Variadic, and their result type comes from the arguments rather than
    # from the table, so they are handled by name in `_call`.
    "coalesce": ((None,), NULL, True),
    "if": ((BOOLEAN, None, None), NULL, False),
}

#: `round(x)` is legal; `round(x, 2)` is legal. The count is a range, not a
#: number, so the optional tail is listed rather than inferred.
_OPTIONAL_FROM: dict[str, int] = {"round": 1}

#: The grammar and the type table describe the same set of functions, and a
#: function in one but not the other is either unparseable or untypeable. Held
#: at import time rather than in a test, because the failure is a language that
#: disagrees with itself and there is no version of that worth shipping.
assert set(_SIGNATURES) == FUNCTIONS, sorted(set(_SIGNATURES) ^ FUNCTIONS)

_ARITHMETIC = frozenset({"+", "-", "*", "/", "%"})
_COMPARISON = frozenset({"=", "!=", "<", "<=", ">", ">="})
_LOGICAL = frozenset({"and", "or"})

_SQL_OPERATOR = {"=": "=", "!=": "<>", "<": "<", "<=": "<=", ">": ">", ">=": ">="}


@dataclass(frozen=True, slots=True)
class Analysed:
    """One expression, checked and compiled."""

    #: The SQL fragment. Safe to interpolate **because nothing user-controlled
    #: reaches it unquoted**: identifiers go through `_quote`, strings through
    #: `_text`, and numbers through `repr` of a parsed float.
    sql: str
    type: str
    #: What `§9.4` hashes instead of the raw text, so two spellings of one
    #: expression are one computation.
    canonical: str
    #: Columns actually referenced. Feeds staleness later: a Step whose
    #: expression names a column the next contract retypes is a Step whose
    #: answer could change.
    columns: tuple[str, ...] = field(default_factory=tuple)


def analyse(source: str, against: Sequence[ColumnSpec], *, expect: str | None = None) -> Analysed:
    """Parse, type-check against these columns, compile. Or refuse, saying why.

    Takes **columns rather than a `SchemaContract`**, and that is not a
    convenience. A chain composes: `derive_column` produces a table with a
    column no contract has ever heard of, and the `aggregate` after it has to
    resolve `[tip_rate]` against what its *input* holds, not against what the
    file held. A signature that demanded a contract would have made the second
    step of every chain unexpressible.

    `expect` is what the caller needs the whole expression to be —
    `filter_rows` needs a boolean and `derive_column` takes anything. Checked
    here rather than at the call site so the refusal reads like every other
    refusal in the language.
    """
    tree = parse(source)
    columns = {spec.name: spec for spec in against}
    found: list[str] = []
    kind = _type_of(tree, columns, found)

    if expect is not None and kind not in (expect, NULL):
        raise ExpressionError(f"this expression is {kind}, and a {expect} is needed here")

    return Analysed(
        sql=_sql(tree, columns),
        type=kind,
        canonical=canonical(tree),
        # Sorted and de-duplicated: the order they were written in is not a
        # fact about the expression, and two spellings must not differ here
        # either.
        columns=tuple(sorted(set(found))),
    )


# ------------------------------------------------------------------ types ---


def _type_of(node: Node, columns: dict[str, ColumnSpec], found: list[str]) -> str:
    if isinstance(node, Literal):
        return node.kind

    if isinstance(node, Column):
        spec = columns.get(node.name)
        if spec is None:
            known = ", ".join(sorted(columns)[:8]) or "none"
            raise ExpressionError(f"no column named {node.name!r}; this dataset has: {known}")
        kind = _AS_TYPE.get(spec.logical_type)
        if kind is None:
            raise ExpressionError(
                f"{node.name!r} is {spec.logical_type.value} and cannot be used in an expression"
            )
        found.append(node.name)
        return kind

    if isinstance(node, Unary):
        inner = _type_of(node.operand, columns, found)
        if node.op == "not":
            _want(inner, BOOLEAN, "'not'")
            return BOOLEAN
        _want(inner, NUMBER, "negation")
        return NUMBER

    if isinstance(node, Binary):
        left = _type_of(node.left, columns, found)
        right = _type_of(node.right, columns, found)

        if node.op in _LOGICAL:
            _want(left, BOOLEAN, f"'{node.op}'")
            _want(right, BOOLEAN, f"'{node.op}'")
            return BOOLEAN

        if node.op in _ARITHMETIC:
            _want(left, NUMBER, f"'{node.op}'")
            _want(right, NUMBER, f"'{node.op}'")
            return NUMBER

        # Comparison. Same type on both sides, and `null` matches anything so
        # `[a] = null` parses and is simply always unknown, the way SQL means.
        if NULL not in (left, right) and left != right:
            raise ExpressionError(f"cannot compare {left} with {right} using '{node.op}'")
        return BOOLEAN

    if isinstance(node, Between):
        value = _type_of(node.value, columns, found)
        for bound in (node.low, node.high):
            edge = _type_of(bound, columns, found)
            if NULL not in (value, edge) and value != edge:
                raise ExpressionError(f"cannot range {value} against {edge} in 'between'")
        return BOOLEAN

    if isinstance(node, In):
        value = _type_of(node.value, columns, found)
        for option in node.options:
            kind = _type_of(option, columns, found)
            if NULL not in (value, kind) and value != kind:
                raise ExpressionError(f"an 'in' list of {value} cannot hold a {kind}")
        return BOOLEAN

    if isinstance(node, IsNull):
        _type_of(node.value, columns, found)
        return BOOLEAN

    return _call_type(node, columns, found)


def _call_type(node: Call, columns: dict[str, ColumnSpec], found: list[str]) -> str:
    signature = _SIGNATURES.get(node.name)
    if signature is None:
        known = ", ".join(sorted(_SIGNATURES))
        raise ExpressionError(f"there is no function called {node.name!r}. Available: {known}")

    wanted, result, variadic = signature
    kinds = [_type_of(argument, columns, found) for argument in node.args]

    if node.name == "coalesce":
        if not kinds:
            raise ExpressionError("coalesce needs at least one value")
        real = [kind for kind in kinds if kind != NULL]
        if len({*real}) > 1:
            raise ExpressionError(f"coalesce cannot mix {' and '.join(sorted(set(real)))}")
        return real[0] if real else NULL

    if node.name == "if":
        if len(kinds) != 3:
            raise ExpressionError("if takes a condition and two values")
        _want(kinds[0], BOOLEAN, "the condition of 'if'")
        left, right = kinds[1], kinds[2]
        if NULL not in (left, right) and left != right:
            raise ExpressionError(f"the two branches of 'if' are {left} and {right}")
        return left if left != NULL else right

    least = _OPTIONAL_FROM.get(node.name, len(wanted))
    if not (least <= len(kinds) <= len(wanted)) and not variadic:
        expected = f"{least} or {len(wanted)}" if least != len(wanted) else str(len(wanted))
        raise ExpressionError(f"{node.name} takes {expected} argument(s), got {len(kinds)}")

    for index, kind in enumerate(kinds):
        want = wanted[min(index, len(wanted) - 1)]
        if want is not None and kind not in (want, NULL):
            raise ExpressionError(
                f"argument {index + 1} of {node.name} is {kind}, and a {want} is needed"
            )
    return result


def _want(found: str, wanted: str, where: str) -> None:
    if found not in (wanted, NULL):
        raise ExpressionError(f"{where} needs a {wanted}, got {found}")


# ------------------------------------------------------------------- SQL ----


def _sql(node: Node, columns: dict[str, ColumnSpec]) -> str:
    if isinstance(node, Literal):
        return _literal(node)

    if isinstance(node, Column):
        return read_column(node.name, columns)

    if isinstance(node, Unary):
        inner = _sql(node.operand, columns)
        return f"(NOT {inner})" if node.op == "not" else f"(-{inner})"

    if isinstance(node, Binary):
        left = _sql(node.left, columns)
        right = _sql(node.right, columns)
        if node.op in _LOGICAL:
            return f"({left} {node.op.upper()} {right})"
        if node.op in ("/", "%"):
            # Division cannot raise. A row that cannot be computed is a missing
            # value; an expression that errors is a dead tool call.
            return f"({left} {node.op} NULLIF({right}, 0))"
        if node.op in _ARITHMETIC:
            return f"({left} {node.op} {right})"
        return f"({left} {_SQL_OPERATOR[node.op]} {right})"

    if isinstance(node, Between):
        word = "NOT BETWEEN" if node.negated else "BETWEEN"
        value = _sql(node.value, columns)
        return f"({value} {word} {_sql(node.low, columns)} AND {_sql(node.high, columns)})"

    if isinstance(node, In):
        word = "NOT IN" if node.negated else "IN"
        options = ", ".join(_sql(option, columns) for option in node.options)
        return f"({_sql(node.value, columns)} {word} ({options}))"

    if isinstance(node, IsNull):
        word = "IS NOT NULL" if node.negated else "IS NULL"
        return f"({_sql(node.value, columns)} {word})"

    return _call_sql(node, columns)


def _call_sql(node: Call, columns: dict[str, ColumnSpec]) -> str:
    args = [_sql(argument, columns) for argument in node.args]

    if node.name == "if":
        return f"(CASE WHEN {args[0]} THEN {args[1]} ELSE {args[2]} END)"
    if node.name == "log":
        return f"ln({args[0]})"
    if node.name == "weekday":
        return f"isodow({args[0]})"
    if node.name == "date_diff":
        return f"date_diff('day', {args[0]}, {args[1]})"
    if node.name == "date":
        # The same shape-then-cast discipline as a column: a string that is not
        # a date becomes NULL rather than an error or a guess.
        return f"try_cast({args[0]} AS TIMESTAMP)"
    if node.name == "length":
        return f"length({args[0]})"

    # Everything else is named the same in DuckDB, and the name came from a
    # fixed table rather than from the input, so it cannot be anything else.
    return f"{node.name}({', '.join(args)})"


def read_column(name: str, columns: dict[str, ColumnSpec]) -> str:
    """One column, read the way the rest of the system reads it.

    Shared with `storage/profile.py` rather than rewritten: two definitions of
    *what this column's values are* is two answers to the same question, and
    only one of them would be on screen.

    ⚠️ **Only text is read through the shape rules**, and the distinction cost
    a chain the first time it ran. A column out of the Parquet file is VARCHAR,
    so `[Age] < 18` needs the regex-then-cast or it compares strings. A column
    a previous step *computed* is already a DOUBLE — `tip_rate` from
    `[tip] / [total_bill]` — and applying `trim()` to it fails outright, which
    was the good outcome: the shape rules are a rule about **text in a file**,
    and running them over a computed value is a category error that would
    otherwise have to be caught by noticing a wrong number.
    """
    spec = columns[name]
    logical = spec.logical_type
    quoted = _quote(name)

    if not spec.physical_type.upper().startswith("VARCHAR"):
        return quoted

    if logical is LogicalType.NUMERICAL:
        return f"({_AS_NUMBER.replace(_SLOT, quoted)})"
    if logical is LogicalType.DATE:
        return f"({_AS_MOMENT.replace(_SLOT, quoted)})"
    if logical is LogicalType.BOOLEAN:
        present = _PRESENT.replace(_SLOT, quoted)
        trimmed = _TRIM.replace(_SLOT, quoted)
        return (
            f"(CASE WHEN {present} AND lower({trimmed}) IN {_TRUE_WORDS} THEN true"
            f" WHEN {present} AND lower({trimmed}) IN {_FALSE_WORDS} THEN false END)"
        )
    present = _PRESENT.replace(_SLOT, quoted)
    trimmed = _TRIM.replace(_SLOT, quoted)
    return f"(CASE WHEN {present} THEN {trimmed} END)"


def _literal(node: Literal) -> str:
    if node.kind == NULL:
        return "NULL"
    if node.kind == BOOLEAN:
        return "true" if node.value else "false"
    if node.kind == TEXT:
        return _text(str(node.value))
    return repr(node.value)


def _text(value: str) -> str:
    """A string literal, quoted the one way that is complete.

    Doubling the quote is the standard escape and there is no sequence that
    closes the literal early once every `'` is doubled — the same argument
    `_quote` makes for identifiers, and the same reason it is written out
    rather than assumed.
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


__all__ = [
    "BOOLEAN",
    "DATE",
    "NULL",
    "NUMBER",
    "TEXT",
    "Analysed",
    "analyse",
    "read_column",
]
