"""Closed vocabularies of the domain.

``StrEnum`` so that the stored representation is the readable value: a database
dump, a log line, and an audit export all say ``"balanced"`` rather than ``2``.
Numeric enum values are the kind of thing that gets renumbered once and then
silently reinterprets years of history.
"""

from __future__ import annotations

from enum import StrEnum, unique


@unique
class UserStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


# ``Role`` — owner / editor / viewer — was removed by D-039 with FR-A.5. It is
# not commented out here: an enum nothing constructs is a vocabulary that drifts
# out of step with the schema, and the schema no longer has a column for it.
# What it encoded lives in D-039 and in migration 0004's downgrade.


@unique
class PrivacyMode(StrEnum):
    """LLM egress policy, per account since D-039 (§13.5.2).

    Default is ``balanced`` (OQ-4). It lives on ``user_policy`` now; the table
    moved, the vocabulary did not.
    """

    STRICT = "strict"
    BALANCED = "balanced"
    FULL = "full"
    LOCAL = "local"


@unique
class LogicalType(StrEnum):
    """How a column is read (FR-C).

    Five types, and one marker that is not a type at all.

    ``categorical`` is separate from ``text`` on purpose: the logical type
    decides which tools are offered and how a profile renders (§FR-C rationale).

    ## What the narrowing from nine cost, and what it did not

    ``integer``/``decimal`` and ``date``/``datetime`` were merged on 2026-08-21.
    Neither pair was ever treated differently by §11.7.3 — each shared one
    profile table — and the distinction inside each pair survives where it was
    always recorded: ``physical_type`` still says BIGINT or DOUBLE, DATE or
    TIMESTAMP. What shrank is the vocabulary a person has to choose from, not
    what the system knows.

    ``duration`` went because nothing produced it. It appeared in this enum and
    in no branch of ``schema/inference.py`` — a type no column could ever have.

    ## Why ``unsupported`` survives outside the five

    It is not a type, it is the absence of one: ``inference`` returns it for a
    column whose physical type is not scalar — a struct, a list — because the
    MVP works on flat tables (§9.6). Folding it into ``text`` would claim a
    nested column is text and open every text tool to it, which is precisely the
    plausible guess P6 forbids.

    So the system can produce six values and a user may choose five.
    ``SELECTABLE`` below is that distinction, and it is the list the API's
    override literal is checked against.
    """

    NUMERICAL = "numerical"
    CATEGORICAL = "categorical"
    TEXT = "text"
    DATE = "date"
    BOOLEAN = "boolean"

    #: Produced by the system, never chosen by a person. See the class docstring.
    UNSUPPORTED = "unsupported"

    @property
    def is_selectable(self) -> bool:
        """Whether a user may correct a column *to* this type (FR-C.2)."""
        return self is not LogicalType.UNSUPPORTED


#: The five a person may pick from when correcting a column (FR-C.2).
#:
#: Derived rather than listed, so adding a type to the enum cannot leave this
#: behind. ``test_api_schemas.py`` holds the wire literal against it.
SELECTABLE_LOGICAL_TYPES = tuple(t for t in LogicalType if t.is_selectable)


@unique
class SourceFormat(StrEnum):
    """Upload formats the MVP accepts (FR-B.1).

    A closed vocabulary rather than a MIME string, because **D-027 decides the
    format by parsing the file, not by reading its label**. A value here means
    "this parsed as X", which is a fact; a MIME type means "something claimed
    X", which is not.
    """

    CSV = "csv"
    TSV = "tsv"
    PARQUET = "parquet"
    XLSX = "xlsx"
    JSON = "json"

    @property
    def is_delimited_text(self) -> bool:
        """True when the file needs a dialect before it can be read at all."""
        return self in {SourceFormat.CSV, SourceFormat.TSV}


# `ColumnRole` — identifier / measure / dimension / timestamp / ignored — was
# removed with FR-C.5 on 2026-08-21. Four of the five never reached a single
# branch anywhere: `aggregate` takes `group_by` and `measures` as arguments per
# call rather than reading them off a column, so nothing consumed them. The
# fifth, `identifier`, had one job — suppressing mean and histogram on a column
# of ids — and that job is better done from the data than from a declaration
# nobody could set. See the note in `app/schema/inference.py`.


@unique
class RouteClass(StrEnum):
    """Tenancy classification every HTTP route must declare (§13.3.1 L1).

    Lives in the domain because it is a security concept, not a web framework
    concept. There is deliberately no default value: a route whose author did
    not think about tenancy must fail the manifest test, not inherit a guess.
    """

    PUBLIC = "public"
    AUTHENTICATED = "authenticated"
    TENANT_SCOPED = "tenant_scoped"


__all__ = [
    "SELECTABLE_LOGICAL_TYPES",
    "LogicalType",
    "PrivacyMode",
    "RouteClass",
    "SourceFormat",
    "UserStatus",
]
