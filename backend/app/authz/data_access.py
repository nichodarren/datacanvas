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
from typing import Final

from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import DatasetVersion
from app.domain.enums import Role
from app.domain.errors import AuthorizationError
from app.domain.ids import DatasetVersionId, WorkspaceId
from app.domain.principal import Principal
from app.repositories.data import DatasetVersionRepository
from app.storage.object_store import ObjectStore
from app.storage.uri import StorageUri

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


__all__ = ["DataAccessDenied", "DataHandle", "open_dataset_version"]
