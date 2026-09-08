"""The syntax half of §11.3: text in, tree out. No data, no SQL, no schema.

## Why a real parser rather than a regex

§11.3 rejects raw SQL (injection, and a model can write anything) and rejects
`eval` (P1, flatly). What is left is a closed grammar, and a closed grammar has
to actually be closed: the only way to know that `[a] + [b]` is allowed and
`[a]; DROP TABLE x` is not is to have a definition of what a sentence in this
language *is*, and to reject everything else by construction. A pattern that
looks for bad things is a list of what somebody thought of.

So nothing here can produce SQL. This module turns text into a tree of the
eleven node types below, or refuses. `analyse.py` is the only thing that can
turn a tree into a query, and it will only do it for a tree that type-checks
against a real schema.

## The one place the documented grammar is ambiguous

§11.3 writes column references as `[name]` **and** list membership as
`in [...]`. Those collide: in `[x] in [2024]`, the `[2024]` is either a list
holding the number 2024 or a column named `2024` — and a column named for a
year is entirely ordinary in a spreadsheet.

Resolved by **parse context rather than by changing the grammar**: after `in`,
a `[` always opens a list, and everywhere else it opens a column reference. The
parser already knows which one it is standing in, so this costs nothing, and
the documented notation survives. A list element that really is a column is
still writable as `[x] in [[other]]`, which is ugly and correct.

## Canonical form, and where it stops

`canonical()` re-renders a tree to one spelling, which is what the fingerprint
hashes (§9.4). `[qty]>4` and `[qty] > 4` parse to the same tree and therefore
to the same bytes, so they are one computation and one cache entry — the open
question the project notes recorded before this work started.

**It stops at structure.** `4 < [qty]` and `[qty] > 4` mean the same thing and
canonicalise differently, and making them agree means an algebraic normaliser:
commutativity, then associativity, then constant folding, then De Morgan. That
is R-6's failure mode written out — *week two and still adding grammar* — and
the cost of stopping here is one extra cache entry for a spelling nobody uses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.domain.errors import DomainError


class ExpressionError(DomainError):
    """The expression could not be read, or means nothing against this schema.

    One error type for the whole language, because §12.3 step 6 hands the
    message back to a model and *what kind of error* is not a distinction it
    can act on. What it can act on is **where**, so every message carries the
    position.
    """


# --------------------------------------------------------------- the tree ---


@dataclass(frozen=True, slots=True)
class Literal:
    """`42`, `"text"`, `true`, `null`, `date("2024-01-01")`."""

    value: Any
    #: `number`, `text`, `boolean`, `date` or `null`. Decided by the lexer from
    #: the spelling, never inferred later.
    kind: str


@dataclass(frozen=True, slots=True)
class Column:
    """`[name]`. Whether it exists is `analyse`'s question, not this one."""

    name: str


@dataclass(frozen=True, slots=True)
class Unary:
    op: str
    operand: Node


@dataclass(frozen=True, slots=True)
class Binary:
    op: str
    left: Node
    right: Node


@dataclass(frozen=True, slots=True)
class Between:
    value: Node
    low: Node
    high: Node
    negated: bool = False


@dataclass(frozen=True, slots=True)
class In:
    value: Node
    options: tuple[Node, ...]
    negated: bool = False


@dataclass(frozen=True, slots=True)
class IsNull:
    value: Node
    negated: bool = False


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    args: tuple[Node, ...]


Node = Literal | Column | Unary | Binary | Between | In | IsNull | Call


# ------------------------------------------------------------------ lexer ---


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    text: str
    at: int


#: Longest first, so `<=` is never read as `<` followed by `=`.
_OPERATORS = ("<=", ">=", "!=", "<>", "=", "<", ">", "+", "-", "*", "/", "%")

#: Words that are grammar rather than function names.
_KEYWORDS = frozenset({"and", "or", "not", "in", "between", "is", "null", "true", "false"})

#: Every function this language has, and **the grammar owns this list**.
#:
#: ⚠️ It lived only in `analyse._SIGNATURES` at first, so `parse("eval(1)")`
#: and `parse("__import__('os')")` both **succeeded** — harmless, because
#: nothing can produce SQL without `analyse` and `analyse` refuses an unknown
#: name, but the closure was one layer further back than this module claimed.
#: §11.3 lists the functions as part of the grammar rather than as a library,
#: and a claim about where a boundary is should be true where it is written.
#: `test_expressions.py` pins the two lists to each other.
FUNCTIONS = frozenset(
    {
        "abs",
        "round",
        "floor",
        "ceil",
        "log",
        "sqrt",
        "lower",
        "upper",
        "trim",
        "length",
        "contains",
        "starts_with",
        "year",
        "month",
        "day",
        "weekday",
        "date_diff",
        "date",
        "coalesce",
        "if",
    }
)

_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: How long an expression may be. Not a security boundary — the grammar is that
#: — but a parser handed a megabyte of nested parentheses should say no rather
#: than recurse until the interpreter does it for us.
MAX_LENGTH = 4_000

#: How deep the tree may nest, for the same reason and enforced in the parser
#: where recursion actually happens.
MAX_DEPTH = 40


def _matching(source: str, opened: int) -> int:
    """The `]` that closes the `[` at `opened`, counting depth.

    Scanning to the **first** `]` was the first version, and it broke two real
    things at once: `[x] in [[a], [b]]` cut the list open at the first inner
    close, and a column named `total [USD]` — a spreadsheet header, not a
    hypothetical — became unreachable while still parsing.

    A column name holding an unbalanced bracket still cannot be written. That
    is a real limit and it is stated rather than worked around: escaping would
    add a second spelling for every name, which the canonical form would then
    have to choose between.
    """
    depth = 0
    for i in range(opened, len(source)):
        if source[i] == "[":
            depth += 1
        elif source[i] == "]":
            depth -= 1
            if depth == 0:
                return i
    raise ExpressionError(f"unclosed [ at position {opened}")


def tokenise(source: str) -> list[Token]:
    """Text to tokens, or a refusal naming the character that stopped it."""
    if len(source) > MAX_LENGTH:
        raise ExpressionError(f"expression is longer than {MAX_LENGTH:,} characters")

    tokens: list[Token] = []
    i = 0
    while i < len(source):
        char = source[i]

        if char.isspace():
            i += 1
            continue

        if char == "[":
            end = _matching(source, i)
            # The raw text between the brackets, untouched. A column called
            # `total (USD)` is a column, and trimming or normalising here would
            # make it unreachable while looking like it worked.
            tokens.append(Token("column", source[i + 1 : end], i))
            i = end + 1
            continue

        if char == "]":
            tokens.append(Token("]", "]", i))
            i += 1
            continue

        if char in "\"'":
            end = source.find(char, i + 1)
            if end < 0:
                raise ExpressionError(f"unclosed string at position {i}")
            tokens.append(Token("string", source[i + 1 : end], i))
            i = end + 1
            continue

        if char.isdigit():
            found = _NUMBER.match(source, i)
            assert found is not None
            tokens.append(Token("number", found.group(), i))
            i = found.end()
            continue

        if char in "()":
            tokens.append(Token(char, char, i))
            i += 1
            continue

        if char == ",":
            tokens.append(Token(",", ",", i))
            i += 1
            continue

        found = _WORD.match(source, i)
        if found is not None:
            word = found.group()
            lowered = word.lower()
            tokens.append(Token("keyword" if lowered in _KEYWORDS else "name", lowered, i))
            i = found.end()
            continue

        for operator in _OPERATORS:
            if source.startswith(operator, i):
                tokens.append(Token("operator", operator, i))
                i += len(operator)
                break
        else:
            raise ExpressionError(f"{char!r} is not part of this language (position {i})")

    tokens.append(Token("end", "", len(source)))
    return tokens


# ----------------------------------------------------------------- parser ---

#: Binding power, loosest first. Comparison sits between logic and arithmetic
#: so `[a] + 1 > [b]` reads the way anybody writing it expects.
_COMPARISONS = frozenset({"=", "!=", "<>", "<", "<=", ">", ">="})


class _Parser:
    """Precedence climbing. One token of lookahead, no backtracking."""

    def __init__(self, tokens: list[Token]) -> None:
        self._tokens = tokens
        self._i = 0
        self._depth = 0

    # -- plumbing --

    @property
    def _peek(self) -> Token:
        return self._tokens[self._i]

    def _take(self) -> Token:
        token = self._tokens[self._i]
        self._i += 1
        return token

    def _at(self, kind: str, text: str | None = None) -> bool:
        token = self._peek
        return token.kind == kind and (text is None or token.text == text)

    def _expect(self, kind: str, text: str | None = None) -> Token:
        if not self._at(kind, text):
            wanted = text or kind
            found = self._peek.text or "the end of the expression"
            raise ExpressionError(
                f"expected {wanted!r} at position {self._peek.at}, found {found!r}"
            )
        return self._take()

    # -- grammar --

    def parse(self) -> Node:
        node = self._or()
        if not self._at("end"):
            raise ExpressionError(f"unexpected {self._peek.text!r} at position {self._peek.at}")
        return node

    def _or(self) -> Node:
        node = self._and()
        while self._at("keyword", "or"):
            self._take()
            node = Binary("or", node, self._and())
        return node

    def _and(self) -> Node:
        node = self._not()
        while self._at("keyword", "and"):
            self._take()
            node = Binary("and", node, self._not())
        return node

    def _not(self) -> Node:
        if self._at("keyword", "not"):
            self._take()
            return Unary("not", self._not())
        return self._comparison()

    def _comparison(self) -> Node:
        node = self._sum()

        # `is null` / `is not null`
        if self._at("keyword", "is"):
            self._take()
            negated = False
            if self._at("keyword", "not"):
                self._take()
                negated = True
            self._expect("keyword", "null")
            return IsNull(node, negated=negated)

        negated = False
        if self._at("keyword", "not"):
            # Only `not in` and `not between` may follow a value; a bare `not`
            # here is a expression like `[a] not [b]`, which means nothing.
            self._take()
            negated = True
            if not (self._at("keyword", "in") or self._at("keyword", "between")):
                raise ExpressionError(
                    f"'not' at position {self._peek.at} must be followed by 'in' or 'between'"
                )

        if self._at("keyword", "in"):
            self._take()
            return In(node, self._list(), negated=negated)

        if self._at("keyword", "between"):
            self._take()
            low = self._sum()
            self._expect("keyword", "and")
            return Between(node, low, self._sum(), negated=negated)

        if negated:  # pragma: no cover - the check above already refused
            raise ExpressionError("dangling 'not'")

        if self._at("operator") and self._peek.text in _COMPARISONS:
            op = self._take().text
            return Binary("!=" if op == "<>" else op, node, self._sum())
        return node

    def _list(self) -> tuple[Node, ...]:
        """`[a, b, c]`, and here a `[` is a list rather than a column.

        The whole of the ambiguity resolution, and it is this one line of
        context: the parser knows it has just consumed `in`.
        """
        self._expect_open_list()
        options = [self._or()]
        while self._at(","):
            self._take()
            options.append(self._or())
        self._expect("]")
        if not options:  # pragma: no cover - `_or` raises on an empty list first
            raise ExpressionError("an 'in' list cannot be empty")
        return tuple(options)

    def _expect_open_list(self) -> None:
        # A `[` was lexed as a column token, because the lexer cannot know it
        # is standing after `in`. Unpick it: the column's text is the first
        # element, re-lexed here where the context is known.
        if not self._at("column"):
            raise ExpressionError(f"expected '[' after 'in' at position {self._peek.at}")
        token = self._take()
        inner = tokenise(token.text)
        self._tokens[self._i : self._i] = inner[:-1]  # drop the inner `end`
        self._tokens.insert(self._i + len(inner) - 1, Token("]", "]", token.at))

    def _sum(self) -> Node:
        node = self._product()
        while self._at("operator") and self._peek.text in ("+", "-"):
            op = self._take().text
            node = Binary(op, node, self._product())
        return node

    def _product(self) -> Node:
        node = self._unary()
        while self._at("operator") and self._peek.text in ("*", "/", "%"):
            op = self._take().text
            node = Binary(op, node, self._unary())
        return node

    def _unary(self) -> Node:
        if self._at("operator") and self._peek.text == "-":
            self._take()
            return Unary("-", self._unary())
        return self._primary()

    def _primary(self) -> Node:
        self._depth += 1
        if self._depth > MAX_DEPTH:
            raise ExpressionError(f"expression nests deeper than {MAX_DEPTH} levels")
        try:
            return self._primary_inner()
        finally:
            self._depth -= 1

    def _primary_inner(self) -> Node:
        token = self._peek

        if token.kind == "(":
            self._take()
            node = self._or()
            self._expect(")")
            return node

        if token.kind == "column":
            self._take()
            if not token.text.strip():
                raise ExpressionError(f"empty column reference at position {token.at}")
            return Column(token.text)

        if token.kind == "number":
            self._take()
            text = token.text
            return Literal(float(text) if "." in text else int(text), "number")

        if token.kind == "string":
            self._take()
            return Literal(token.text, "text")

        if token.kind == "keyword" and token.text in ("true", "false"):
            self._take()
            return Literal(token.text == "true", "boolean")

        if token.kind == "keyword" and token.text == "null":
            self._take()
            return Literal(None, "null")

        if token.kind == "name":
            self._take()
            if token.text not in FUNCTIONS:
                known = ", ".join(sorted(FUNCTIONS))
                raise ExpressionError(
                    f"there is no function called {token.text!r} "
                    f"(position {token.at}). Available: {known}"
                )
            self._expect("(")
            args: list[Node] = []
            if not self._at(")"):
                args.append(self._or())
                while self._at(","):
                    self._take()
                    args.append(self._or())
            self._expect(")")
            return Call(token.text, tuple(args))

        found = token.text or "the end of the expression"
        raise ExpressionError(f"unexpected {found!r} at position {token.at}")


def parse(source: str) -> Node:
    """Text to tree, or `ExpressionError` saying where it stopped."""
    if not source or not source.strip():
        raise ExpressionError("an expression cannot be empty")
    return _Parser(tokenise(source)).parse()


# -------------------------------------------------------------- canonical ---


def canonical(node: Node) -> str:
    """One spelling per tree, which is what §9.4 hashes.

    Fully parenthesised rather than minimally: precedence is already in the
    tree, so re-deriving which parentheses are redundant would be a second
    implementation of the parser's own rules, kept in step by hand. The
    canonical form is read by machines and by anyone debugging a cache miss,
    and both are better served by unambiguous than by pretty.
    """
    if isinstance(node, Literal):
        if node.kind == "null":
            return "null"
        if node.kind == "boolean":
            return "true" if node.value else "false"
        if node.kind == "text":
            escaped = str(node.value).replace('"', '\\"')
            return f'"{escaped}"'
        return repr(node.value)

    if isinstance(node, Column):
        return f"[{node.name}]"

    if isinstance(node, Unary):
        return f"({node.op} {canonical(node.operand)})"

    if isinstance(node, Binary):
        return f"({canonical(node.left)} {node.op} {canonical(node.right)})"

    if isinstance(node, Between):
        word = "not between" if node.negated else "between"
        return f"({canonical(node.value)} {word} {canonical(node.low)} and {canonical(node.high)})"

    if isinstance(node, In):
        word = "not in" if node.negated else "in"
        options = ", ".join(canonical(option) for option in node.options)
        return f"({canonical(node.value)} {word} [{options}])"

    if isinstance(node, IsNull):
        word = "is not null" if node.negated else "is null"
        return f"({canonical(node.value)} {word})"

    arguments = ", ".join(canonical(argument) for argument in node.args)
    return f"{node.name}({arguments})"


__all__ = [
    "FUNCTIONS",
    "MAX_DEPTH",
    "MAX_LENGTH",
    "Between",
    "Binary",
    "Call",
    "Column",
    "ExpressionError",
    "In",
    "IsNull",
    "Literal",
    "Node",
    "Token",
    "Unary",
    "canonical",
    "parse",
    "tokenise",
]
