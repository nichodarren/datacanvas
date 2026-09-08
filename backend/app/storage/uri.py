"""``storage://`` URIs and the layout behind them (DESIGN.md §10.5).

Tenant isolation shows up in the *path*, not only in the query:

```
users/{owner_id}/
  datasets/{dataset_id}/
    data.parquet
    source/{uuid}{suffix}
  artifacts/{computation_id}/...
```

The `versions/{version_id}/` segment came out with D-043. Rows written before
that keep the URI they were written with — a `parquet_uri` sits on an immutable
row, so the honest way to change one is not to change it, and the file is still
where it says it is.

That gives a second line of defence — a traversal that somehow gets past the
authorization layer still lands inside the tenant it started in. Swapping
filesystem for S3 changes how a URI is resolved, never what it means.

The prefix read ``workspaces/{workspace_id}/`` until D-039. Only the key
changed: the account is the tenant now, so the tenant's id is the user's. The
guarantee is the same one, spelled with a different id — which is why migration
0004 deletes the rows carrying the old prefix rather than rewriting them. A URI
is on an immutable row (INV-2), and the honest way to change an immutable value
is not to change it.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from uuid import UUID

from app.domain.errors import DomainError
from app.domain.ids import DatasetId, UserId

SCHEME = "storage://"

#: One path segment. No dots at all, so "." and ".." cannot be spelled, and no
#: separators, so a segment can never expand into several.
_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*$")


class StorageUriError(DomainError):
    """A URI that is malformed, or that tries to leave its tenant."""


@dataclass(frozen=True, slots=True)
class StorageUri:
    """A validated location inside the object store.

    Construction is the validation. Once one of these exists, the path it
    carries is known to be tenant-relative and free of traversal — so the
    backends do not each have to re-derive that.
    """

    owner_id: UserId
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
        return f"{SCHEME}users/{self.owner_id}/{self.key}"

    @property
    def relative_path(self) -> str:
        """Path relative to the store root, including the tenant prefix."""
        return f"users/{self.owner_id}/{self.key}"

    @classmethod
    def parse(cls, uri: str) -> StorageUri:
        if not uri.startswith(SCHEME):
            raise StorageUriError(f"not a storage URI: {uri!r}")
        rest = uri[len(SCHEME) :]
        parts = rest.split("/")
        if len(parts) < 3 or parts[0] != "users":
            raise StorageUriError(f"storage URI must start with users/<id>/: {uri!r}")
        try:
            owner_id = UserId(UUID(parts[1]))
        except ValueError as exc:
            raise StorageUriError(f"invalid owner id in {uri!r}") from exc
        return cls(owner_id=owner_id, key="/".join(parts[2:]))


def dataset_data_uri(owner_id: UserId, dataset_id: DatasetId) -> StorageUri:
    """Where the normalized Parquet for a Dataset lives."""
    return StorageUri(owner_id=owner_id, key=f"datasets/{dataset_id}/data.parquet")


def source_file_uri(
    owner_id: UserId,
    dataset_id: DatasetId,
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
    # tenant, so it is not a breach; it is worse in one way, because
    # nothing fails and the file is simply somewhere else.
    if cleaned and not cleaned.isalnum():
        raise StorageUriError(f"file suffix must be alphanumeric, got {suffix!r}")
    name = f"{source_file_id}.{cleaned}" if cleaned else str(source_file_id)
    return StorageUri(owner_id=owner_id, key=f"datasets/{dataset_id}/source/{name}")


__all__ = [
    "SCHEME",
    "StorageUri",
    "StorageUriError",
    "dataset_data_uri",
    "source_file_uri",
]
