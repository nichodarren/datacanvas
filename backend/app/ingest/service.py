"""Committing an upload (FR-B.2, FR-B.4, FR-B.6, §10.4 Alur 1).

This is the one place where two stores have to agree: bytes go to the object
store, rows go to Postgres, and only one of the two can be rolled back.

**The order is forced, not chosen.** INV-2 says a Dataset is complete the moment
it exists — no *pending* row filled in later, because filling it in is an UPDATE
and the trigger refuses. But ``row_count``, ``column_count`` and
``content_hash`` are only knowable *after* normalization. So the files must be
written first, and the row inserted once there is something true to insert.

That is why the row is built in one place here rather than created empty and
completed: it is the same reason the entity is one table and not two.

That leaves one honest gap, stated rather than hidden: if the process dies
between writing the Parquet and committing the transaction, the bytes survive
with no row pointing at them. :meth:`IngestScope.discard_dataset` handles every
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
from app.domain.data import Dataset, SchemaContract, SourceFile
from app.domain.enums import SourceFormat
from app.domain.ids import DatasetId, SourceFileId, UserId
from app.ingest.dialect import Dialect
from app.ingest.limits import IngestRejected, check_upload_size
from app.ingest.normalize import normalize_file
from app.repositories.audit import AuditRepository
from app.repositories.data import DatasetRepository, SourceFileRepository
from app.repositories.schema import SchemaContractRepository, first_contract
from app.schema.inference import build_columns
from app.storage.engine import TableEngine


@dataclass(frozen=True, slots=True)
class Committed:
    """What a successful upload produced."""

    dataset: Dataset
    source_file: SourceFile
    contract: SchemaContract


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
    """Turns an authorized upload into a Dataset.

    Takes an :class:`IngestScope` rather than a store, which is the whole point:
    it has no way to name a location outside the account it was handed.
    """

    def __init__(
        self, connection: AsyncConnection, *, scope: IngestScope, engine: TableEngine
    ) -> None:
        self._c = connection
        self._scope = scope
        self._engine = engine

    async def commit(
        self,
        *,
        upload: BinaryIO,
        filename: str,
        declared_size: int,
        fmt: SourceFormat,
        dialect: Dialect | None,
        dataset_name: str,
        actor: UserId,
        now: datetime,
    ) -> Committed:
        """Store the file, normalize it, and record it.

        The signature took a ``dataset_id`` until D-043, to say *add a version to
        this one*. FR-B.2 went with the versions: an upload is a dataset, and a
        re-upload is another dataset.
        """
        check_upload_size(declared_size)

        new_id = DatasetId(uuid4())
        source_file_id = SourceFileId(uuid4())

        source_uri = self._scope.source_uri(new_id, source_file_id, _suffix_of(filename))
        data_uri = self._scope.data_uri(new_id)

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

            record = Dataset(
                id=new_id,
                owner_id=self._scope.owner_id,
                name=dataset_name,
                content_hash=normalized.content_hash,
                parquet_uri=str(data_uri),
                row_count=normalized.row_count,
                column_count=normalized.column_count,
                byte_size=normalized.byte_size,
                created_at=now,
                ingest_options=self._options(fmt, dialect),
            )
            await DatasetRepository(self._c).create(record)

            source = SourceFile(
                id=source_file_id,
                dataset_id=new_id,
                original_filename=filename,
                # What we determined by parsing, not what the client claimed
                # (D-027). Storing the claim would preserve the lie.
                mime_detected=fmt.value,
                byte_size=stored_bytes,
                storage_uri=str(source_uri),
            )
            await SourceFileRepository(self._c).create(source)

            # SchemaContract v1, read back through the same authorization path
            # any later reader uses (§13.3.1 L3). Inference scans the whole file
            # (FR-B.3) — which it can only do now that the file exists, and
            # cheaply, because every column was written as text (D-029).
            contract = await SchemaContractRepository(self._c).create(
                first_contract(
                    dataset_id=new_id,
                    columns=build_columns(
                        self._engine.column_statistics(self._scope.reader_for(record))
                    ),
                    now=now,
                )
            )
        except Exception:
            # Everything written for this dataset goes, including the verbatim
            # copy. The database transaction will roll back on its own; the
            # filesystem will not, and an orphaned Parquet is user data that no
            # row can authorize access to.
            self._scope.discard_dataset(new_id)
            raise

        await AuditRepository(self._c).record(
            action=AuditAction.DATASET_CREATED,
            now=now,
            actor_user_id=actor,
            target_type="dataset",
            target_id=new_id,
            # §13.7.1: ids, counts and a hash. No filename, no column names —
            # column names are sensitive (K1) and this table cannot be deleted.
            metadata={
                "row_count": record.row_count,
                "column_count": record.column_count,
                "content_hash": record.content_hash,
                "format": fmt.value,
            },
        )

        return Committed(dataset=record, source_file=source, contract=contract)

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
            actor_user_id=actor,
            target_type="dataset",
            target_id=dataset_id,
        )

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


__all__ = ["Committed", "IngestService"]
