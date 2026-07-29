"""Correcting a schema, end to end (FR-C.2, FR-C.3, INV-3, P0-15).

Two claims carry the weight here.

**A correction is a new version, never an edit.** An Analysis is bound to a
*specific* contract (§9.2), so editing one in place would silently change what
every finished analysis means. The route never issues an UPDATE — and the
database refuses one anyway, which is the difference between discipline and a
guarantee (§13.3).

**An override that discards values succeeds, and says so.** §10.2 gives the
decision to the person who knows what the column means; D-029 exists because
losing values quietly is the failure this whole design avoids. Both hold at
once, and the contract carries the cost in words.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy.exc import DBAPIError

from app.auth.tokens import COOKIE_NAME
from app.repositories.connection import Database
from app.repositories.tables import audit_event

pytestmark = pytest.mark.asyncio(loop_scope="session")

ORDERS = b"order_id,region,amount\n1,Jakarta,1500\n2,Medan,2300\n3,Solo,900\n"


async def _login(client: AsyncClient, email: str) -> dict[str, str]:
    response = await client.post(
        "/auth/register", json={"email": email, "password": "correct-horse-battery"}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return {
        "cookie": f"{COOKIE_NAME}={token}",
        "workspace_id": body["workspace"]["id"],
        "project_id": body["project"]["id"],
        "user_id": body["user"]["id"],
    }


def _headers(session: dict[str, str]) -> dict[str, str]:
    return {"Cookie": session["cookie"]}


async def _upload(
    api: AsyncClient, session: dict[str, str], content: bytes = ORDERS, name: str = "orders.csv"
) -> dict[str, Any]:
    response = await api.post(
        f"/workspaces/{session['workspace_id']}/projects/{session['project_id']}/datasets",
        headers=_headers(session),
        files={"file": (name, content, "text/csv")},
        data={"name": "orders"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _schema_url(session: dict[str, str], version_id: str) -> str:
    return f"/workspaces/{session['workspace_id']}/dataset-versions/{version_id}/schema"


@pytest.mark.invariant
async def test_correcting_a_type_creates_version_two_and_leaves_v1_alone(
    api: AsyncClient,
) -> None:
    """FR-C.2 + FR-C.3 + INV-3, at the level a user experiences them."""
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)
    url = _schema_url(session, body["version"]["id"])

    assert body["schema_contract"]["columns"][0]["logical_type"] == "integer"

    response = await api.post(
        url,
        headers=_headers(session),
        json={"columns": [{"name": "order_id", "logical_type": "text", "role": "identifier"}]},
    )
    assert response.status_code == 201, response.text
    v2 = response.json()

    assert v2["version_no"] == 2
    assert v2["derived_from"] == body["schema_contract"]["id"]
    assert v2["columns"][0]["logical_type"] == "text"
    assert v2["columns"][0]["role"] == "identifier"
    assert v2["columns"][0]["overridden"] is True
    # A human decision is not a detection — a 0.7 from the detector must not sit
    # underneath a type the user is certain of.
    assert v2["columns"][0]["detection_confidence"] == 1.0
    assert "by a user" in v2["columns"][0]["detection_reason"]

    # Untouched columns are carried over exactly, not re-detected. Re-running
    # inference here would undo an earlier decision the moment somebody edited
    # an unrelated column.
    assert v2["columns"][1] == body["schema_contract"]["columns"][1]

    assert (await api.get(url, headers=_headers(session))).json()["version_no"] == 2


async def test_an_override_that_would_discard_values_is_accepted_and_recorded(
    api: AsyncClient,
) -> None:
    """The honest middle between refusing the user and obeying silently."""
    session = await _login(api, "alice@example.com")
    rows = b"code\n" + b"".join(f"{i}\n".encode() for i in range(100)) + b"LG-1\nLG-2\n"
    body = await _upload(api, session, rows, name="codes.csv")

    response = await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "code", "logical_type": "integer"}]},
    )

    assert response.status_code == 201, response.text
    column = response.json()["columns"][0]
    assert column["logical_type"] == "integer"
    assert "2 of 102 values do not conform" in column["detection_reason"]


async def test_an_override_that_fits_says_so_too(api: AsyncClient) -> None:
    """The control. "Records the cost" is only meaningful if there is a no-cost case."""
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    response = await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "order_id", "logical_type": "decimal"}]},
    )
    assert "every value conforms" in response.json()["columns"][0]["detection_reason"]


async def test_corrections_stack_across_versions(api: AsyncClient) -> None:
    """v3 derives from v2, and v2's decision survives into it."""
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)
    url = _schema_url(session, body["version"]["id"])

    second = await api.post(
        url,
        headers=_headers(session),
        json={"columns": [{"name": "order_id", "logical_type": "text"}]},
    )
    third = await api.post(
        url,
        headers=_headers(session),
        json={"columns": [{"name": "amount", "logical_type": "text"}]},
    )

    assert third.status_code == 201, third.text
    v3 = third.json()
    assert v3["version_no"] == 3
    assert v3["derived_from"] == second.json()["id"]
    # The earlier correction is still there. A correction is not a reset.
    assert v3["columns"][0]["logical_type"] == "text"
    assert v3["columns"][0]["overridden"] is True


async def test_correcting_an_unknown_column_is_refused_by_name(api: AsyncClient) -> None:
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    response = await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "does_not_exist", "logical_type": "text"}]},
    )
    assert response.status_code == 422
    assert "does_not_exist" in response.json()["detail"]


async def test_an_unsupported_logical_type_is_refused_at_the_boundary(
    api: AsyncClient,
) -> None:
    """The wire vocabulary is closed (§9.2), and validation says so before we act."""
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    response = await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "order_id", "logical_type": "spreadsheet"}]},
    )
    assert response.status_code == 422


async def test_a_correction_that_changes_nothing_is_refused(api: AsyncClient) -> None:
    """A version that differs from its parent in nothing is noise in the history."""
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    response = await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "order_id"}]},
    )
    assert response.status_code == 422
    assert "nothing to change" in response.json()["detail"]


async def test_a_viewer_cannot_correct_a_schema(api: AsyncClient, database: Database) -> None:
    """§13.3: a viewer reads and runs read-only tools.

    Rewriting the meaning of every column is neither, and the refusal looks like
    absence — 404, not 403.
    """
    alice = await _login(api, "alice@example.com")
    bob = await _login(api, "bob@example.com")
    body = await _upload(api, alice)

    async with database.transaction() as connection:
        await connection.execute(
            sa.text(
                "INSERT INTO membership (id, user_id, workspace_id, role, created_at)"
                " VALUES (:mid, :uid, :ws, 'viewer', now())"
            ),
            {
                "mid": uuid.uuid4(),
                "uid": uuid.UUID(bob["user_id"]),
                "ws": uuid.UUID(alice["workspace_id"]),
            },
        )

    url = _schema_url(alice, body["version"]["id"])
    assert (await api.get(url, headers=_headers(bob))).status_code == 200

    response = await api.post(
        url,
        headers=_headers(bob),
        json={"columns": [{"name": "order_id", "logical_type": "text"}]},
    )
    assert response.status_code == 404


@pytest.mark.invariant
async def test_the_database_refuses_to_update_a_contract(
    api: AsyncClient, database: Database
) -> None:
    """INV-3 where it is actually enforced.

    The route never issues an UPDATE, but "our code does not do that" is
    discipline, and §13.3 rejects discipline as a mechanism. The trigger is why
    a correction *cannot* become an edit even from a hand-written statement.
    """
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    with pytest.raises(DBAPIError):
        async with database.transaction() as connection:
            await connection.execute(
                sa.text("UPDATE schema_contract SET version_no = 99 WHERE id = :id"),
                {"id": uuid.UUID(body["schema_contract"]["id"])},
            )


async def test_a_correction_is_audited_without_naming_a_column(
    api: AsyncClient, database: Database
) -> None:
    """§13.7 requires schema changes be recorded; §13.7.1 forbids the name.

    Ordinals identify the column and resolve through the contract. The name is
    sensitive (K1, §13.5.1), and this table can never be deleted from.
    """
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session)

    await api.post(
        _schema_url(session, body["version"]["id"]),
        headers=_headers(session),
        json={"columns": [{"name": "region", "logical_type": "text"}]},
    )

    async with database.transaction() as connection:
        rows = [
            row[0]
            for row in await connection.execute(
                sa.select(audit_event.c["metadata"]).where(
                    audit_event.c.action == "schema.contract_created"
                )
            )
        ]

    assert rows, "the correction was not recorded at all"
    assert rows[0]["changed_ordinals"] == [1]
    assert "region" not in repr(rows), "a column name reached the undeletable table"
