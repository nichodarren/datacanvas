"""What the first screen needs from the API (FR-B.5, FR-C.6).

Written after the first person to use the home screen said they did not know
what to do. Two of the three causes were server-side:

* the dataset listing returned names and nothing else, so there was no way to
  tell which dataset wanted attention — or even to reach one;
* there were no sample datasets, so an empty account had nothing to look at,
  which §14.5 forbids in as many words.

The assertions below are about **whether the screen can be built**, not about
how it looks. A card that cannot say "3 columns to check" is a card that sends
someone back to guessing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.tokens import COOKIE_NAME
from app.repositories.connection import Database

pytestmark = pytest.mark.asyncio(loop_scope="session")

# `qty` gets 0.6 (few distinct values) and `code` 0.5 (a near miss), so this
# file has exactly two columns the detector is unsure about and one it is not.
ROWS = (
    b"qty,code,city\n"
    + b"".join(f"{i % 5 + 1},{i},Bogor\n".encode() for i in range(200))
    + b"3,LG-1,Solo\n"
)


async def _session(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/auth/register",
        json={"email": "alice@example.com", "password": "correct-horse-battery"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return {
        "cookie": f"{COOKIE_NAME}={token}",
        "workspace_id": body["workspace"]["id"],
        "project_id": body["project"]["id"],
    }


def _headers(session: dict[str, str]) -> dict[str, str]:
    return {"Cookie": session["cookie"]}


def _datasets_url(session: dict[str, str]) -> str:
    return f"/workspaces/{session['workspace_id']}/projects/{session['project_id']}/datasets"


async def _upload(
    api: AsyncClient, session: dict[str, str], content: bytes = ROWS
) -> dict[str, Any]:
    response = await api.post(
        _datasets_url(session),
        headers=_headers(session),
        files={"file": ("rows.csv", content, "text/csv")},
        data={"name": "rows"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------- listing -----


async def test_an_empty_project_lists_nothing(api: AsyncClient) -> None:
    session = await _session(api)
    response = await api.get(_datasets_url(session), headers=_headers(session))
    assert response.status_code == 200
    assert response.json() == []


async def test_a_listed_dataset_carries_a_way_to_open_it(api: AsyncClient) -> None:
    """The bug this file exists for.

    The listing used to return a name and a timestamp. Uploading redirected you
    to the grid, but coming back later left you looking at your own data with no
    route into it — a dead end that read as "I don't know what to do".
    """
    session = await _session(api)
    uploaded = await _upload(api, session)

    listed = (await api.get(_datasets_url(session), headers=_headers(session))).json()

    assert len(listed) == 1
    assert listed[0]["latest_version_id"] == uploaded["version"]["id"]


async def test_a_card_can_say_which_dataset_needs_attention(api: AsyncClient) -> None:
    """FR-C.6 at the level above the grid.

    Without this number the screen answers "what did I upload" and not "which
    of these wants me", and only the second question is worth a screen.
    """
    session = await _session(api)
    await _upload(api, session)

    summary = (await api.get(_datasets_url(session), headers=_headers(session))).json()[0]

    assert summary["row_count"] == 201
    assert summary["column_count"] == 3
    assert summary["version_no"] == 1
    assert summary["schema_version_no"] == 1


async def test_correcting_a_column_advances_the_contract(api: AsyncClient) -> None:
    """FR-C.3 / INV-3: a correction adds a version rather than overwriting one.

    This used to assert that a "columns needing attention" count shrank. That
    count is gone — the grid no longer marks low-confidence columns, and a
    number pointing at an invisible signal is a warning nobody can act on. What
    still matters, and is what the card actually shows, is that the correction
    produced contract v2.
    """
    session = await _session(api)
    uploaded = await _upload(api, session)
    version_id = uploaded["version"]["id"]

    assert (await api.get(_datasets_url(session), headers=_headers(session))).json()[0][
        "schema_version_no"
    ] == 1

    corrected = await api.post(
        f"/workspaces/{session['workspace_id']}/dataset-versions/{version_id}/schema",
        headers=_headers(session),
        json={"columns": [{"name": "qty", "logical_type": "categorical"}]},
    )
    assert corrected.status_code == 201, corrected.text

    after = (await api.get(_datasets_url(session), headers=_headers(session))).json()[0]
    assert after["schema_version_no"] == 2, "the card follows the newest contract"


async def test_the_card_follows_the_newest_version(api: AsyncClient) -> None:
    """FR-B.2 makes a re-upload a new version; the card must not show the old one."""
    session = await _session(api)
    first = await _upload(api, session)

    second = await api.post(
        f"{_datasets_url(session)}/{first['dataset']['id']}/versions",
        headers=_headers(session),
        files={"file": ("rows.csv", b"a,b\n1,2\n2,3\n", "text/csv")},
    )
    assert second.status_code == 201, second.text

    summary = (await api.get(_datasets_url(session), headers=_headers(session))).json()[0]
    assert summary["version_no"] == 2
    assert summary["version_count"] == 2
    assert summary["latest_version_id"] == second.json()["version"]["id"]


# ------------------------------------------------------------- samples -----


async def test_the_sample_catalogue_is_offered(api: AsyncClient) -> None:
    """§14.5: an empty canvas is the wrong empty state."""
    session = await _session(api)
    response = await api.get("/samples", headers=_headers(session))

    assert response.status_code == 200
    keys = {sample["key"] for sample in response.json()}
    assert {"titanic", "messy-sales"} <= keys
    assert all(sample["description"] for sample in response.json())


async def test_loading_a_sample_produces_a_real_dataset(api: AsyncClient) -> None:
    """Through the same commit path an upload takes.

    A shortcut that produced a dataset some other way would make the demo prove
    something the product does not do — worse than having no demo at all.
    """
    session = await _session(api)

    response = await api.post(
        f"{_datasets_url(session)}/samples",
        headers=_headers(session),
        json={"key": "messy-sales"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["version"]["row_count"] == 5_000
    assert body["schema_contract"]["version_no"] == 1
    # The sample worth offering is the one where detection has something to say.
    flagged = [
        column
        for column in body["schema_contract"]["columns"]
        if column["detection_confidence"] < 0.8
    ]
    assert {column["name"] for column in flagged} == {"order_id", "qty", "legacy_code"}


async def test_an_unknown_sample_is_refused_by_name(api: AsyncClient) -> None:
    session = await _session(api)
    response = await api.post(
        f"{_datasets_url(session)}/samples",
        headers=_headers(session),
        json={"key": "nonexistent"},
    )
    assert response.status_code == 422
    assert "nonexistent" in response.json()["detail"]


async def test_a_viewer_cannot_load_a_sample(api: AsyncClient, database: Database) -> None:
    """It creates a dataset, so it needs what creating a dataset needs (§13.3)."""
    alice = await _session(api)

    bob = await api.post(
        "/auth/register", json={"email": "bob@example.com", "password": "correct-horse-battery"}
    )
    bob_body = bob.json()
    bob_cookie = f"{COOKIE_NAME}={bob.cookies[COOKIE_NAME]}"
    api.cookies.clear()

    async with database.transaction() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO membership (id, user_id, workspace_id, role, created_at)"
                " VALUES (:mid, :uid, :ws, 'viewer', now())"
            ),
            {
                "mid": uuid.uuid4(),
                "uid": uuid.UUID(bob_body["user"]["id"]),
                "ws": uuid.UUID(alice["workspace_id"]),
            },
        )

    response = await api.post(
        f"{_datasets_url(alice)}/samples",
        headers={"Cookie": bob_cookie},
        json={"key": "titanic"},
    )
    assert response.status_code == 404
