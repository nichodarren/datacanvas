"""Password reset (FR-A.6).

Delivery is not wired — no provider was ever decided (see ``app.auth.email``) —
so these tests read the token out of the database, the way the development
sender reads it out of the log. What is under test is the part that would be a
security incident if it were wrong: who can obtain a token, how long it lives,
how many times it works, and what it invalidates when it succeeds.
"""

from __future__ import annotations

from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient

from app.auth.password_reset import MAX_RESET_REQUESTS
from app.auth.tokens import COOKIE_NAME, hash_token
from app.repositories.connection import Database
from app.repositories.tables import audit_event, password_reset_token, user_session

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-completely-different-one"


async def _register(client: AsyncClient, email: str = "rina@example.com") -> dict[str, Any]:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    body["token"] = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return body


class _CapturingSender:
    """Keeps the last message instead of sending it."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_password_reset(self, message: Any) -> None:
        self.sent.append((message.to_email, message.token))


@pytest.fixture
def captured(api_application: FastAPI) -> _CapturingSender:
    """Swap the app's sender so the test can read the token it would have mailed.

    Set on the application before its lifespan runs, so it replaces the default
    rather than racing it.
    """
    sender = _CapturingSender()
    api_application.state.email_sender = sender
    return sender


# ------------------------------------------------------------ requesting ----


@pytest.mark.invariant
async def test_requesting_a_reset_never_reveals_whether_an_account_exists(
    api: AsyncClient,
) -> None:
    """Any difference here turns the endpoint into an account-enumeration oracle."""
    await _register(api, "rina@example.com")

    known = await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    unknown = await api.post("/auth/password-reset", json={"email": "nobody@example.com"})

    assert known.status_code == unknown.status_code == 202
    assert known.content == unknown.content


async def test_a_token_is_issued_for_a_real_account(
    api: AsyncClient, database: Database, captured: _CapturingSender
) -> None:
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})

    assert len(captured.sent) == 1
    to_email, raw = captured.sent[0]
    assert to_email == "rina@example.com"

    async with database.connect() as connection:
        stored = (
            (await connection.execute(sa.select(password_reset_token.c.token_hash))).scalars().all()
        )
    # Only the hash is stored, exactly as for session tokens (§13.2).
    assert stored == [hash_token(raw)]
    assert raw not in stored


async def test_no_token_is_issued_for_an_unknown_address(
    api: AsyncClient, database: Database, captured: _CapturingSender
) -> None:
    await api.post("/auth/password-reset", json={"email": "nobody@example.com"})

    assert captured.sent == []
    async with database.connect() as connection:
        count = await connection.scalar(
            sa.select(sa.func.count()).select_from(password_reset_token)
        )
    assert count == 0


@pytest.mark.invariant
async def test_a_new_request_burns_the_previous_token(
    api: AsyncClient, captured: _CapturingSender
) -> None:
    """Otherwise every reset mail ever sent stays a live key to the account."""
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})

    first, second = captured.sent[0][1], captured.sent[1][1]

    stale = await api.post(
        "/auth/password-reset/confirm", json={"token": first, "password": NEW_PASSWORD}
    )
    assert stale.status_code == 400

    fresh = await api.post(
        "/auth/password-reset/confirm", json={"token": second, "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 204


async def test_requests_are_capped_per_account(
    api: AsyncClient, captured: _CapturingSender
) -> None:
    """So the endpoint cannot be used to flood somebody's inbox."""
    await _register(api)
    for _ in range(MAX_RESET_REQUESTS + 3):
        response = await api.post("/auth/password-reset", json={"email": "rina@example.com"})
        # Still 202 every time — the cap must not be observable either.
        assert response.status_code == 202

    assert len(captured.sent) == MAX_RESET_REQUESTS


# ------------------------------------------------------------ confirming ----


async def test_a_valid_token_changes_the_password(
    api: AsyncClient, captured: _CapturingSender
) -> None:
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    raw = captured.sent[0][1]

    confirmed = await api.post(
        "/auth/password-reset/confirm", json={"token": raw, "password": NEW_PASSWORD}
    )
    assert confirmed.status_code == 204

    old = await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    assert old.status_code == 401

    new = await api.post(
        "/auth/login", json={"email": "rina@example.com", "password": NEW_PASSWORD}
    )
    assert new.status_code == 200


@pytest.mark.invariant
async def test_a_token_works_exactly_once(api: AsyncClient, captured: _CapturingSender) -> None:
    """A link sitting in a mailbox must stop being a key to the account."""
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    raw = captured.sent[0][1]

    first = await api.post(
        "/auth/password-reset/confirm", json={"token": raw, "password": NEW_PASSWORD}
    )
    assert first.status_code == 204

    second = await api.post(
        "/auth/password-reset/confirm",
        json={"token": raw, "password": "yet-another-password"},
    )
    assert second.status_code == 400


@pytest.mark.invariant
async def test_a_completed_reset_revokes_every_session(
    api: AsyncClient, database: Database, captured: _CapturingSender
) -> None:
    """A reset is what somebody does when they think they were breached.

    Leaving existing sessions alive would leave the intruder logged in, which
    defeats the entire act.
    """
    account = await _register(api)
    other = await api.post("/auth/login", json={"email": "rina@example.com", "password": PASSWORD})
    other_token = other.cookies[COOKIE_NAME]
    api.cookies.clear()

    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    raw = captured.sent[0][1]
    await api.post("/auth/password-reset/confirm", json={"token": raw, "password": NEW_PASSWORD})

    for token in (account["token"], other_token):
        response = await api.get("/auth/me", headers={"Cookie": f"{COOKIE_NAME}={token}"})
        assert response.status_code == 401

    async with database.connect() as connection:
        live = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(user_session)
            .where(user_session.c.revoked_at.is_(None))
        )
    assert live == 0


@pytest.mark.parametrize("token", ["", "not-a-real-token", "x" * 100])
async def test_a_bogus_token_is_refused(api: AsyncClient, token: str) -> None:
    response = await api.post(
        "/auth/password-reset/confirm", json={"token": token, "password": NEW_PASSWORD}
    )
    assert response.status_code in {400, 422}


async def test_a_weak_new_password_is_refused(api: AsyncClient, captured: _CapturingSender) -> None:
    """The reset path must not become a way around the password policy."""
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    raw = captured.sent[0][1]

    response = await api.post(
        "/auth/password-reset/confirm", json={"token": raw, "password": "short"}
    )
    assert response.status_code == 422


@pytest.mark.invariant
async def test_the_reset_flow_is_audited_without_leaking_the_token(
    api: AsyncClient, database: Database, captured: _CapturingSender
) -> None:
    """§13.7.1: the audit log can never be deleted, so it holds no secrets."""
    await _register(api)
    await api.post("/auth/password-reset", json={"email": "rina@example.com"})
    raw = captured.sent[0][1]
    await api.post("/auth/password-reset/confirm", json={"token": raw, "password": NEW_PASSWORD})

    async with database.connect() as connection:
        rows = (
            await connection.execute(
                sa.select(audit_event.c.action, sa.cast(audit_event.c.metadata, sa.Text))
            )
        ).all()

    actions = {row[0] for row in rows}
    assert "auth.password_reset_requested" in actions
    assert "auth.password_reset_completed" in actions
    assert all(raw not in (row[1] or "") for row in rows)
    assert all(NEW_PASSWORD not in (row[1] or "") for row in rows)
