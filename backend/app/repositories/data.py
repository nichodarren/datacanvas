"""Dataset repositories.

Phase 1 needed only enough of these for ``data_access.open()`` to have something
to open and to answer one question: *who owns this data?* Phase 2 added
ingestion, which — as predicted — extended this module rather than reshaping it.

That question used to be answered by joining through ``project`` to
``workspace``. D-039 put ``owner_id`` on ``dataset``, so ``locate`` lost its
joins. It kept its shape on purpose: returning the row *and* its owner together
is what stops a caller finding one without checking the other, and that property
is independent of how deep the chain is.

``DatasetVersionRepository`` was here until D-043, with a ``locate`` of its own
that this one now does. One entity, one repository — and one fewer place where a
row could be found without the check that says whose it is.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import Dataset, SourceFile
from app.domain.ids import DatasetId, SourceFileId, UserId
from app.repositories.tables import dataset, schema_contract, source_file


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    """What a dataset card needs, without opening the dataset.

    ``columns_needing_attention`` used to be here — a count of columns whose
    detection confidence fell below 0.8, computed by walking the contract's
    column JSON on every listing. It went when the grid stopped marking those
    columns: a count with nothing to point at is a warning the user cannot act
    on, and the work to produce it was being done for a badge nobody would see.

    ``detection_confidence`` is still on every contract (D-029). This removed a
    derived field, not a fact.
    """

    dataset: Dataset
    schema_version_no: int | None


def _to_dataset(row: Row[tuple[object, ...]]) -> Dataset:
    return Dataset(
        id=DatasetId(row.id),
        owner_id=UserId(row.owner_id),
        name=row.name,
        content_hash=row.content_hash,
        parquet_uri=row.parquet_uri,
        row_count=row.row_count,
        column_count=row.column_count,
        byte_size=row.byte_size,
        created_at=row.created_at,
        ingest_options=row.ingest_options,
    )


class DatasetRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, record: Dataset) -> Dataset:
        """Takes a fully built domain object.

        INV-2 says a Dataset never changes after commit, so there is no such
        thing as a partially built one to fill in later. The signature says so
        too — this took keyword arguments and returned a row with no data on it
        until D-043, which is exactly the shape that made a second table
        necessary.
        """
        await self._c.execute(
            sa.insert(dataset).values(
                id=record.id,
                owner_id=record.owner_id,
                name=record.name,
                content_hash=record.content_hash,
                parquet_uri=record.parquet_uri,
                row_count=record.row_count,
                column_count=record.column_count,
                byte_size=record.byte_size,
                created_at=record.created_at,
                ingest_options=dict(record.ingest_options),
            )
        )
        return record

    async def get(self, dataset_id: DatasetId) -> Dataset | None:
        row = (
            await self._c.execute(sa.select(dataset).where(dataset.c.id == dataset_id))
        ).one_or_none()
        return _to_dataset(row) if row else None

    async def locate(self, dataset_id: DatasetId) -> tuple[Dataset, UserId] | None:
        """The dataset and its owner, in one query.

        This is the query authorization is built on. Two queries would open a
        window where the row is found and the ownership check is skipped because
        someone forgot the second call — precisely the class of mistake §13.3
        exists to make impossible.

        The owner is a column on the row now rather than something two joins
        away, so this returns a pair whose halves come from the same tuple. That
        makes the guarantee stronger, not weaker: there is no arrangement of
        this query that can return a dataset without its owner.
        """
        row = (
            await self._c.execute(sa.select(dataset).where(dataset.c.id == dataset_id))
        ).one_or_none()
        if row is None:
            return None
        return _to_dataset(row), UserId(row.owner_id)

    async def list_for_owner(self, owner_id: UserId) -> list[Dataset]:
        rows = await self._c.execute(
            sa.select(dataset)
            .where(dataset.c.owner_id == owner_id)
            .order_by(dataset.c.created_at, dataset.c.id)
        )
        return [_to_dataset(row) for row in rows]

    async def summaries_for_owner(self, owner_id: UserId) -> list[DatasetSummary]:
        """Enough about each dataset to decide whether to open it.

        Two queries where there were four. Counting versions and finding the
        latest one were half of this method until D-043, and both questions
        stopped existing rather than getting faster: a dataset *is* its data now.
        """
        datasets = await self.list_for_owner(owner_id)
        if not datasets:
            return []

        # The newest contract for each dataset. DISTINCT ON is Postgres-specific,
        # and §10.3 allows leaning on Postgres beyond JSONB only where the
        # alternative is materially worse — a window function here would be.
        contracts = {
            row.dataset_id: row
            for row in await self._c.execute(
                sa.select(schema_contract)
                .where(schema_contract.c.dataset_id.in_([item.id for item in datasets]))
                .distinct(schema_contract.c.dataset_id)
                .order_by(schema_contract.c.dataset_id, schema_contract.c.version_no.desc())
            )
        }

        return [
            DatasetSummary(
                dataset=item,
                schema_version_no=(
                    None if item.id not in contracts else contracts[item.id].version_no
                ),
            )
            for item in datasets
        ]

    async def delete(self, dataset_id: DatasetId) -> int:
        """Really delete it (FR-B.6).

        Source files and contracts go with it by ``ON DELETE CASCADE``. The
        audit trail survives, because it deliberately holds no foreign keys
        (D-023) — deletion of data is not deletion of the record that it existed.
        """
        result = await self._c.execute(sa.delete(dataset).where(dataset.c.id == dataset_id))
        return result.rowcount


class SourceFileRepository:
    """The uploaded file, kept verbatim for audit and re-parse (§9.2)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, file: SourceFile) -> SourceFile:
        await self._c.execute(
            sa.insert(source_file).values(
                id=file.id,
                dataset_id=file.dataset_id,
                original_filename=file.original_filename,
                mime_detected=file.mime_detected,
                byte_size=file.byte_size,
                storage_uri=file.storage_uri,
            )
        )
        return file

    async def for_version(self, dataset_id: DatasetId) -> SourceFile | None:
        row = (
            await self._c.execute(
                sa.select(source_file).where(source_file.c.dataset_id == dataset_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return SourceFile(
            id=SourceFileId(row.id),
            dataset_id=DatasetId(row.dataset_id),
            original_filename=row.original_filename,
            mime_detected=row.mime_detected,
            byte_size=row.byte_size,
            storage_uri=row.storage_uri,
        )


__all__ = [
    "DatasetRepository",
    "DatasetSummary",
    "SourceFileRepository",
]
