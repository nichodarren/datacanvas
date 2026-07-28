"""``storage://`` URIs and the layout behind them (DESIGN.md §10.5).

Tenant isolation shows up in the *path*, not only in the query:

```
workspaces/{workspace_id}/
  datasets/{dataset_id}/versions/{version_id}/
    data.parquet
    source/{uuid}{suffix}
  artifacts/{computation_id}/...
```

That gives a second line of defence — a traversal that somehow gets past the
authorization layer still lands inside the workspace it started in. Swapping
filesystem for S3 changes how a URI is resolved, never what it means.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from uuid import UUID

from app.domain.errors import DomainError
from app.domain.ids import DatasetId, DatasetVersionId, WorkspaceId

SCHEME = "storage://"

#: One path segment. No dots at all, so "." and ".." cannot be spelled, and no
#: separators, so a segment can never expand into several.
_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")


class StorageUriError(DomainError):
    """A URI that is malformed, or that tries to leave its workspace."""


@dataclass(frozen=True, slots=True)
class StorageUri:
    """A validated location inside the object store.

    Construction is the validation. Once one of these exists, the path it
    carries is known to be workspace-relative and free of traversal — so the
    backends do not each have to re-derive that.
    """

    workspace_id: WorkspaceId
    key: str

    def __post_init__(self) -> None:
        if not self.key:
            raise StorageUriError("storage key must not be empty")
        for segment in self.key.split("/"):
            if not _SEGMENT.match(segment):
                raise StorageUriError(
                    f"illegal path segment {segment!r} in {self.key!r};"
                    " segments allow letters, digits, '_', '-' and internal dots only"
                )
        # Belt and braces: even with the segment rule above, normalising must
        # not move the path. If it does, something got through.
        if posixpath.normpath(self.key) != self.key:
            raise StorageUriError(f"key {self.key!r} is not in normal form")

    def __str__(self) -> str:
        return f"{SCHEME}workspaces/{self.workspace_id}/{self.key}"

    @property
    def relative_path(self) -> str:
        """Path relative to the store root, including the workspace prefix."""
        return f"workspaces/{self.workspace_id}/{self.key}"

    @classmethod
    def parse(cls, uri: str) -> StorageUri:
        if not uri.startswith(SCHEME):
            raise StorageUriError(f"not a storage URI: {uri!r}")
        rest = uri[len(SCHEME) :]
        parts = rest.split("/")
        if len(parts) < 3 or parts[0] != "workspaces":
            raise StorageUriError(f"storage URI must start with workspaces/<id>/: {uri!r}")
        try:
            workspace_id = WorkspaceId(UUID(parts[1]))
        except ValueError as exc:
            raise StorageUriError(f"invalid workspace id in {uri!r}") from exc
        return cls(workspace_id=workspace_id, key="/".join(parts[2:]))


def dataset_version_data_uri(
    workspace_id: WorkspaceId, dataset_id: DatasetId, version_id: DatasetVersionId
) -> StorageUri:
    """Where the normalized Parquet for a DatasetVersion lives."""
    return StorageUri(
        workspace_id=workspace_id,
        key=f"datasets/{dataset_id}/versions/{version_id}/data.parquet",
    )


def source_file_uri(
    workspace_id: WorkspaceId,
    dataset_id: DatasetId,
    version_id: DatasetVersionId,
    source_file_id: UUID,
    suffix: str = "",
) -> StorageUri:
    """Where the uploaded file is kept verbatim.

    Named by id, never by the uploaded filename (§13.6). A filename is attacker
    controlled, and the safest thing to do with it is to keep it out of the path
    entirely rather than to sanitise it well.
    """
    cleaned = suffix.lower().lstrip(".")
    # A suffix is one extension, not a path fragment. Without this check,
    # `a/b` passes — each half is a legal segment on its own — and the object
    # quietly lands a directory deeper than intended. It stays inside the
    # workspace, so it is not a breach; it is worse in one way, because
    # nothing fails and the file is simply somewhere else.
    if cleaned and not cleaned.isalnum():
        raise StorageUriError(f"file suffix must be alphanumeric, got {suffix!r}")
    name = f"{source_file_id}.{cleaned}" if cleaned else str(source_file_id)
    return StorageUri(
        workspace_id=workspace_id,
        key=f"datasets/{dataset_id}/versions/{version_id}/source/{name}",
    )


__all__ = [
    "SCHEME",
    "StorageUri",
    "StorageUriError",
    "dataset_version_data_uri",
    "source_file_uri",
]
