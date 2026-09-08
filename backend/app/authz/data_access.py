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

from app.domain.data import Dataset
from app.domain.errors import AuthorizationError
from app.domain.ids import DatasetId, UserId
from app.domain.principal import Principal
from app.repositories.data import DatasetRepository
from app.storage.object_store import ObjectStore
from app.storage.uri import StorageUri, dataset_data_uri, source_file_uri

#: Module-private. Only :func:`open_dataset` holds it.
_GRANT: Final = object()


class DataAccessDenied(AuthorizationError):
    """Not a member, insufficient role, or no such dataset.

    One exception for all three. The API renders it as 404, never 403: a 403
    confirms the resource exists, and that confirmation is itself the leak
    (§13.3.1 L2).
    """


@dataclass(frozen=True, slots=True)
class DataHandle:
    """Proof that a principal may read one Dataset, plus the means to.

    Carrying the store rather than a bare path is what keeps callers away from
    the filesystem: everything they can do with this handle is scoped to the
    account it was opened in.
    """

    principal: Principal
    owner_id: UserId
    dataset: Dataset
    uri: StorageUri
    _store: ObjectStore = field(repr=False)
    _grant: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._grant is not _GRANT:
            raise AuthorizationError(
                "DataHandle cannot be constructed directly; use data_access.open_dataset()"
            )

    def read(self) -> bytes:
        return self._store.read(self.uri)

    def local_path(self) -> Path:
        """A real path for the analytics engine (DuckDB reads Parquet by path)."""
        return self._store.local_path(self.uri)

    def exists(self) -> bool:
        return self._store.exists(self.uri)


async def open_dataset(
    principal: Principal,
    dataset_id: DatasetId,
    *,
    connection: AsyncConnection,
    store: ObjectStore,
) -> DataHandle:
    """Authorize, then hand back the only object that can read the data.

    The lookup resolves the version and its owner in **one** query. Two queries
    would leave a gap where the version is found and the ownership check is
    skipped because someone forgot the second call — the exact mistake this
    design exists to prevent.

    A missing dataset and somebody else's dataset raise the same error, so the
    caller cannot tell them apart and neither can an attacker.

    ``required_role`` was a parameter here until D-039, defaulting to
    ``viewer``. It went with FR-A.5: there is one owner, and no lesser role for
    the argument to name. The question it guarded — *may this caller read this?*
    — is the equality below, and it is no more skippable than it was.
    """
    located = await DatasetRepository(connection).locate(dataset_id)
    if located is None:
        raise DataAccessDenied(str(dataset_id))

    record, owner_id = located
    if not principal.owns(owner_id):
        raise DataAccessDenied(str(dataset_id))

    return DataHandle(
        principal=principal,
        owner_id=owner_id,
        dataset=record,
        uri=StorageUri.parse(record.parquet_uri),
        _store=store,
        _grant=_GRANT,
    )


@dataclass(frozen=True, slots=True)
class IngestScope:
    """Permission to *write* into one account's namespace, plus the means to.

    ``DataHandle`` answers "may this principal read this dataset?". Ingest asks
    the mirror-image question — "may this principal put bytes here?" — and it
    needs its own answer, because a brand-new upload has no Dataset row to open
    yet.

    Writing deserves the same gate as reading. A bug that writes into the wrong
    tenant's namespace is a breach in the same way a bad read is, and §10.5
    leans on the path layout as a second line of defence — which only holds if
    nothing can choose a path freely. Here nothing can: every URI this hands out
    is built from the account this scope was opened for.

    The alternative was to let ``app/ingest/`` import the object store directly.
    That means widening the list in ``test_authz_boundaries.py`` to admit the
    one package whose whole job is handling untrusted uploads — the wrong
    direction for a list that exists to stay short.
    """

    principal: Principal
    owner_id: UserId
    _store: ObjectStore = field(repr=False)
    _grant: object = field(repr=False)

    def __post_init__(self) -> None:
        if self._grant is not _GRANT:
            raise AuthorizationError(
                "IngestScope cannot be constructed directly;"
                " use data_access.open_account_for_ingest()"
            )

    def data_uri(self, dataset_id: DatasetId) -> StorageUri:
        return dataset_data_uri(self.owner_id, dataset_id)

    def source_uri(
        self,
        dataset_id: DatasetId,
        source_file_id: UUID,
        suffix: str = "",
    ) -> StorageUri:
        return source_file_uri(self.owner_id, dataset_id, source_file_id, suffix)

    def writable_path(self, uri: StorageUri) -> Path:
        self._must_be_ours(uri)
        return self._store.writable_path(uri)

    def write_stream(self, uri: StorageUri, reader: BinaryIO) -> int:
        self._must_be_ours(uri)
        return self._store.write_stream(uri, reader)

    def reader_for(self, record: Dataset) -> DataHandle:
        """A read handle for a dataset this scope just wrote.

        Ingest has to read back what it wrote — schema inference scans the
        normalized Parquet (FR-B.3), and the engine takes a ``DataHandle`` and
        nothing else (§13.3.1 L3). Rather than carve an exception for the one
        caller that already has the bytes in hand, the scope mints the handle:
        it has already proved this principal may write here, and writing is the
        stronger permission of the two.

        The ownership check is not ceremony. A ``Dataset`` carries its own
        ``parquet_uri``, so without it a caller could hand over somebody else's
        dataset and receive a handle to their data.
        """
        uri = StorageUri.parse(record.parquet_uri)
        self._must_be_ours(uri)
        return DataHandle(
            principal=self.principal,
            owner_id=self.owner_id,
            dataset=record,
            uri=uri,
            _store=self._store,
            _grant=_GRANT,
        )

    def discard_dataset(self, dataset_id: DatasetId) -> None:
        """Remove everything written for one dataset (FR-B.6).

        Also the compensation for a commit that fails after the files exist:
        storage is not in the database transaction, so a rollback leaves the
        bytes behind unless something removes them — and an orphaned Parquet
        file is user data with no row to authorize access to it.

        ``discard_version`` was the second half of this until D-043, deleting
        one version's prefix. There is one prefix per dataset now.
        """
        self._store.delete_prefix(self.owner_id, f"datasets/{dataset_id}")

    def _must_be_ours(self, uri: StorageUri) -> None:
        """A URI from somewhere else is not made ours by being passed here.

        Without this the scope would authorize the *caller* and then happily
        write wherever the caller pointed — which is the check being skipped,
        just one function further along.
        """
        if uri.owner_id != self.owner_id:
            raise DataAccessDenied(
                f"refusing to write into the namespace of {uri.owner_id} from a"
                f" scope opened for {self.owner_id}"
            )


def open_account_for_ingest(
    principal: Principal,
    *,
    store: ObjectStore,
) -> IngestScope:
    """Hand back the only way to write, scoped to the caller's own account.

    This was ``open_project_for_ingest``, and it was ``async`` because it had to
    find a project and then the workspace behind it before it could decide
    anything. There is nothing to look up now: an account may write into its own
    namespace, and the caller's identity is the whole answer. No query, no
    role, no database round trip in the middle of an authorization decision.

    That reads like the check disappeared. It did not — it became trivially
    true, which is what *the account is the tenant* means. What still cannot
    happen is a caller choosing where the bytes land: every URI this scope hands
    out is built from ``principal.user_id``, and ``_must_be_ours`` rejects any
    URI that arrives from anywhere else.
    """
    return IngestScope(
        principal=principal,
        owner_id=principal.user_id,
        _store=store,
        _grant=_GRANT,
    )


__all__ = [
    "DataAccessDenied",
    "DataHandle",
    "IngestScope",
    "open_account_for_ingest",
    "open_dataset",
]
