"""Route manifest — layer 1 of the INV-7 enforcement (DESIGN.md §13.3.1).

Every route must be listed here with its tenancy class. A route that is missing
fails ``test_route_manifest.py``; there is deliberately **no default**, so
whoever adds an endpoint has to state what it exposes rather than inherit a
guess.

The cross-tenant sweep (layer 2) is generated from the ``TENANT_SCOPED`` entries
below, which is the property that matters: a new tenant-scoped route is swept
automatically. A list of tests maintained by hand is a list that falls behind.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.enums import RouteClass


@dataclass(frozen=True, slots=True)
class RouteSpec:
    method: str
    path: str
    tenancy: RouteClass
    #: Which seeded resource fills the path parameters during the sweep.
    #: Required for TENANT_SCOPED routes — without it the sweep cannot build a
    #: URL that points at another tenant's data, which is the whole test.
    resource: str | None = None
    #: Body to send for methods that need one, again for the sweep only.
    sample_body: dict[str, object] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.method.upper(), self.path


ROUTES: tuple[RouteSpec, ...] = (
    # --- public ---------------------------------------------------------
    RouteSpec("GET", "/health", RouteClass.PUBLIC),
    RouteSpec("POST", "/auth/register", RouteClass.PUBLIC),
    RouteSpec("POST", "/auth/login", RouteClass.PUBLIC),
    # --- authenticated, not tied to one workspace ------------------------
    RouteSpec("GET", "/auth/me", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/auth/logout", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/auth/logout-all", RouteClass.AUTHENTICATED),
    # Lists only the caller's own workspaces, so it is authenticated rather
    # than tenant-scoped: there is no id in the path to point elsewhere.
    RouteSpec("GET", "/workspaces", RouteClass.AUTHENTICATED),
    # --- tenant-scoped ---------------------------------------------------
    RouteSpec("GET", "/workspaces/{workspace_id}", RouteClass.TENANT_SCOPED, resource="workspace"),
    RouteSpec(
        "GET",
        "/workspaces/{workspace_id}/projects",
        RouteClass.TENANT_SCOPED,
        resource="workspace",
    ),
    RouteSpec(
        "POST",
        "/workspaces/{workspace_id}/projects",
        RouteClass.TENANT_SCOPED,
        resource="workspace",
        sample_body={"name": "swept"},
    ),
    RouteSpec(
        "GET",
        "/workspaces/{workspace_id}/projects/{project_id}",
        RouteClass.TENANT_SCOPED,
        resource="project",
    ),
    RouteSpec(
        "GET",
        "/workspaces/{workspace_id}/dataset-versions/{version_id}",
        RouteClass.TENANT_SCOPED,
        resource="dataset_version",
    ),
)

BY_KEY: dict[tuple[str, str], RouteSpec] = {spec.key: spec for spec in ROUTES}

TENANT_SCOPED: tuple[RouteSpec, ...] = tuple(
    spec for spec in ROUTES if spec.tenancy is RouteClass.TENANT_SCOPED
)


__all__ = ["BY_KEY", "ROUTES", "TENANT_SCOPED", "RouteSpec"]
