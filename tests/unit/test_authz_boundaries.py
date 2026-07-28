"""Layer 3 of INV-7: there is no way to reach data except through a handle.

Two claims are tested here.

1. ``DataHandle`` cannot be built by ordinary code. Python has no private
   constructors, so this cannot be made *impossible* — a determined caller can
   reach the module-private token. The goal is narrower and still worth having:
   the accidental path, the one written at the end of a long day, fails on the
   first run rather than in production.

2. Nothing outside ``app.storage`` and ``app.authz`` imports the object store.
   Importing it is equivalent to bypassing authorization, so the import graph
   is checked the same way ``domain/`` is (§10.6).
"""

from __future__ import annotations

import ast
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.authz.data_access import DataHandle
from app.domain.data import DatasetVersion
from app.domain.errors import AuthorizationError
from app.domain.ids import DatasetId, DatasetVersionId, SessionId, UserId, WorkspaceId
from app.domain.principal import Principal
from app.storage.object_store import FilesystemObjectStore
from app.storage.uri import dataset_version_data_uri

BACKEND = Path(__file__).resolve().parents[2] / "backend" / "app"

#: Only these packages may import the object store.
STORE_MODULE = "app.storage.object_store"
ALLOWED_STORE_IMPORTERS = ("app/storage/", "app/authz/", "app/api/")

WS = WorkspaceId(uuid.UUID("00000000-0000-4000-8000-0000000000aa"))
DS = DatasetId(uuid.UUID("00000000-0000-4000-8000-0000000000cc"))
DV = DatasetVersionId(uuid.UUID("00000000-0000-4000-8000-0000000000dd"))
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)


def _version() -> DatasetVersion:
    return DatasetVersion(
        id=DV,
        dataset_id=DS,
        version_no=1,
        content_hash="a" * 64,
        parquet_uri=str(dataset_version_data_uri(WS, DS, DV)),
        row_count=1,
        column_count=1,
        byte_size=1,
        ingested_at=T0,
        ingested_by=UserId(uuid.uuid4()),
    )


@pytest.mark.invariant
def test_data_handle_cannot_be_constructed_directly(tmp_path: Path) -> None:
    """The whole point of INV-7: a handle is proof, not a container.

    If this were constructible, every guarantee above it would be decoration.
    """
    principal = Principal(
        user_id=UserId(uuid.uuid4()), session_id=SessionId(uuid.uuid4()), memberships={}
    )
    with pytest.raises(AuthorizationError):
        DataHandle(
            principal=principal,
            workspace_id=WS,
            version=_version(),
            uri=dataset_version_data_uri(WS, DS, DV),
            _store=FilesystemObjectStore(tmp_path),
            _grant=object(),  # anything but the real token
        )


@pytest.mark.invariant
def test_only_storage_authz_and_api_import_the_object_store() -> None:
    """Importing the store is equivalent to bypassing the authorization layer.

    ``api/`` is on the list because it wires the store into the app at startup;
    it never resolves a URI itself — the routes go through
    ``open_dataset_version``, and the cross-tenant sweep is what proves it.
    """
    offenders: list[str] = []
    for module_path in sorted(BACKEND.rglob("*.py")):
        relative = module_path.relative_to(BACKEND.parent).as_posix()
        if relative.startswith(ALLOWED_STORE_IMPORTERS):
            continue

        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.ImportFrom) and node.module == STORE_MODULE) or (
                isinstance(node, ast.Import)
                and any(alias.name == STORE_MODULE for alias in node.names)
            ):
                offenders.append(relative)

    assert not offenders, (
        f"{sorted(set(offenders))} import {STORE_MODULE}. Data must be reached through "
        f"data_access.open_dataset_version() (DESIGN.md §13.3.1 L3)."
    )


@pytest.mark.invariant
def test_authz_package_does_not_import_the_api_layer() -> None:
    """Authorization must not depend on how a request happened to arrive.

    A rule that knows about HTTP is a rule that gets a second implementation
    the first time something calls it from a background job.
    """
    for module_path in sorted((BACKEND / "authz").rglob("*.py")):
        tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
        imported = [
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        ]
        assert not [name for name in imported if name.startswith("app.api")], (
            f"{module_path.name} imports the API layer"
        )
