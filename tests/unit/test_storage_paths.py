"""Path handling in the object store (DESIGN.md §10.5, §13.4, §13.6).

Tenant isolation is expressed in the path, so this is the boundary where a
mistake means one tenant reads another's files. Two independent guards exist —
the URI rejects traversal syntactically, the store re-checks the resolved path —
and both are tested, because "the other one would have caught it" is how both
end up removed.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

from app.domain.ids import DatasetId, DatasetVersionId, WorkspaceId
from app.storage.object_store import FilesystemObjectStore, ObjectNotFound, StorageError
from app.storage.uri import (
    StorageUri,
    StorageUriError,
    dataset_version_data_uri,
    source_file_uri,
)

WS = WorkspaceId(uuid.UUID("00000000-0000-4000-8000-0000000000aa"))
OTHER_WS = WorkspaceId(uuid.UUID("00000000-0000-4000-8000-0000000000bb"))
DS = DatasetId(uuid.UUID("00000000-0000-4000-8000-0000000000cc"))
DV = DatasetVersionId(uuid.UUID("00000000-0000-4000-8000-0000000000dd"))


# -------------------------------------------------------------------- URI ----


@pytest.mark.parametrize(
    "key",
    [
        "../secrets",
        "datasets/../../etc/passwd",
        "..",
        "./data.parquet",
        "datasets//double",
        "/absolute",
        "datasets/x/../y",
        "C:/windows/system32",
        "data\\parquet",
        "datasets/\x00null",
    ],
)
def test_uri_rejects_traversal_and_odd_segments(key: str) -> None:
    with pytest.raises(StorageUriError):
        StorageUri(workspace_id=WS, key=key)


def test_uri_rejects_empty_key() -> None:
    with pytest.raises(StorageUriError):
        StorageUri(workspace_id=WS, key="")


def test_uri_round_trips() -> None:
    original = dataset_version_data_uri(WS, DS, DV)
    assert StorageUri.parse(str(original)) == original


@pytest.mark.parametrize(
    "text",
    [
        "s3://workspaces/x/y",
        "storage://datasets/x",
        "storage://workspaces/not-a-uuid/data.parquet",
        "storage://workspaces/",
        "/workspaces/x/y",
    ],
)
def test_parse_rejects_malformed_uris(text: str) -> None:
    with pytest.raises(StorageUriError):
        StorageUri.parse(text)


def test_layout_namespaces_by_workspace() -> None:
    """§10.5: isolation shows up in the path, not only in the query."""
    uri = dataset_version_data_uri(WS, DS, DV)
    assert uri.relative_path.startswith(f"workspaces/{WS}/")
    assert dataset_version_data_uri(OTHER_WS, DS, DV).relative_path != uri.relative_path


def test_source_file_never_uses_the_uploaded_name() -> None:
    """§13.6: a filename is attacker-controlled; the safest use of it is none."""
    file_id = uuid.uuid4()
    uri = source_file_uri(WS, DS, DV, file_id, suffix=".CSV")
    assert str(file_id) in uri.key
    assert uri.key.endswith(".csv")


@pytest.mark.parametrize("suffix", ["../../evil", "csv/../..", "a/b"])
def test_source_file_suffix_cannot_smuggle_a_path(suffix: str) -> None:
    with pytest.raises(StorageUriError):
        source_file_uri(WS, DS, DV, uuid.uuid4(), suffix=suffix)


# ------------------------------------------------------------------ store ----


@pytest.fixture
def store(tmp_path: Path) -> FilesystemObjectStore:
    return FilesystemObjectStore(tmp_path / "storage")


def test_write_then_read(store: FilesystemObjectStore) -> None:
    uri = dataset_version_data_uri(WS, DS, DV)
    store.write(uri, b"parquet-bytes")
    assert store.read(uri) == b"parquet-bytes"
    assert store.exists(uri)


def test_read_missing_object_raises(store: FilesystemObjectStore) -> None:
    with pytest.raises(ObjectNotFound):
        store.read(dataset_version_data_uri(WS, DS, DV))


def test_delete_is_idempotent(store: FilesystemObjectStore) -> None:
    """FR-B.6 deletion must not fail because it already happened."""
    uri = dataset_version_data_uri(WS, DS, DV)
    store.write(uri, b"x")
    store.delete(uri)
    store.delete(uri)
    assert not store.exists(uri)


def test_write_is_atomic_enough_to_leave_no_partial_file(
    store: FilesystemObjectStore,
) -> None:
    """A half-written object would be a DatasetVersion that changed (INV-2)."""
    uri = dataset_version_data_uri(WS, DS, DV)
    store.write(uri, b"first")
    store.write(uri, b"second")
    assert store.read(uri) == b"second"
    leftovers = list(store.root.rglob("*.partial"))
    assert not leftovers


def test_deleting_a_workspace_leaves_others_untouched(
    store: FilesystemObjectStore,
) -> None:
    """NFR-PRIV.3 deletion is per tenant, and must stay that way."""
    mine = dataset_version_data_uri(WS, DS, DV)
    theirs = dataset_version_data_uri(OTHER_WS, DS, DV)
    store.write(mine, b"a")
    store.write(theirs, b"b")

    store.delete_workspace(WS)

    assert not store.exists(mine)
    assert store.exists(theirs)


@pytest.mark.invariant
def test_symlink_out_of_the_store_is_refused(store: FilesystemObjectStore, tmp_path: Path) -> None:
    """The case the URI rules cannot see.

    ``StorageUri`` validates syntax; a symlink is a fact about the filesystem.
    Only resolving the real path catches it, which is why the store checks
    again after ``resolve()``.
    """
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.parquet").write_bytes(b"another tenant's data")

    link = store.root / "workspaces" / str(WS) / "datasets"
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):  # pragma: no cover
        pytest.skip("creating symlinks needs privileges this machine does not grant")

    uri = StorageUri(workspace_id=WS, key="datasets/secret.parquet")
    with pytest.raises(StorageError):
        store.read(uri)


def test_local_path_stays_under_the_root(store: FilesystemObjectStore) -> None:
    uri = dataset_version_data_uri(WS, DS, DV)
    store.write(uri, b"x")
    resolved = store.local_path(uri)
    assert store.root in resolved.parents


def test_local_path_on_missing_object_raises(store: FilesystemObjectStore) -> None:
    with pytest.raises(ObjectNotFound):
        store.local_path(dataset_version_data_uri(WS, DS, DV))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific path shapes")
@pytest.mark.parametrize("key", ["datasets/con", "datasets/x:stream"])
def test_windows_reserved_shapes_are_rejected_or_contained(key: str) -> None:
    """Alternate data streams and device names are Windows' own traversal tricks."""
    if ":" in key:
        with pytest.raises(StorageUriError):
            StorageUri(workspace_id=WS, key=key)
    else:
        # `con` is a legal segment by our rules; what matters is that it stays
        # inside the workspace prefix rather than addressing a device.
        assert StorageUri(workspace_id=WS, key=key).relative_path.startswith("workspaces/")
