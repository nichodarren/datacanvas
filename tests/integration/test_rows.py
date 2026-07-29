"""Server-side pagination for the grid (FR-D.1, FR-D.2)."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient

from app.auth.tokens import COOKIE_NAME
from app.storage.engine import MAX_PAGE_SIZE

pytestmark = pytest.mark.asyncio(loop_scope="session")

ROWS = b"n,label\n" + b"".join(f"{i},row-{i}\n".encode() for i in range(500))


async def _session(client: AsyncClient) -> dict[str, str]:
    response = await client.post(
        "/auth/register", json={"email": "alice@example.com", "password": "correct-horse-battery"}
    )
    body = response.json()
    token = response.cookies[COOKIE_NAME]
    client.cookies.clear()
    return {
        "cookie": f"{COOKIE_NAME}={token}",
        "workspace_id": body["workspace"]["id"],
        "project_id": body["project"]["id"],
    }


async def _upload(api: AsyncClient, session: dict[str, str]) -> dict[str, Any]:
    response = await api.post(
        f"/workspaces/{session['workspace_id']}/projects/{session['project_id']}/datasets",
        headers={"Cookie": session["cookie"]},
        files={"file": ("rows.csv", ROWS, "text/csv")},
        data={"name": "rows"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _url(session: dict[str, str], version_id: str) -> str:
    return f"/workspaces/{session['workspace_id']}/dataset-versions/{version_id}/rows"


async def test_a_page_carries_what_the_grid_needs_to_render(api: AsyncClient) -> None:
    session = await _session(api)
    body = await _upload(api, session)

    response = await api.get(
        _url(session, body["version"]["id"]),
        headers={"Cookie": session["cookie"]},
        params={"offset": 0, "limit": 10},
    )

    assert response.status_code == 200, response.text
    page = response.json()
    assert page["columns"] == ["n", "label"]
    assert page["rows"][0] == ["0", "row-0"]
    assert len(page["rows"]) == 10
    # The grid needs the total to size its scrollbar without fetching everything.
    assert page["total_rows"] == 500


async def test_paging_covers_every_row_exactly_once(api: AsyncClient) -> None:
    """FR-D.1's real promise, asserted as a sweep rather than one page.

    Any single page looks plausible whatever the order is. A row returned twice
    and a row never returned are the same defect seen from two sides.
    """
    session = await _session(api)
    body = await _upload(api, session)

    seen: list[str] = []
    for offset in range(0, 500, 100):
        response = await api.get(
            _url(session, body["version"]["id"]),
            headers={"Cookie": session["cookie"]},
            params={"offset": offset, "limit": 100},
        )
        seen.extend(row[0] for row in response.json()["rows"])

    assert seen == [str(i) for i in range(500)]


async def test_the_page_size_cap_is_enforced_by_the_engine(api: AsyncClient) -> None:
    """FR-D.2 lets the user choose the page size, not the response size.

    The cap lives in the engine so it holds for every caller, and asking for
    more is refused with a reason rather than quietly truncated — a silently
    shortened page looks like missing data.
    """
    session = await _session(api)
    body = await _upload(api, session)

    response = await api.get(
        _url(session, body["version"]["id"]),
        headers={"Cookie": session["cookie"]},
        params={"offset": 0, "limit": MAX_PAGE_SIZE + 1},
    )
    assert response.status_code == 422
    assert str(MAX_PAGE_SIZE) in response.json()["detail"]


async def test_paging_past_the_end_is_empty_rather_than_an_error(api: AsyncClient) -> None:
    """Scrolling one step too far is navigation, not a failure."""
    session = await _session(api)
    body = await _upload(api, session)

    response = await api.get(
        _url(session, body["version"]["id"]),
        headers={"Cookie": session["cookie"]},
        params={"offset": 10_000, "limit": 100},
    )
    assert response.status_code == 200
    assert response.json()["rows"] == []
    assert response.json()["columns"] == ["n", "label"]
