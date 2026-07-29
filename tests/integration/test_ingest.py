"""Ingest end to end, against the real app and a real database (FR-B.1..B.4, B.6).

The cross-tenant sweep proves nobody *else* can reach these routes. It says
nothing about whether an upload actually works, and a route that 404s for
everyone would pass every test in that file. This is the other half.

The claims worth testing here are the ones a happy-path test would skip:

* a re-upload creates a **version**, never an overwrite (FR-B.2) — the whole
  basis of determinism (P4);
* deletion really removes the bytes (FR-B.6), not only the rows;
* a failed commit leaves nothing behind, because storage does not roll back
  when the transaction does;
* the audit trail records what happened and **not** what was in the file
  (§13.7.1).
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from httpx import AsyncClient

from app.auth.tokens import COOKIE_NAME
from app.repositories.connection import Database
from app.repositories.tables import audit_event, dataset, dataset_version, source_file

pytestmark = pytest.mark.asyncio(loop_scope="session")

ORDERS = b"order_id,region,amount\n1,Jakarta,1500\n2,Medan,2300\n3,Solo,900\n"
ORDERS_V2 = b"order_id,region,amount\n1,Jakarta,1500\n2,Medan,2300\n3,Solo,900\n4,Bogor,120\n"


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


def _datasets_url(session: dict[str, str]) -> str:
    return f"/workspaces/{session['workspace_id']}/projects/{session['project_id']}/datasets"


async def _upload(
    api: AsyncClient, session: dict[str, str], content: bytes, name: str = "orders.csv"
) -> dict[str, Any]:
    response = await api.post(
        _datasets_url(session),
        headers=_headers(session),
        files={"file": (name, content, "text/csv")},
        data={"name": "orders"},
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


# ------------------------------------------------------------------ preview --


async def test_preview_describes_the_file_without_storing_it(
    api: AsyncClient, tmp_path: Path
) -> None:
    """D-025 through the actual HTTP route, not just the function underneath."""
    session = await _login(api, "alice@example.com")

    storage = tmp_path / "storage"
    before = sorted(p for p in storage.rglob("*") if p.is_file()) if storage.exists() else []

    response = await api.post(
        "/uploads/preview",
        headers=_headers(session),
        files={"file": ("orders.csv", ORDERS, "text/csv")},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["format"] == "csv"
    assert body["dialect"]["delimiter"] == ","
    assert body["dialect"]["has_header"] is True
    assert body["columns"] == ["order_id", "region", "amount"]
    assert body["sample_rows"][0] == ["1", "Jakarta", "1500"]
    # The response deliberately carries no handle back (D-025).
    assert "id" not in body and "upload_id" not in body

    after = sorted(p for p in storage.rglob("*") if p.is_file()) if storage.exists() else []
    assert after == before, "preview must not write anything (D-025)"


async def test_preview_requires_a_session(api: AsyncClient) -> None:
    """Not tenant-scoped is not the same as open.

    Parsing arbitrary bytes is work, and work an anonymous caller can ask for is
    work an anonymous caller can ask for a million times (NFR-SEC.6).
    """
    response = await api.post(
        "/uploads/preview", files={"file": ("orders.csv", ORDERS, "text/csv")}
    )
    assert response.status_code == 401


async def test_a_file_that_cannot_be_parsed_is_refused_with_a_reason(api: AsyncClient) -> None:
    """P6: an honest failure that names the problem, not a 500."""
    session = await _login(api, "alice@example.com")

    response = await api.post(
        "/uploads/preview",
        headers=_headers(session),
        files={"file": ("notes.txt", b"just one line, no columns anywhere", "text/plain")},
    )
    assert response.status_code == 422
    assert "separator" in response.json()["detail"]


# ------------------------------------------------------------------- commit --


async def test_upload_creates_a_dataset_a_version_and_a_source_file(
    api: AsyncClient, database: Database
) -> None:
    session = await _login(api, "alice@example.com")

    body = await _upload(api, session, ORDERS)

    assert body["dataset"]["name"] == "orders"
    assert body["version"]["version_no"] == 1
    assert body["version"]["row_count"] == 3
    assert body["version"]["column_count"] == 3
    assert body["columns"] == ["order_id", "region", "amount"]
    assert body["original_filename"] == "orders.csv"
    assert len(body["version"]["content_hash"]) == 64

    async with database.transaction() as connection:
        stored = (
            await connection.execute(
                sa.select(source_file).where(
                    source_file.c.dataset_version_id == uuid.UUID(body["version"]["id"])
                )
            )
        ).one()
    # The verbatim copy is kept (§9.2), and its name is a uuid rather than
    # anything the client chose (§13.6).
    assert stored.original_filename == "orders.csv"
    assert "orders.csv" not in stored.storage_uri
    assert stored.mime_detected == "csv"


async def test_the_uploaded_data_is_readable_afterwards(api: AsyncClient) -> None:
    """The version route resolves, and the bytes are really there.

    ``data_present`` is computed through ``data_access.open_dataset_version``,
    so a true here means the whole chain worked: authorization, storage layout
    and the write itself.
    """
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session, ORDERS)

    response = await api.get(
        f"/workspaces/{session['workspace_id']}/dataset-versions/{body['version']['id']}",
        headers=_headers(session),
    )
    assert response.status_code == 200, response.text
    assert response.json()["data_present"] is True
    assert response.json()["row_count"] == 3


async def test_reuploading_adds_a_version_and_never_overwrites(
    api: AsyncClient, database: Database
) -> None:
    """FR-B.2, and the reason it is P0.

    Without this, "the same answer to the same question" holds only until
    somebody re-uploads a file with the same name — which is to say it does not
    hold at all (P4).
    """
    session = await _login(api, "alice@example.com")
    first = await _upload(api, session, ORDERS)
    dataset_id = first["dataset"]["id"]

    response = await api.post(
        f"{_datasets_url(session)}/{dataset_id}/versions",
        headers=_headers(session),
        files={"file": ("orders.csv", ORDERS_V2, "text/csv")},
    )
    assert response.status_code == 201, response.text
    second = response.json()

    assert second["dataset"]["id"] == dataset_id
    assert second["version"]["version_no"] == 2
    assert second["version"]["row_count"] == 4
    assert second["version"]["id"] != first["version"]["id"]
    assert second["version"]["content_hash"] != first["version"]["content_hash"]

    # v1 is untouched — still there, still three rows, still the same bytes.
    still = await api.get(
        f"/workspaces/{session['workspace_id']}/dataset-versions/{first['version']['id']}",
        headers=_headers(session),
    )
    assert still.status_code == 200
    assert still.json()["row_count"] == 3
    assert still.json()["data_present"] is True

    async with database.transaction() as connection:
        count = await connection.scalar(
            sa.select(sa.func.count())
            .select_from(dataset_version)
            .where(dataset_version.c.dataset_id == uuid.UUID(str(dataset_id)))
        )
    assert count == 2


async def test_identical_uploads_produce_identical_hashes(api: AsyncClient) -> None:
    """INV-6 at the API boundary: same bytes in, same content hash out.

    Two versions, deliberately — FR-B.2 says a re-upload is a new version, so
    this also pins that "new version" does not mean "different data".
    """
    session = await _login(api, "alice@example.com")
    first = await _upload(api, session, ORDERS)

    response = await api.post(
        f"{_datasets_url(session)}/{first['dataset']['id']}/versions",
        headers=_headers(session),
        files={"file": ("orders-again.csv", ORDERS, "text/csv")},
    )
    assert response.status_code == 201, response.text
    assert response.json()["version"]["content_hash"] == first["version"]["content_hash"]


async def test_a_windows_encoded_file_keeps_its_characters(api: AsyncClient) -> None:
    """The data-loss bug, guarded at the level a user would notice it.

    Handing a cp1252 file to polars' ``utf8-lossy`` silently replaced every
    non-ASCII character. Indonesian text out of Excel is exactly the case, so
    this asserts on the value rather than on the encoding label.
    """
    session = await _login(api, "alice@example.com")
    content = "kota,catatan\nBogor,café dekat alun-alun\n".encode("cp1252")

    body = await _upload(api, session, content, name="kota.csv")
    assert body["version"]["row_count"] == 1

    preview = await api.post(
        "/uploads/preview",
        headers=_headers(session),
        files={"file": ("kota.csv", content, "text/csv")},
    )
    assert preview.json()["dialect"]["encoding"] == "cp1252"
    assert preview.json()["sample_rows"][0][1] == "café dekat alun-alun"


async def test_a_wrong_delimiter_is_refused_rather_than_committed(
    api: AsyncClient, database: Database
) -> None:
    """The silent-success defect, refused at the API and leaving nothing behind."""
    session = await _login(api, "alice@example.com")

    response = await api.post(
        _datasets_url(session),
        headers=_headers(session),
        files={"file": ("orders.csv", ORDERS, "text/csv")},
        data={"name": "orders", "delimiter": ";"},
    )
    assert response.status_code == 422
    assert "';'" in response.json()["detail"]

    async with database.transaction() as connection:
        versions = await connection.scalar(sa.select(sa.func.count()).select_from(dataset_version))
    assert versions == 0, "a refused upload must not leave a version behind"


async def test_a_failed_commit_leaves_no_files_behind(api: AsyncClient, tmp_path: Path) -> None:
    """Storage does not roll back when the transaction does.

    An orphaned Parquet is user data that no row can authorize access to — it
    would sit in the workspace tree indefinitely, outside every guarantee the
    rest of the system makes about deletion (NFR-PRIV.3).
    """
    session = await _login(api, "alice@example.com")

    response = await api.post(
        _datasets_url(session),
        headers=_headers(session),
        files={"file": ("orders.csv", ORDERS, "text/csv")},
        data={"name": "orders", "delimiter": ";"},
    )
    assert response.status_code == 422

    storage = tmp_path / "storage"
    leftovers = [p for p in storage.rglob("*") if p.is_file()] if storage.exists() else []
    assert leftovers == [], f"failed commit left files behind: {leftovers}"


async def test_a_viewer_cannot_upload(api: AsyncClient, database: Database) -> None:
    """§13.3: a viewer reads and runs read-only tools. It does not upload.

    And a refusal looks exactly like a missing resource — 404, not 403.
    """
    alice = await _login(api, "alice@example.com")
    bob = await _login(api, "bob@example.com")

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

    response = await api.post(
        _datasets_url(alice),
        headers=_headers(bob),
        files={"file": ("orders.csv", ORDERS, "text/csv")},
        data={"name": "sneaky"},
    )
    assert response.status_code == 404


# ------------------------------------------------------------------ deletion --


async def test_deleting_a_dataset_removes_the_files_not_only_the_rows(
    api: AsyncClient, database: Database, tmp_path: Path
) -> None:
    """FR-B.6, and the half that is easy to skip.

    Deleting rows is the visible half. NFR-PRIV.3 promises the bytes go too, and
    a test that only counts rows would pass while the data sat on disk.
    """
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session, ORDERS)

    storage = tmp_path / "storage"
    assert [p for p in storage.rglob("*") if p.is_file()], "nothing was written to begin with"

    response = await api.delete(
        f"{_datasets_url(session)}/{body['dataset']['id']}", headers=_headers(session)
    )
    assert response.status_code == 204, response.text

    assert [p for p in storage.rglob("*") if p.is_file()] == [], "the files are still on disk"

    async with database.transaction() as connection:
        datasets = await connection.scalar(sa.select(sa.func.count()).select_from(dataset))
        versions = await connection.scalar(sa.select(sa.func.count()).select_from(dataset_version))
    assert (datasets, versions) == (0, 0)


async def test_deleting_leaves_the_audit_trail_intact(api: AsyncClient, database: Database) -> None:
    """D-023: the audit log outlives the data it describes.

    That is not a side effect — it is the reason the audit log has no foreign
    keys. A record of what happened that disappears with the thing it happened
    to is not a record.
    """
    session = await _login(api, "alice@example.com")
    body = await _upload(api, session, ORDERS)

    await api.delete(f"{_datasets_url(session)}/{body['dataset']['id']}", headers=_headers(session))

    async with database.transaction() as connection:
        actions = [
            row.action
            for row in await connection.execute(
                sa.select(audit_event.c.action).where(audit_event.c.action.like("dataset.%"))
            )
        ]
    assert "dataset.created" in actions
    assert "dataset.version_created" in actions
    assert "dataset.deleted" in actions


@pytest.mark.invariant
async def test_the_audit_record_contains_no_data_and_no_column_names(
    api: AsyncClient, database: Database
) -> None:
    """§13.7.1 — the rule that keeps append-only compatible with NFR-PRIV.3.

    ``audit_event`` cannot be deleted from, so anything sensitive that lands in
    it is undeletable. Column names count as sensitive (K1, §13.5.1), and so
    does the filename a user chose.
    """
    session = await _login(api, "alice@example.com")
    await _upload(api, session, ORDERS, name="gaji_karyawan_2026.csv")

    async with database.transaction() as connection:
        rows = [
            row[0]
            for row in await connection.execute(
                sa.select(audit_event.c["metadata"]).where(
                    audit_event.c.action == "dataset.version_created"
                )
            )
        ]

    assert rows, "the event was not recorded at all"
    blob = repr(rows)
    for forbidden in ("gaji_karyawan", "order_id", "region", "Jakarta", "amount"):
        assert forbidden not in blob, (
            f"{forbidden!r} reached the audit log, which cannot be deleted from (§13.7.1)"
        )
