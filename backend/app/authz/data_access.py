"""The only way to reach data (INV-7, DESIGN.md §13.3, §13.3.1 L3).

The rejected alternative was a membership check in every endpoint. That fails
because it depends on discipline: one new route that forgets, and tenant
isolation is gone. Every team that has built multi-tenant SaaS has this story.

What replaces it: a ``DataHandle`` is the only object that can read a dataset,
and ``open()`` is the only thing that can produce one. Forgetting the check is
not something you can do by accident, because there is no code path that
reaches bytes without going through here.

``DataHandle`` has no usable public constructor. Python cannot make that
literally impossible — a determined caller can reach the module-private token
below — but the point is not to stop someone who is trying. It is to make the
*accidental* path, the one a tired person writes at 6pm, fail immediately.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import DatasetVersion
from app.domain.enums import Role
from app.domain.errors import AuthorizationError
from app.domain.ids import DatasetId, DatasetVersionId, ProjectId, WorkspaceId
from app.domain.principal import Principal
from app.repositories.data import DatasetVersionRepository
from app.repositories.identity import ProjectRepository
from app.storage.object_store import ObjectStore
from app.storage.uri import StorageUri, dataset_version_data_uri, source_file_uri

#: Module-private. Only :func:`open_dataset_version` holds it.
_GRANT: Final = object()


class DataAccessDenied(AuthorizationError):
    """Not a member, insufficient role, or no such dataset.

    One exception for all three. The API renders it as 404, never 403: a 403
    confirms the resource exists, and that confirmation is itself the leak
    (§13.3.1 L2).
    """


@dataclass(frozen=True, slots=True)
class DataHandle:
    """Proof that a principal may read one DatasetVersion, plus the means to.

    Carrying the store rather than a bare path is what keeps callers away from
    the filesystem: everything they can do with this handle is scoped to the
    workspace it was opened in.
    """

    principal: Principal
    workspace_id: WorkspaceId
    version: DatasetVersion
    uri: StorageUri
    _store: ObjectStore = field(repr=False)
    _grant: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._grant is not _GRANT:
            raise AuthorizationError(
                "DataHandle cannot be constructed directly; use data_access.open_dataset_version()"
            )

    def read(self) -> bytes:
        return self._store.read(self.uri)

    def local_path(self) -> Path:
        """A real path for the analytics engine (DuckDB reads Parquet by path)."""
        return self._store.local_path(self.uri)

    def exists(self) -> bool:
        return self._store.exists(self.uri)


async def open_dataset_version(
    principal: Principal,
    version_id: DatasetVersionId,
    *,
    connection: AsyncConnection,
    store: ObjectStore,
    required_role: Role = Role.VIEWER,
) -> DataHandle:
    """Authorize, then hand back the only object that can read the data.

    The lookup resolves the version and its owning workspace in **one** query.
    Two queries would leave a gap where the version is found and the ownership
    check is skipped because someone forgot the second call — the exact mistake
    this design exists to prevent.

    A missing dataset and a dataset in someone else's workspace raise the same
    error, so the caller cannot tell them apart and neither can an attacker.
    """
    located = await DatasetVersionRepository(connection).locate(version_id)
    if located is None:
        raise DataAccessDenied(str(version_id))

    version, workspace_id = located
    role = principal.role_in(workspace_id)
    if role is None or not role.at_least(required_role):
        raise DataAccessDenied(str(version_id))

    return DataHandle(
        principal=principal,
        workspace_id=workspace_id,
        version=version,
        uri=StorageUri.parse(version.parquet_uri),
        _store=store,
        _grant=_GRANT,
    )


@dataclass(frozen=True, slots=True)
class IngestScope:
    """Permission to *write* into one workspace, plus the means to.

    ``DataHandle`` answers "may this principal read this dataset?". Ingest asks
    the mirror-image question — "may this principal put bytes into this
    workspace?" — and it needs its own answer, because a brand-new upload has no
    DatasetVersion to open yet.

    Writing deserves the same gate as reading. A bug that writes into the wrong
    workspace's namespace is a tenant breach in the same way a bad read is, and
    §10.5 leans on the path layout as a second line of defence — which only
    holds if nothing can choose a path freely. Here nothing can: every URI this
    hands out is built from the workspace this scope was opened for.

    The alternative was to let ``app/ingest/`` import the object store directly.
    That means widening the list in ``test_authz_boundaries.py`` to admit the
    one package whose whole job is handling untrusted uploads — the wrong
    direction for a list that exists to stay short.
    """

    principal: Principal
    workspace_id: WorkspaceId
    project_id: ProjectId
    _store: ObjectStore = field(repr=False)
    _grant: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._grant is not _GRANT:
            raise AuthorizationError(
                "IngestScope cannot be constructed directly;"
                " use data_access.open_project_for_ingest()"
            )

    def data_uri(self, dataset_id: DatasetId, version_id: DatasetVersionId) -> StorageUri:
        return dataset_version_data_uri(self.workspace_id, dataset_id, version_id)

    def source_uri(
        self,
        dataset_id: DatasetId,
        version_id: DatasetVersionId,
        source_file_id: UUID,
        suffix: str = "",
    ) -> StorageUri:
        return source_file_uri(self.workspace_id, dataset_id, version_id, source_file_id, suffix)

    def writable_path(self, uri: StorageUri) -> Path:
        self._must_be_ours(uri)
        return self._store.writable_path(uri)

    def write_stream(self, uri: StorageUri, reader: BinaryIO) -> int:
        self._must_be_ours(uri)
        return self._store.write_stream(uri, reader)

    def discard_version(self, dataset_id: DatasetId, version_id: DatasetVersionId) -> None:
        """Remove everything written for one version.

        The compensation for a commit that fails after the files exist. Storage
        is not in the database transaction, so a rollback leaves the bytes
        behind unless something removes them — and an orphaned Parquet file is
        user data with no row to authorize access to it.
        """
        self._store.delete_prefix(self.workspace_id, f"datasets/{dataset_id}/versions/{version_id}")

    def discard_dataset(self, dataset_id: DatasetId) -> None:
        """Remove every version's bytes for one dataset (FR-B.6)."""
        self._store.delete_prefix(self.workspace_id, f"datasets/{dataset_id}")

    def _must_be_ours(self, uri: StorageUri) -> None:
        """A URI from somewhere else is not made ours by being passed here.

        Without this the scope would authorize the *caller* and then happily
        write wherever the caller pointed — which is the check being skipped,
        just one function further along.
        """
        if uri.workspace_id != self.workspace_id:
            raise DataAccessDenied(
                f"refusing to write to workspace {uri.workspace_id} from a scope"
                f" opened for {self.workspace_id}"
            )


async def open_project_for_ingest(
    principal: Principal,
    project_id: ProjectId,
    *,
    connection: AsyncConnection,
    store: ObjectStore,
    required_role: Role = Role.EDITOR,
) -> IngestScope:
    """Authorize an upload into a project, then hand back the only way to write.

    ``editor`` by default: §13.3 says a ``viewer`` may read and run read-only
    tools but may not upload or delete. A viewer therefore gets the same error
    as a stranger, and the API renders both as 404.
    """
    located = await ProjectRepository(connection).locate(project_id)
    if located is None:
        raise DataAccessDenied(str(project_id))

    _, workspace_id = located
    role = principal.role_in(workspace_id)
    if role is None or not role.at_least(required_role):
        raise DataAccessDenied(str(project_id))

    return IngestScope(
        principal=principal,
        workspace_id=workspace_id,
        project_id=project_id,
        _store=store,
        _grant=_GRANT,
    )


__all__ = [
    "DataAccessDenied",
    "DataHandle",
    "IngestScope",
    "open_dataset_version",
    "open_project_for_ingest",
]
