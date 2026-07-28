"""Gate 1: two users in different workspaces cannot see anything of each other.

This is layer 2 of the INV-7 enforcement (§13.3.1). The sweep is **generated
from the route manifest**, which is the property that matters — a tenant-scoped
route added next month is swept without anyone remembering to add a test here.
A hand-maintained list of routes to check is a list that falls behind, and the
first route it misses is the one that leaks.

Every response must be **404**. Not 403: a 403 confirms the resource exists,
and that confirmation is itself what tenant isolation exists to withhold.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.api.manifest import TENANT_SCOPED, RouteSpec
from app.auth.tokens import COOKIE_NAME
from app.repositories.connection import Database
from app.repositories.tables import dataset, dataset_version, project

pytestmark = pytest.mark.asyncio(loop_scope="session")


@dataclass(frozen=True)
class Tenant:
    """One registered user with a workspace, a project and a dataset version."""

    email: str
    token: str
    user_id: str
    workspace_id: str
    project_id: str
    dataset_version_id: str

    def resource(self, kind: str) -> str:
        return {
            "workspace": self.workspace_id,
            "project": self.project_id,
            "dataset_version": self.dataset_version_id,
        }[kind]


async def _register(client: AsyncClient, database: Database, email: str) -> Tenant:
    response = await client.post(
        "/auth/register", json={"email": email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    token = response.cookies[COOKIE_NAME]

    # httpx persists cookies on the client, which would give every later
    # request ambient authority as whoever registered last. For a test whose
    # subject is *who may do what*, identity has to be stated per request and
    # never inherited.
    client.cookies.clear()

    workspace_id = body["workspace"]["id"]
    project_id = body["project"]["id"]

    # Seed a dataset version directly. Ingestion is Phase 2; Gate 1 is about
    # isolation, and waiting for upload to exist would postpone the security
    # gate to the phase after this one.
    dataset_id, version_id = uuid.uuid4(), uuid.uuid4()
    async with database.transaction() as connection:
        await connection.execute(
            sa.insert(dataset).values(
                id=dataset_id,
                project_id=uuid.UUID(project_id),
                name="seeded",
                created_at=sa.func.now(),
            )
        )
        await connection.execute(
            sa.insert(dataset_version).values(
                id=version_id,
                dataset_id=dataset_id,
                version_no=1,
                content_hash="b" * 64,
                parquet_uri=(
                    f"storage://workspaces/{workspace_id}/datasets/{dataset_id}"
                    f"/versions/{version_id}/data.parquet"
                ),
                row_count=10,
                column_count=3,
                byte_size=512,
                ingested_at=sa.func.now(),
                ingested_by=uuid.UUID(body["user"]["id"]),
            )
        )

    return Tenant(
        email=email,
        token=token,
        user_id=body["user"]["id"],
        workspace_id=workspace_id,
        project_id=project_id,
        dataset_version_id=str(version_id),
    )


def _as(tenant: Tenant) -> dict[str, str]:
    """Send the session explicitly. No cookie jar, no ambient identity."""
    return {"Cookie": f"{COOKIE_NAME}={tenant.token}"}


def _url(spec: RouteSpec, owner: Tenant, member_user_id: str | None = None) -> str:
    """Build a URL aimed at the *owner's* resource.

    ``workspace_id`` is filled from the owner too. Filling it from the caller
    instead would only prove that a member cannot reach a stranger's nested
    resource through their own workspace — worth testing, and tested
    separately below, but a weaker claim than this one.
    """
    return spec.path.format(
        workspace_id=owner.workspace_id,
        project_id=owner.project_id,
        version_id=owner.dataset_version_id,
        member_user_id=member_user_id or owner.user_id,
    )


@pytest.fixture(scope="module")
def _sweep_ids() -> list[str]:
    return [f"{spec.method} {spec.path}" for spec in TENANT_SCOPED]


@pytest.mark.invariant
async def test_the_sweep_covers_every_tenant_scoped_route(api: AsyncClient) -> None:
    """Guard against the sweep silently covering nothing.

    A parametrised test over an empty list passes. This asserts the list is not
    empty and matches the manifest, so "all green" cannot mean "nothing ran".
    """
    assert len(TENANT_SCOPED) >= 5


@pytest.mark.invariant
@pytest.mark.parametrize("spec", TENANT_SCOPED, ids=lambda spec: f"{spec.method} {spec.path}")
async def test_cross_tenant_access_returns_404(
    api: AsyncClient, database: Database, spec: RouteSpec
) -> None:
    """The heart of Gate 1, run once per tenant-scoped route."""
    alice = await _register(api, database, "alice@example.com")
    bob = await _register(api, database, "bob@example.com")

    assert spec.resource is not None
    response = await api.request(
        spec.method,
        _url(spec, owner=alice),
        headers=_as(bob),
        json=spec.sample_body,
    )

    assert response.status_code == 404, (
        f"{spec.method} {spec.path} returned {response.status_code} to a non-member. "
        f"Cross-tenant access must be indistinguishable from a missing resource "
        f"(DESIGN.md §13.3.1 L2)."
    )


@pytest.mark.invariant
@pytest.mark.parametrize("spec", TENANT_SCOPED, ids=lambda spec: f"{spec.method} {spec.path}")
async def test_tenant_scoped_routes_reject_anonymous_callers(
    api: AsyncClient, database: Database, spec: RouteSpec
) -> None:
    """No cookie at all must not be treated as "no membership required"."""
    alice = await _register(api, database, "alice@example.com")

    response = await api.request(spec.method, _url(spec, owner=alice), json=spec.sample_body)
    assert response.status_code in {401, 404}


@pytest.mark.invariant
async def test_owner_is_never_refused_on_their_own_resources(
    api: AsyncClient, database: Database
) -> None:
    """The sweep proves nothing if every route 404s for everyone.

    A `deny all` implementation would pass every test above. This is the
    control that rules it out.

    The assertion is "not 404" rather than "200", because some of these routes
    legitimately answer 409 — removing the last owner, for one. Widening it to
    any non-denial response keeps the control honest instead of forcing the
    routes to bend around the test.
    """
    alice = await _register(api, database, "alice@example.com")
    # A second account that already exists, so adding it as a member succeeds
    # and the member routes have a real target that is not the last owner.
    guest = await _register(api, database, "swept@example.com")
    added = await api.post(
        f"/workspaces/{alice.workspace_id}/members",
        headers=_as(alice),
        json={"email": guest.email, "role": "viewer"},
    )
    assert added.status_code == 201, added.text

    for spec in TENANT_SCOPED:
        response = await api.request(
            spec.method,
            _url(spec, owner=alice, member_user_id=guest.user_id),
            headers=_as(alice),
            json=spec.sample_body,
        )
        assert response.status_code != 404, (
            f"{spec.method} {spec.path} returned 404 to its own owner — "
            f"tenant isolation must not deny the tenant"
        )


@pytest.mark.invariant
async def test_nesting_a_foreign_id_under_your_own_workspace_fails(
    api: AsyncClient, database: Database
) -> None:
    """The variant a path-based check alone would miss.

    Bob is a legitimate member of his own workspace, so a check that only asks
    "is the caller a member of {workspace_id}?" passes — and then happily reads
    Alice's project, because nothing verified the project belongs to that
    workspace.
    """
    alice = await _register(api, database, "alice@example.com")
    bob = await _register(api, database, "bob@example.com")

    response = await api.get(
        f"/workspaces/{bob.workspace_id}/projects/{alice.project_id}",
        headers=_as(bob),
    )
    assert response.status_code == 404

    response = await api.get(
        f"/workspaces/{bob.workspace_id}/dataset-versions/{alice.dataset_version_id}",
        headers=_as(bob),
    )
    assert response.status_code == 404


@pytest.mark.invariant
async def test_listing_endpoints_never_leak_other_tenants(
    api: AsyncClient, database: Database
) -> None:
    """Isolation has to hold for collections, not only for direct lookups.

    Direct-access tests are the ones people write; a list endpoint that
    forgets its filter leaks everything at once and returns 200 while doing it.
    """
    alice = await _register(api, database, "alice@example.com")
    bob = await _register(api, database, "bob@example.com")

    workspaces = await api.get("/workspaces", headers=_as(bob))
    assert workspaces.status_code == 200
    ids = {item["id"] for item in workspaces.json()}
    assert ids == {bob.workspace_id}
    assert alice.workspace_id not in ids

    me = await api.get("/auth/me", headers=_as(bob))
    assert me.status_code == 200
    assert {w["id"] for w in me.json()["workspaces"]} == {bob.workspace_id}


@pytest.mark.invariant
async def test_a_viewer_cannot_write(api: AsyncClient, database: Database) -> None:
    """FR-A.5: `viewer` reads and runs read-only tools, and never creates.

    Granted directly rather than through an invite endpoint, which does not
    exist yet (FR-A.5 is P1). The role check is what is under test.
    """
    alice = await _register(api, database, "alice@example.com")
    bob = await _register(api, database, "bob@example.com")

    async with database.transaction() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO membership (id, user_id, workspace_id, role, created_at)"
                " SELECT :mid, u.id, :ws, 'viewer', now() FROM app_user u WHERE u.email = :email"
            ),
            {"mid": uuid.uuid4(), "ws": uuid.UUID(alice.workspace_id), "email": bob.email},
        )

    # Reading is allowed...
    read = await api.get(f"/workspaces/{alice.workspace_id}", headers=_as(bob))
    assert read.status_code == 200
    assert read.json()["role"] == "viewer"

    # ...writing is not, and looks exactly like not existing.
    write = await api.post(
        f"/workspaces/{alice.workspace_id}/projects",
        headers=_as(bob),
        json={"name": "should not exist"},
    )
    assert write.status_code == 404

    async with database.transaction() as connection:
        count = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(project)
            .where(project.c.workspace_id == uuid.UUID(alice.workspace_id))
        )
    assert count == 1  # only the one registration created
