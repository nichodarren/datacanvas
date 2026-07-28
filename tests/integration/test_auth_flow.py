"""Registration, login, sessions and the audit trail (FR-A.1 to A.4, §13.2).

Runs against the real application over HTTP, so what is verified is the
behaviour a browser would get — cookie flags included.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.service import DEFAULT_PROJECT_NAME, MAX_LOGIN_FAILURES
from app.auth.tokens import COOKIE_NAME, hash_token
from app.repositories.connection import Database
from app.repositories.tables import audit_event, membership, user_session, workspace_policy

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "correct-horse-battery"


async def _register(
    client: AsyncClient, email: str = "rina@example.com"
) -> tuple[dict[str, Any], str]:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()  # identity is stated per request, never inherited
    return response.json(), token


def _as(token: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={token}"}


# ------------------------------------------------------------- register ----


async def test_registration_provisions_everything_needed_to_start(
    api: AsyncClient, database: Database
) -> None:
    """FR-A.3: a user always has a workspace. And a project, so the app is not empty.

    All of it in one transaction: an account with a workspace but no membership
    is a support ticket nobody can resolve from the code.
    """
    body, _ = await _register(api)

    assert body["workspace"]["is_personal"] is True
    assert body["workspace"]["role"] == "owner"
    assert body["project"]["name"] == DEFAULT_PROJECT_NAME

    async with database.connect() as connection:
        roles = (
            (
                await connection.execute(
                    sa.select(membership.c.role).where(
                        membership.c.workspace_id == uuid.UUID(body["workspace"]["id"])
                    )
                )
            )
            .scalars()
            .all()
        )
        privacy = await connection.scalar(
            sa.select(workspace_policy.c.llm_privacy_mode).where(
                workspace_policy.c.workspace_id == uuid.UUID(body["workspace"]["id"])
            )
        )

    assert roles == ["owner"]
    # OQ-4 decided `balanced`, and a workspace must never exist without a policy.
    assert privacy == "balanced"


async def test_email_is_normalized_so_one_person_gets_one_account(api: AsyncClient) -> None:
    await _register(api, "Rina@Example.COM")
    duplicate = await api.post(
        "/auth/register", json={"email": "rina@example.com", "password": PASSWORD}
    )
    assert duplicate.status_code == 409


async def test_short_passwords_are_rejected_before_anything_is_created(
    api: AsyncClient, database: Database
) -> None:
    response = await api.post("/auth/register", json={"email": "x@example.com", "password": "abc"})
    assert response.status_code == 422

    async with database.connect() as connection:
        count = await connection.scalar(sa.text("SELECT count(*) FROM app_user"))
    assert count == 0


async def test_registration_sets_a_hardened_cookie(api: AsyncClient) -> None:
    """§13.2: httpOnly + SameSite=Lax. SameSite is also what covers CSRF here."""
    response = await api.post(
        "/auth/register", json={"email": "rina@example.com", "password": PASSWORD}
    )
    header = response.headers["set-cookie"]
    assert "httponly" in header.lower()
    assert "samesite=lax" in header.lower()


async def test_the_raw_token_is_never_stored(api: AsyncClient, database: Database) -> None:
    """Only the SHA-256 digest reaches the database (§13.2)."""
    _, token = await _register(api)

    async with database.connect() as connection:
        stored = (await connection.execute(sa.select(user_session.c.token_hash))).scalars().all()

    assert stored == [hash_token(token)]
    assert token not in stored


# ---------------------------------------------------------------- login ----


async def test_login_then_me(api: AsyncClient) -> None:
    await _register(api)
    login = await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    assert login.status_code == 200
    token = login.cookies[COOKIE_NAME]
    api.cookies.clear()

    me = await api.get("/auth/me", headers=_as(token))
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "rina@example.com"
    assert len(me.json()["workspaces"]) == 1


@pytest.mark.parametrize(
    ("email", "password"),
    [
        ("rina@example.com", "wrong-password-here"),
        ("nobody@example.com", PASSWORD),
    ],
)
async def test_wrong_password_and_unknown_account_are_indistinguishable(
    api: AsyncClient, email: str, password: str
) -> None:
    """Anything more specific turns the login form into an enumeration oracle."""
    await _register(api)
    response = await api.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid credentials"


async def test_repeated_failures_are_rate_limited(api: AsyncClient) -> None:
    """§13.2. The counter is in Postgres, not Redis (§19.2)."""
    await _register(api)
    for _ in range(MAX_LOGIN_FAILURES):
        failed = await api.post(
            "/auth/login", json={"email": "rina@example.com", "password": "nope-nope-nope"}
        )
        assert failed.status_code == 401

    blocked = await api.post(
        "/auth/login", json={"email": "rina@example.com", "password": PASSWORD}
    )
    assert blocked.status_code == 429


# -------------------------------------------------------------- session ----


async def test_no_cookie_is_unauthenticated(api: AsyncClient) -> None:
    assert (await api.get("/auth/me")).status_code == 401


async def test_a_forged_token_is_rejected(api: AsyncClient) -> None:
    await _register(api)
    assert (await api.get("/auth/me", headers=_as("not-a-real-token"))).status_code == 401


async def test_logout_revokes_only_this_session(api: AsyncClient) -> None:
    await _register(api)
    first = (
        await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    ).cookies[COOKIE_NAME]
    api.cookies.clear()
    second = (
        await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    ).cookies[COOKIE_NAME]
    api.cookies.clear()

    assert (await api.post("/auth/logout", headers=_as(first))).status_code == 204

    assert (await api.get("/auth/me", headers=_as(first))).status_code == 401
    assert (await api.get("/auth/me", headers=_as(second))).status_code == 200


async def test_logout_everywhere_revokes_every_session(api: AsyncClient) -> None:
    """FR-A.2 — the action taken when someone thinks they were breached."""
    _, registration_token = await _register(api)
    other = (
        await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    ).cookies[COOKIE_NAME]
    api.cookies.clear()

    response = await api.post("/auth/logout-all", headers=_as(other))
    assert response.status_code == 200
    assert response.json()["revoked_sessions"] == 2

    for token in (registration_token, other):
        assert (await api.get("/auth/me", headers=_as(token))).status_code == 401


async def test_revocation_is_recorded_rather_than_deleted(
    api: AsyncClient, database: Database
) -> None:
    """§9.2: a row that vanished cannot explain anything during an investigation."""
    _, token = await _register(api)
    await api.post("/auth/logout", headers=_as(token))

    async with database.connect() as connection:
        rows = (await connection.execute(sa.select(user_session.c.revoked_at))).scalars().all()

    assert len(rows) == 1
    assert rows[0] is not None


# ---------------------------------------------------------------- audit ----


async def test_the_audit_trail_records_what_happened(api: AsyncClient, database: Database) -> None:
    await _register(api)
    await api.post("/auth/login", json={"email": "rina@example.com", "password": "wrong-one-here"})
    await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    api.cookies.clear()

    async with database.connect() as connection:
        actions = (
            (await connection.execute(sa.select(audit_event.c.action).order_by(audit_event.c.at)))
            .scalars()
            .all()
        )

    assert "user.registered" in actions
    assert "workspace.created" in actions
    assert "project.created" in actions
    assert "auth.login_failed" in actions
    assert "auth.login_succeeded" in actions


@pytest.mark.invariant
async def test_the_audit_trail_never_holds_the_password(
    api: AsyncClient, database: Database
) -> None:
    """§13.7.1: the log can never be deleted, so it must never hold secrets."""
    await _register(api)
    await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})

    async with database.connect() as connection:
        blobs = (
            (await connection.execute(sa.select(sa.cast(audit_event.c.metadata, sa.Text))))
            .scalars()
            .all()
        )

    assert all(PASSWORD not in blob for blob in blobs)
