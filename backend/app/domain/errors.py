"""Domain-level errors.

These carry no HTTP status and no framework types on purpose: ``domain/`` must
stay usable without FastAPI in the room (DESIGN.md §10.6). Translation to
responses happens in ``api/``.
"""

from __future__ import annotations


class DomainError(Exception):
    """Base class for every error raised by the domain layer."""


class InvariantViolation(DomainError):
    """An invariant from DESIGN.md §9.3 would be broken by this operation.

    Raised where the domain can see the violation itself. The invariants that
    can be enforced by the database (INV-2, INV-3) are enforced there as well —
    two layers, because either one alone is a promise rather than a guarantee.
    """


class AuthorizationError(DomainError):
    """The principal may not perform this action on this resource.

    Deliberately does not distinguish "does not exist" from "not yours": that
    distinction is itself a leak (§13.3.1 L2), and the API layer renders both
    as 404.
    """


__all__ = ["AuthorizationError", "DomainError", "InvariantViolation"]
