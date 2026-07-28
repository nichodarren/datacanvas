"""Layer 1 of INV-7: every route declares its tenancy class (§13.3.1).

There is no default. A route whose author did not think about tenancy fails
here rather than inheriting a guess — and a guess that happens to be wrong is
indistinguishable from one that happens to be right until somebody's data
leaks.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

import pytest
from fastapi.routing import APIRoute

from app.api.app import create_app
from app.api.manifest import BY_KEY, ROUTES, TENANT_SCOPED
from app.domain.enums import RouteClass

#: FastAPI adds these itself.
BUILTIN_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def _walk(routes: Iterable[object], prefix: str = "") -> Iterator[tuple[str, APIRoute]]:
    """Yield ``(full_path, route)`` for every APIRoute, however deeply nested.

    FastAPI 0.140 keeps an included router as a wrapper object holding
    ``original_router`` rather than flattening its routes into ``app.routes``,
    so a flat loop over ``app.routes`` finds nothing.

    It found nothing *quietly*, too: "every route is classified" passed against
    an empty set. Only the opposite assertion — the manifest lists routes the
    app does not serve — caught it. That is the argument for asserting both
    directions of a set comparison, and for the non-empty guard below.
    """
    for route in routes:
        if isinstance(route, APIRoute):
            yield prefix + route.path, route
            continue

        included = getattr(route, "original_router", None)
        if included is not None:
            context = getattr(route, "include_context", None)
            yield from _walk(included.routes, prefix + getattr(context, "prefix", ""))
            continue

        nested = getattr(route, "routes", None)
        if nested:
            yield from _walk(nested, prefix)


def _application_routes() -> set[tuple[str, str]]:
    """Every route the app really serves.

    Walks the router tree rather than reading the OpenAPI schema: a route
    declared with ``include_in_schema=False`` is absent from the schema, and a
    hidden route is precisely the kind that should not escape this check.
    """
    application = create_app()
    found: set[tuple[str, str]] = set()
    for path, route in _walk(application.routes):
        if path in BUILTIN_PATHS:
            continue
        for method in route.methods or ():
            if method in {"HEAD", "OPTIONS"}:
                continue
            found.add((method, path))
    assert found, "no routes discovered — the router layout changed, and this test went blind"
    return found


@pytest.mark.invariant
def test_every_route_is_classified() -> None:
    """The test that fails when somebody adds an endpoint and forgets."""
    undeclared = _application_routes() - set(BY_KEY)
    assert not undeclared, (
        f"routes missing from app.api.manifest: {sorted(undeclared)}. "
        f"Declare each one as public, authenticated or tenant_scoped — "
        f"DESIGN.md §13.3.1 L1 leaves no default on purpose."
    )


@pytest.mark.invariant
def test_manifest_has_no_phantom_routes() -> None:
    """A manifest entry for a route that no longer exists is a sweep that no longer runs."""
    missing = set(BY_KEY) - _application_routes()
    assert not missing, f"manifest lists routes the app does not serve: {sorted(missing)}"


def test_tenant_scoped_routes_declare_a_resource() -> None:
    """Without one, the cross-tenant sweep cannot build a URL pointing elsewhere."""
    incomplete = [spec.key for spec in TENANT_SCOPED if spec.resource is None]
    assert not incomplete, f"tenant-scoped routes without a resource: {incomplete}"


def test_tenant_scoped_routes_take_an_id_in_the_path() -> None:
    """A route with no id in its path cannot point at another tenant.

    If one is classified tenant-scoped anyway, either the classification or the
    path is wrong, and both are worth catching.
    """
    for spec in TENANT_SCOPED:
        assert "{" in spec.path, f"{spec.key} is tenant-scoped but has no path parameter"


def test_public_routes_are_few_and_named() -> None:
    """Public means unauthenticated. The list stays short enough to read in one go.

    Written as an exact set so that widening the unauthenticated surface is a
    deliberate edit to this line, with whatever review that attracts — rather
    than a route that quietly became reachable without a session.
    """
    public = {spec.path for spec in ROUTES if spec.tenancy is RouteClass.PUBLIC}
    assert public == {
        "/health",
        "/auth/register",
        "/auth/login",
        # Public by necessity: whoever needs these has lost their password.
        "/auth/password-reset",
        "/auth/password-reset/confirm",
    }
