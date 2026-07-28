"""Workspace members and roles (FR-A.5).

The cross-tenant behaviour of these routes is already covered by the generated
sweep in ``test_tenant_isolation.py`` — that is the point of generating it.
What is left, and what lives here, is the behaviour *inside* a workspace: who
may change what, and the states the service refuses to enter.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.tokens import COOKIE_NAME
from app.repositories.connection import Database
from app.repositories.tables import audit_event, membership

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "correct-horse-battery"


async def _register(client: AsyncClient, email: str) -> dict[str, Any]:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    body["token"] = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return body


def _as(actor: dict[str, Any]) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={actor['token']}"}


async def _owner_with_member(
    api: AsyncClient, role: str = "editor"
) -> tuple[dict[str, Any], dict[str, Any]]:
    owner = await _register(api, "owner@example.com")
    member = await _register(api, "member@example.com")
    added = await api.post(
        f"/workspaces/{owner['workspace']['id']}/members",
        headers=_as(owner),
        json={"email": member["user"]["email"], "role": role},
    )
    assert added.status_code == 201, added.text
    return owner, member


# ------------------------------------------------------------- adding ----


async def test_owner_can_add_an_existing_account(api: AsyncClient) -> None:
    owner, member = await _owner_with_member(api)

    listed = await api.get(f"/workspaces/{owner['workspace']['id']}/members", headers=_as(owner))
    assert listed.status_code == 200
    by_email = {row["email"]: row for row in listed.json()}
    assert by_email[member["user"]["email"]]["role"] == "editor"
    assert by_email[member["user"]["email"]]["invited_by"] == owner["user"]["id"]


async def test_adding_an_unregistered_address_fails_clearly(api: AsyncClient) -> None:
    """The documented trade-off (see ``NoSuchAccount``).

    A silent no-op would leave the owner staring at an unchanged member list
    with no idea whether they mistyped the address.
    """
    owner = await _register(api, "owner@example.com")
    response = await api.post(
        f"/workspaces/{owner['workspace']['id']}/members",
        headers=_as(owner),
        json={"email": "nobody@example.com", "role": "editor"},
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "no account with that email"


async def test_adding_the_same_person_twice_is_a_conflict(api: AsyncClient) -> None:
    """Not an error to hide: `(user, workspace)` is unique, and two rows would
    make "what may they do?" a question with two answers."""
    owner, member = await _owner_with_member(api)
    again = await api.post(
        f"/workspaces/{owner['workspace']['id']}/members",
        headers=_as(owner),
        json={"email": member["user"]["email"], "role": "viewer"},
    )
    assert again.status_code == 409


@pytest.mark.invariant
async def test_a_non_owner_cannot_add_members(api: AsyncClient) -> None:
    """An editor has full power over *data*, and none over *access* (FR-A.5)."""
    owner, member = await _owner_with_member(api, role="editor")
    outsider = await _register(api, "outsider@example.com")

    attempt = await api.post(
        f"/workspaces/{owner['workspace']['id']}/members",
        headers=_as(member),
        json={"email": outsider["user"]["email"], "role": "viewer"},
    )
    assert attempt.status_code == 404


# -------------------------------------------------------------- roles ----


async def test_owner_can_change_a_role(api: AsyncClient, database: Database) -> None:
    owner, member = await _owner_with_member(api, role="viewer")

    changed = await api.patch(
        f"/workspaces/{owner['workspace']['id']}/members/{member['user']['id']}",
        headers=_as(owner),
        json={"role": "editor"},
    )
    assert changed.status_code == 200
    assert changed.json()["role"] == "editor"

    async with database.connect() as connection:
        stored = await connection.scalar(
            sa.select(membership.c.role).where(
                membership.c.user_id == uuid.UUID(member["user"]["id"]),
                membership.c.workspace_id == uuid.UUID(owner["workspace"]["id"]),
            )
        )
    assert stored == "editor"


@pytest.mark.invariant
async def test_a_role_change_takes_effect_immediately(api: AsyncClient) -> None:
    """A Principal is a snapshot per request, so a demotion must not need a re-login.

    If it did, revoking somebody's access would leave them writing for up to
    thirty days — the session lifetime.
    """
    owner, member = await _owner_with_member(api, role="editor")
    workspace_id = owner["workspace"]["id"]

    allowed = await api.post(
        f"/workspaces/{workspace_id}/projects",
        headers=_as(member),
        json={"name": "while still an editor"},
    )
    assert allowed.status_code == 201

    await api.patch(
        f"/workspaces/{workspace_id}/members/{member['user']['id']}",
        headers=_as(owner),
        json={"role": "viewer"},
    )

    refused = await api.post(
        f"/workspaces/{workspace_id}/projects",
        headers=_as(member),
        json={"name": "after demotion"},
    )
    assert refused.status_code == 404


@pytest.mark.invariant
async def test_the_last_owner_cannot_be_demoted(api: AsyncClient) -> None:
    """A workspace with no owner is a workspace nobody can administer.

    There is no endpoint to repair that state, so the operation that would
    create it is refused rather than regretted.
    """
    owner = await _register(api, "owner@example.com")
    response = await api.patch(
        f"/workspaces/{owner['workspace']['id']}/members/{owner['user']['id']}",
        headers=_as(owner),
        json={"role": "viewer"},
    )
    assert response.status_code == 409
    assert "owner" in response.json()["detail"]


@pytest.mark.invariant
async def test_the_last_owner_cannot_remove_themselves(api: AsyncClient) -> None:
    """Self-service lockout is still lockout."""
    owner = await _register(api, "owner@example.com")
    response = await api.delete(
        f"/workspaces/{owner['workspace']['id']}/members/{owner['user']['id']}",
        headers=_as(owner),
    )
    assert response.status_code == 409


async def test_an_owner_can_step_down_once_another_owner_exists(api: AsyncClient) -> None:
    """The protection is about the *last* owner, not about owners in general."""
    first, second = await _owner_with_member(api, role="owner")

    stepped_down = await api.patch(
        f"/workspaces/{first['workspace']['id']}/members/{first['user']['id']}",
        headers=_as(first),
        json={"role": "editor"},
    )
    assert stepped_down.status_code == 200

    still_owner = await api.get(f"/workspaces/{first['workspace']['id']}", headers=_as(second))
    assert still_owner.json()["role"] == "owner"


# ------------------------------------------------------------ removal ----


async def test_removing_a_member_revokes_access_but_keeps_their_work(
    api: AsyncClient, database: Database
) -> None:
    """Their projects belong to the workspace, not to them.

    Deleting somebody's work because their access ended would be a surprising
    thing for a tool to decide on its own.
    """
    owner, member = await _owner_with_member(api, role="editor")
    workspace_id = owner["workspace"]["id"]

    created = await api.post(
        f"/workspaces/{workspace_id}/projects",
        headers=_as(member),
        json={"name": "their work"},
    )
    assert created.status_code == 201

    removed = await api.delete(
        f"/workspaces/{workspace_id}/members/{member['user']['id']}", headers=_as(owner)
    )
    assert removed.status_code == 204

    assert (await api.get(f"/workspaces/{workspace_id}", headers=_as(member))).status_code == 404

    projects = await api.get(f"/workspaces/{workspace_id}/projects", headers=_as(owner))
    assert {p["name"] for p in projects.json()} >= {"their work"}


# -------------------------------------------------------------- audit ----


@pytest.mark.invariant
async def test_membership_changes_are_audited(api: AsyncClient, database: Database) -> None:
    """§13.7 lists member and role changes explicitly."""
    owner, member = await _owner_with_member(api, role="viewer")
    workspace_id = owner["workspace"]["id"]

    await api.patch(
        f"/workspaces/{workspace_id}/members/{member['user']['id']}",
        headers=_as(owner),
        json={"role": "editor"},
    )
    await api.delete(
        f"/workspaces/{workspace_id}/members/{member['user']['id']}", headers=_as(owner)
    )

    async with database.connect() as connection:
        actions = (await connection.execute(sa.select(audit_event.c.action))).scalars().all()

    assert "membership.granted" in actions
    assert "membership.role_changed" in actions
    assert "membership.revoked" in actions
