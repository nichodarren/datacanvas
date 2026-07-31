"""Listing sessions, ending one, and changing a password (FR-A.1, FR-A.2).

These three routes exist because OWASP's Session Management guidance asks for
them together: a user should be able to *see* their live sessions — address,
client, when each started and was last used — and end any of them remotely,
and a password change should be treated as a security boundary event that
invalidates every other session.

The columns those need have been on ``user_session`` since Phase 1. What was
missing was any way to reach them, which is a shape of gap no layer-local test
can see: every query worked, every route worked, and the product had no answer
to "sign out the laptop I left at the office" except "sign out everywhere".

The assertion this file exists for is
``test_a_session_belonging_to_someone_else_cannot_be_ended``. A session id is a
plain UUID that the owner is *shown*; if the UPDATE were not scoped by user, a
leaked or guessed id would let any authenticated stranger end it.
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.tokens import COOKIE_NAME
from app.domain.audit import AuditAction
from app.repositories.connection import Database
from app.repositories.tables import audit_event, password_reset_token

pytestmark = pytest.mark.asyncio(loop_scope="session")

PASSWORD = "correct-horse-battery"
NEW_PASSWORD = "a-different-long-password"


async def _register(client: AsyncClient, email: str) -> str:
    response = await client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201, response.text
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return token


async def _login(client: AsyncClient, email: str, password: str = PASSWORD) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return token


def _as(token: str) -> dict[str, str]:
    return {"Cookie": f"{COOKIE_NAME}={token}"}


# ------------------------------------------------------------ listing ------


async def test_the_listing_marks_which_session_is_this_one(api: AsyncClient) -> None:
    """Without this flag the list is unusable.

    Every row looks alike, and the user cannot tell which one they would be
    cutting themselves off with.
    """
    first = await _register(api, "sessions@example.com")
    second = await _login(api, "sessions@example.com")

    listed = (await api.get("/auth/sessions", headers=_as(second))).json()

    assert len(listed) == 2
    current = [session for session in listed if session["is_current"]]
    assert len(current) == 1, "exactly one session is the caller's own"
    assert (await api.get("/auth/me", headers=_as(first))).status_code == 200


async def test_the_listing_never_carries_a_token(api: AsyncClient) -> None:
    """§13.2. The hash is indexable and cheap, which is exactly why it must not leak."""
    token = await _register(api, "notoken@example.com")

    body = (await api.get("/auth/sessions", headers=_as(token))).text

    assert "token" not in body.lower()


async def test_a_revoked_session_leaves_the_listing(api: AsyncClient) -> None:
    first = await _register(api, "gone@example.com")
    second = await _login(api, "gone@example.com")

    await api.post("/auth/logout", headers=_as(first))

    listed = (await api.get("/auth/sessions", headers=_as(second))).json()
    assert len(listed) == 1
    assert listed[0]["is_current"] is True


# ------------------------------------------------------------ revoking -----


async def test_ending_one_session_leaves_the_others_alone(api: AsyncClient) -> None:
    """The whole point of the feature.

    A laptop left signed in at the office should cost you that laptop, not
    every device you own — which was the only option before this existed.
    """
    remote = await _register(api, "one@example.com")
    here = await _login(api, "one@example.com")

    listed = (await api.get("/auth/sessions", headers=_as(here))).json()
    target = next(session for session in listed if not session["is_current"])

    response = await api.delete(f"/auth/sessions/{target['id']}", headers=_as(here))
    assert response.status_code == 204

    assert (await api.get("/auth/me", headers=_as(remote))).status_code == 401
    assert (await api.get("/auth/me", headers=_as(here))).status_code == 200


async def test_a_session_belonging_to_someone_else_cannot_be_ended(api: AsyncClient) -> None:
    """The assertion this file exists for (§13.3.1 L2).

    Alice is shown her own session ids. If the UPDATE were not scoped by
    user_id, handing one to Bob would end it. 404 rather than 403, so "not
    yours" and "not there" stay indistinguishable.
    """
    alice = await _register(api, "alice-sessions@example.com")
    bob = await _register(api, "bob-sessions@example.com")

    hers = (await api.get("/auth/sessions", headers=_as(alice))).json()[0]

    response = await api.delete(f"/auth/sessions/{hers['id']}", headers=_as(bob))

    assert response.status_code == 404
    assert (await api.get("/auth/me", headers=_as(alice))).status_code == 200, (
        "Alice must still be signed in"
    )


async def test_ending_an_unknown_session_is_a_404_not_a_500(api: AsyncClient) -> None:
    token = await _register(api, "unknown@example.com")
    missing = "00000000-0000-4000-8000-000000000000"

    assert (await api.delete(f"/auth/sessions/{missing}", headers=_as(token))).status_code == 404


async def test_ending_a_session_is_recorded(api: AsyncClient, database: Database) -> None:
    """§13.7. Who revoked what is the part an investigation needs."""
    await _register(api, "audited@example.com")
    here = await _login(api, "audited@example.com")
    listed = (await api.get("/auth/sessions", headers=_as(here))).json()
    target = next(session for session in listed if not session["is_current"])

    await api.delete(f"/auth/sessions/{target['id']}", headers=_as(here))

    async with database.connect() as connection:
        actions = (
            (
                await connection.execute(
                    sa.select(audit_event.c.action).where(
                        audit_event.c.action == AuditAction.SESSION_REVOKED
                    )
                )
            )
            .scalars()
            .all()
        )
    assert len(actions) == 1


# ----------------------------------------------------- changing password ---


async def test_changing_the_password_ends_every_other_session(api: AsyncClient) -> None:
    """OWASP treats this as a security boundary event.

    The usual reason to change a password is that somebody else may know the
    old one. Leaving their session alive defeats the entire act.
    """
    elsewhere = await _register(api, "rotate@example.com")
    here = await _login(api, "rotate@example.com")

    response = await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 200, response.text
    assert response.json()["revoked_sessions"] == 1
    assert (await api.get("/auth/me", headers=_as(elsewhere))).status_code == 401


async def test_the_session_that_changed_it_stays_signed_in(api: AsyncClient) -> None:
    """Signing someone out of the tab they are working in reads as a failure."""
    here = await _register(api, "stay@example.com")

    await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    assert (await api.get("/auth/me", headers=_as(here))).status_code == 200


async def test_the_new_password_is_the_one_that_works(api: AsyncClient) -> None:
    here = await _register(api, "works@example.com")
    await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    stale = await api.post("/auth/login", json={"email": "works@example.com", "password": PASSWORD})
    assert stale.status_code == 401
    api.cookies.clear()

    fresh = await api.post(
        "/auth/login", json={"email": "works@example.com", "password": NEW_PASSWORD}
    )
    assert fresh.status_code == 200


async def test_the_wrong_current_password_changes_nothing(api: AsyncClient) -> None:
    """Already being authenticated is not enough.

    Requiring the current password is what stops a borrowed unlocked laptop
    from becoming a permanent account takeover.
    """
    elsewhere = await _register(api, "guard@example.com")
    here = await _login(api, "guard@example.com")

    response = await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
    )

    assert response.status_code == 401
    assert (await api.get("/auth/me", headers=_as(elsewhere))).status_code == 200, (
        "a rejected change must not revoke anything"
    )
    assert (
        await api.post("/auth/login", json={"email": "guard@example.com", "password": PASSWORD})
    ).status_code == 200, "the old password must still be the real one"


async def test_a_short_new_password_is_refused(api: AsyncClient) -> None:
    here = await _register(api, "short@example.com")
    response = await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 422


async def test_changing_the_password_kills_an_outstanding_reset_link(
    api: AsyncClient, database: Database
) -> None:
    """The hole this closes is small and real.

    An attacker requests a reset, the victim notices something is wrong and
    changes their password, and the emailed token still works — so the one
    defensive move available to the user does not shut the door they were
    trying to close.
    """
    here = await _register(api, "reset-race@example.com")
    assert (
        await api.post("/auth/password-reset", json={"email": "reset-race@example.com"})
    ).status_code == 202

    async with database.connect() as connection:
        before = (
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(password_reset_token)
                .where(password_reset_token.c.used_at.is_(None))
            )
        ) or 0
    assert before == 1, "the reset request must have produced a live token"

    await api.post(
        "/auth/password",
        headers=_as(here),
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )

    async with database.connect() as connection:
        still_live = (
            await connection.scalar(
                sa.select(sa.func.count())
                .select_from(password_reset_token)
                .where(password_reset_token.c.used_at.is_(None))
            )
        ) or 0
    assert still_live == 0, "the outstanding reset link must not outlive the password"


async def test_an_anonymous_caller_reaches_none_of_this(api: AsyncClient) -> None:
    assert (await api.get("/auth/sessions")).status_code == 401
    assert (
        await api.post(
            "/auth/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
    ).status_code == 401
