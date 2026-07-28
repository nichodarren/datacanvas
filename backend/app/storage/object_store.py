"""Object store abstraction (DESIGN.md §10.3, §10.5).

Filesystem in development, S3-compatible in production, one interface either
way. Callers never see a filesystem path unless they explicitly ask for one, and
only the local backend can give them one.

**Nothing outside ``app.storage`` and ``app.authz`` may import this module.**
It is the layer that turns a location into bytes, so importing it is equivalent
to bypassing authorization. That rule is enforced by
``tests/unit/test_authz_boundaries.py`` rather than by memory (§13.3.1 L3).

Methods are synchronous. Filesystem and S3 calls block, and pretending
otherwise by wrapping every one of them in a coroutine buys nothing; callers on
the request path offload with ``asyncio.to_thread``.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Protocol, runtime_checkable

from app.domain.errors import DomainError
from app.domain.ids import WorkspaceId
from app.storage.uri import StorageUri


class StorageError(DomainError):
    """The store refused an operation, or the object is missing."""


class ObjectNotFound(StorageError):
    pass


@runtime_checkable
class ObjectStore(Protocol):
    """What every backend must provide."""

    def write(self, uri: StorageUri, data: bytes) -> None: ...

    def read(self, uri: StorageUri) -> bytes: ...

    def exists(self, uri: StorageUri) -> bool: ...

    def delete(self, uri: StorageUri) -> None: ...

    def delete_workspace(self, workspace_id: WorkspaceId) -> None: ...

    def local_path(self, uri: StorageUri) -> Path:
        """A real path DuckDB can read.

        Present on the filesystem backend only; an S3 backend raises. Kept in
        the protocol so the analytics engine can state the requirement instead
        of discovering it at runtime in production.
        """
        ...


class FilesystemObjectStore:
    """Local filesystem backend.

    Every path goes through :meth:`_resolve`, which is where the traversal
    guarantee lives. There is intentionally no other way in.
    """

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def _resolve(self, uri: StorageUri) -> Path:
        """Turn a URI into an absolute path that provably sits under the root.

        ``StorageUri`` has already rejected traversal in the key itself. This
        check is the second one, and it catches what the first cannot: a
        *symlink* inside the store pointing somewhere else. ``resolve()``
        follows links, so the comparison happens on the real destination.

        Two independent checks for one property is deliberate. This is the
        boundary where a mistake means one tenant reads another's files.
        """
        candidate = (self._root / uri.relative_path).resolve()
        if candidate != self._root and self._root not in candidate.parents:
            raise StorageError(f"resolved path escapes the store root: {uri}")
        return candidate

    def write(self, uri: StorageUri, data: bytes) -> None:
        path = self._resolve(uri)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write beside the target and rename: a crash mid-write leaves the old
        # object intact rather than a truncated one. INV-2 promises a
        # DatasetVersion never changes, and a half-written file is a change.
        temporary = path.with_name(f"{path.name}.partial")
        temporary.write_bytes(data)
        temporary.replace(path)

    def read(self, uri: StorageUri) -> bytes:
        path = self._resolve(uri)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise ObjectNotFound(str(uri)) from exc

    def exists(self, uri: StorageUri) -> bool:
        return self._resolve(uri).is_file()

    def delete(self, uri: StorageUri) -> None:
        """Missing is success. Deletion is required to be idempotent (FR-B.6)."""
        self._resolve(uri).unlink(missing_ok=True)

    def delete_workspace(self, workspace_id: WorkspaceId) -> None:
        """Remove everything belonging to one workspace (NFR-PRIV.3)."""
        target = (self._root / "workspaces" / str(workspace_id)).resolve()
        if self._root not in target.parents:
            raise StorageError(f"refusing to delete outside the store root: {target}")
        shutil.rmtree(target, ignore_errors=True)

    def local_path(self, uri: StorageUri) -> Path:
        path = self._resolve(uri)
        if not path.is_file():
            raise ObjectNotFound(str(uri))
        return path


__all__ = [
    "FilesystemObjectStore",
    "ObjectNotFound",
    "ObjectStore",
    "StorageError",
]
