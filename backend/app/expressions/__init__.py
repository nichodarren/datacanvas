"""The expression language (§11.3, D-003).

Two halves, and the split is the safety property. `grammar` turns text into a
tree and **cannot produce SQL**; `analyse` is the only thing that can, and only
for a tree that type-checked against a real `SchemaContract` first.

    from app.expressions import ExpressionError, analyse

    analysed = analyse("[Age] < 18", contract, expect="boolean")
    analysed.sql        # the guarded DuckDB fragment
    analysed.canonical  # what §9.4 hashes, so two spellings are one question
    analysed.columns    # what it read, for staleness later
"""

from __future__ import annotations

from app.expressions.analyse import (
    BOOLEAN,
    DATE,
    NULL,
    NUMBER,
    TEXT,
    Analysed,
    analyse,
    read_column,
)
from app.expressions.grammar import ExpressionError, canonical, parse

__all__ = [
    "BOOLEAN",
    "DATE",
    "NULL",
    "NUMBER",
    "TEXT",
    "Analysed",
    "ExpressionError",
    "analyse",
    "canonical",
    "parse",
    "read_column",
]
