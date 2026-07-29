"""Committing an upload (FR-B.2, FR-B.4, FR-B.6, §10.4 Alur 1).

This is the one place where two stores have to agree: bytes go to the object
store, rows go to Postgres, and only one of the two can be rolled back.

**The order is forced, not chosen.** INV-2 says a DatasetVersion is complete the
moment it exists — no *pending* row filled in later, because filling it in is an
UPDATE and the trigger refuses. But ``row_count``, ``column_count`` and
``content_hash`` are only knowable *after* normalization. So the files must be
written first, and the row inserted once there is something true to insert.

That leaves one honest gap, stated rather than hidden: if the process dies
between writing the Parquet and committing the transaction, the bytes survive
with no row pointing at them. :meth:`IngestScope.discard_version` handles every
failure this code can see; it cannot handle a power cut. Orphans are therefore a
known debt, and the sweep that collects them belongs with the retention policy
(NFR-SCALE.3), not here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import BinaryIO
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncConnection

from app.authz.data_access import IngestScope
from app.domain.audit import AuditAction
from app.domain.data import Dataset, DatasetVersion, SourceFile
from app.domain.enums import SourceFormat
from app.domain.ids import DatasetId, DatasetVersionId, SourceFileId, UserId
from app.ingest.dialect import Dialect
from app.ingest.limits import IngestRejected, check_upload_size
from app.ingest.normalize import normalize_file
from app.repositories.audit import AuditRepository
from app.repositories.data import (
    DatasetRepository,
    DatasetVersionRepository,
    SourceFileRepository,
)


@dataclass(frozen=True, slots=True)
class CommittedVersion:
    """What a successful upload produced."""

    dataset: Dataset
    version: DatasetVersion
    source_file: SourceFile
    columns: tuple[str, ...]


def _suffix_of(filename: str) -> str:
    """The extension, for the stored copy's name only.

    Never part of a directory path (§13.6): the file is stored under a UUID, and
    this only decides what comes after the dot. ``StorageUri`` rejects anything
    that is not alphanumeric, so a filename cannot smuggle a separator through.
    """
    if "." not in filename:
        return ""
    candidate = filename.rsplit(".", 1)[-1].strip().lower()
    return candidate if candidate.isalnum() and len(candidate) <= 12 else ""


class IngestService:
    """Turns an authorized upload into a DatasetVersion.

    Takes an :class:`IngestScope` rather than a store, which is the whole point:
    it has no way to name a location outside the workspace it was handed.
    """

    def __init__(self, connection: AsyncConnection, *, scope: IngestScope) -> None:
        self._c = connection
        self._scope = scope

    async def commit(
        self,
        *,
        upload: BinaryIO,
        filename: str,
        declared_size: int,
        fmt: SourceFormat,
        dialect: Dialect | None,
        dataset_id: DatasetId | None,
        dataset_name: str,
        actor: UserId,
        now: datetime,
    ) -> CommittedVersion:
        """Store the file, normalize it, and record the version.

        ``dataset_id`` decides which of the two FR-B requirements applies:
        ``None`` creates a new Dataset at version 1, and an existing id adds a
        version to it (FR-B.2 — a re-upload never overwrites).
        """
        check_upload_size(declared_size)

        target = await self._resolve_dataset(dataset_id, dataset_name, now)
        version_id = DatasetVersionId(uuid4())
        source_file_id = SourceFileId(uuid4())

        source_uri = self._scope.source_uri(
            target.id, version_id, source_file_id, _suffix_of(filename)
        )
        data_uri = self._scope.data_uri(target.id, version_id)

        try:
            # The original is kept verbatim (§9.2) *before* anything is parsed.
            # If normalization then fails, we still have exactly what the user
            # sent — which is what makes "re-parse with corrected options"
            # possible instead of "upload it again".
            stored_bytes = self._scope.write_stream(source_uri, upload)
            source_path = self._scope.writable_path(source_uri)

            normalized = normalize_file(
                source_path, fmt, self._scope.writable_path(data_uri), dialect
            )

            version = DatasetVersion(
                id=version_id,
                dataset_id=target.id,
                version_no=await DatasetVersionRepository(self._c).next_version_no(target.id),
                content_hash=normalized.content_hash,
                parquet_uri=str(data_uri),
                row_count=normalized.row_count,
                column_count=normalized.column_count,
                byte_size=normalized.byte_size,
                ingested_at=now,
                ingested_by=actor,
                ingest_options=self._options(fmt, dialect),
            )
            await DatasetVersionRepository(self._c).create(version)

            source = SourceFile(
                id=source_file_id,
                dataset_version_id=version_id,
                original_filename=filename,
                # What we determined by parsing, not what the client claimed
                # (D-027). Storing the claim would preserve the lie.
                mime_detected=fmt.value,
                byte_size=stored_bytes,
                storage_uri=str(source_uri),
            )
            await SourceFileRepository(self._c).create(source)
        except Exception:
            # Everything written for this version goes, including the verbatim
            # copy. The database transaction will roll back on its own; the
            # filesystem will not, and an orphaned Parquet is user data that no
            # row can authorize access to.
            self._scope.discard_version(target.id, version_id)
            raise

        await AuditRepository(self._c).record(
            action=AuditAction.DATASET_VERSION_CREATED,
            now=now,
            workspace_id=self._scope.workspace_id,
            actor_user_id=actor,
            target_type="dataset_version",
            target_id=version_id,
            # §13.7.1: ids, counts and a hash. No filename, no column names —
            # column names are sensitive (K1) and this table cannot be deleted.
            metadata={
                "dataset_id": str(target.id),
                "version_no": version.version_no,
                "row_count": version.row_count,
                "column_count": version.column_count,
                "content_hash": version.content_hash,
                "format": fmt.value,
            },
        )

        return CommittedVersion(
            dataset=target,
            version=version,
            source_file=source,
            columns=normalized.columns,
        )

    async def delete_dataset(self, dataset_id: DatasetId, *, actor: UserId, now: datetime) -> None:
        """FR-B.6 — the files really go, not just the rows.

        Bytes first. If the row were deleted first and the unlink then failed,
        the result would be data on disk that nothing knows about and nothing
        will ever collect. This way a failure leaves rows pointing at missing
        files, which is visible (``data_present: false``) and repairable.
        """
        self._scope.discard_dataset(dataset_id)
        removed = await DatasetRepository(self._c).delete(dataset_id)
        if removed == 0:
            raise IngestRejected("no such dataset")

        await AuditRepository(self._c).record(
            action=AuditAction.DATASET_DELETED,
            now=now,
            workspace_id=self._scope.workspace_id,
            actor_user_id=actor,
            target_type="dataset",
            target_id=dataset_id,
        )

    async def _resolve_dataset(
        self, dataset_id: DatasetId | None, name: str, now: datetime
    ) -> Dataset:
        if dataset_id is None:
            created = await DatasetRepository(self._c).create(
                project_id=self._scope.project_id, name=name, now=now
            )
            await AuditRepository(self._c).record(
                action=AuditAction.DATASET_CREATED,
                now=now,
                workspace_id=self._scope.workspace_id,
                actor_user_id=self._scope.principal.user_id,
                target_type="dataset",
                target_id=created.id,
            )
            return created

        located = await DatasetRepository(self._c).locate(dataset_id)
        # The workspace check is not redundant with the scope: the scope proves
        # the caller may write *here*, and this proves the dataset they named
        # actually lives here. Without it, a member of one workspace could add a
        # version to another workspace's dataset by naming its id.
        if located is None or located[1] != self._scope.workspace_id:
            raise IngestRejected("no such dataset")
        return located[0]

    @staticmethod
    def _options(fmt: SourceFormat, dialect: Dialect | None) -> dict[str, object]:
        """What ``ingest_options`` records (§9.2) — part of reproducibility.

        Without the dialect written down, re-reading the source file later is a
        fresh guess rather than a repeat.
        """
        options: dict[str, object] = {"format": fmt.value}
        if dialect is not None:
            options.update(dialect.as_options())
        return options


__all__ = ["CommittedVersion", "IngestService"]
