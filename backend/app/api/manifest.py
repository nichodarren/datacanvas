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
    #: Multipart payload for upload routes. Present because the sweep has to
    #: send what the route actually accepts: a JSON body to a multipart endpoint
    #: is rejected at validation, which answers 422 and never reaches the
    #: authorization check — a sweep that proves nothing while looking green.
    sample_files: dict[str, tuple[str, bytes, str]] | None = None
    #: Form fields accompanying ``sample_files``.
    sample_form: dict[str, str] | None = None

    @property
    def key(self) -> tuple[str, str]:
        return self.method.upper(), self.path


ROUTES: tuple[RouteSpec, ...] = (
    # --- public ---------------------------------------------------------
    RouteSpec("GET", "/health", RouteClass.PUBLIC),
    RouteSpec("POST", "/auth/register", RouteClass.PUBLIC),
    RouteSpec("POST", "/auth/login", RouteClass.PUBLIC),
    # Public by necessity: whoever needs these has lost their password.
    RouteSpec("POST", "/auth/password-reset", RouteClass.PUBLIC),
    RouteSpec("POST", "/auth/password-reset/confirm", RouteClass.PUBLIC),
    # --- authenticated, and pointing at nothing but the caller -----------
    #
    # The line between this class and TENANT_SCOPED moved with D-039, and it is
    # worth stating where it sits now. It was *does the path contain a
    # workspace id*. It is now **does the path contain an id belonging to
    # somebody**. Routes below take no id at all, so the session decides which
    # account they act on and there is nowhere for a caller to point.
    RouteSpec("GET", "/auth/me", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/auth/logout", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/auth/logout-all", RouteClass.AUTHENTICATED),
    # Account self-service. All three read or write only the caller's own rows:
    # the listing takes no id at all, and the revoke scopes its UPDATE by
    # user_id so a guessed session id matches nothing.
    RouteSpec("GET", "/auth/sessions", RouteClass.AUTHENTICATED),
    RouteSpec("DELETE", "/auth/sessions/{session_id}", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/auth/password", RouteClass.AUTHENTICATED),
    # D-025: reads a prefix, answers, keeps nothing. There is no stored resource
    # for it to belong to, so there is nothing to scope. The classification is
    # the decision — if this route ever starts retaining an upload, it becomes
    # tenant-scoped on the same day.
    RouteSpec("POST", "/uploads/preview", RouteClass.AUTHENTICATED),
    # A catalogue of what the server ships (FR-B.5). Identical for everyone and
    # naming nobody's data, so there is nothing to scope it to.
    RouteSpec("GET", "/samples", RouteClass.AUTHENTICATED),
    # The caller's own datasets. This was tenant-scoped as
    # `/workspaces/{id}/projects/{id}/datasets`; both ids are gone, and with
    # them any way to ask for somebody else's list.
    RouteSpec("GET", "/datasets", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/datasets", RouteClass.AUTHENTICATED),
    RouteSpec("POST", "/datasets/samples", RouteClass.AUTHENTICATED),
    # --- tenant-scoped ---------------------------------------------------
    #
    # Every route here takes the id of a row somebody owns, so every one of them
    # can be *pointed at another account* — which is exactly what the sweep
    # does. Six routes rather than the fourteen before D-039, and that is a
    # smaller attack surface rather than a smaller test: nothing that could be
    # aimed elsewhere stopped being swept.
    #
    # Five after D-043, for the same reason: `POST /datasets/{id}/versions` was
    # the sixth, and it addressed a thing that no longer exists. Every id that
    # can still be aimed somewhere is still aimed there below.
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/schema",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/profile",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/columns/{column}/profile",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    # One copilot turn (§12.3). Tenant-scoped for the ordinary reason — it
    # opens a dataset — and the sweep generated from this list is what proves
    # a turn cannot be run against somebody else's data.
    RouteSpec(
        "POST",
        "/datasets/{dataset_id}/ask",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
        # Without this the sweep posts nothing, Pydantic answers 422 before the
        # handler runs, and the route looks like it leaks a distinguishable
        # status to a non-member. It does not — but a guard that cannot tell
        # the difference is a guard nobody will trust the next time it fires.
        sample_body={"question": "what is in this data?"},
    ),
    # One computation's result, for the canvas to draw. Tenant-scoped twice
    # over: the dataset is opened through the gate, and the computation is then
    # looked up *within* that dataset rather than filtered after the fact.
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/computations/{computation_id}",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    # The conversation log. Tenant-scoped like everything else that reads a
    # dataset: a history is a list of questions somebody asked about their own
    # data, and it is opened through the same gate rather than beside it.
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/history",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    RouteSpec(
        "GET",
        "/datasets/{dataset_id}/rows",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    RouteSpec(
        "POST",
        "/datasets/{dataset_id}/schema",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
        sample_body={"columns": [{"name": "seeded", "logical_type": "categorical"}]},
    ),
    RouteSpec(
        "DELETE",
        "/datasets/{dataset_id}",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
    # Forgetting one question. Tenant-scoped like every other read or write of
    # a dataset's conversation, and NFR-PRIV.3 is why it exists at all: the
    # sentence a person typed has to be removable, which is also why
    # `conversation_turn` carries no immutability trigger.
    RouteSpec(
        "DELETE",
        "/datasets/{dataset_id}/history/{turn_id}",
        RouteClass.TENANT_SCOPED,
        resource="dataset",
    ),
)

BY_KEY: dict[tuple[str, str], RouteSpec] = {spec.key: spec for spec in ROUTES}

TENANT_SCOPED: tuple[RouteSpec, ...] = tuple(
    spec for spec in ROUTES if spec.tenancy is RouteClass.TENANT_SCOPED
)


__all__ = ["BY_KEY", "ROUTES", "TENANT_SCOPED", "RouteSpec"]
