"""Dataset repositories.

Phase 1 needed only enough of these for ``data_access.open()`` to have something
to open and to answer one question: *which workspace does this DatasetVersion
belong to?* Phase 2 adds ingestion, which — as predicted — extended this module
rather than reshaping it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import Dataset, DatasetVersion, SourceFile
from app.domain.ids import (
    DatasetId,
    DatasetVersionId,
    ProjectId,
    SourceFileId,
    UserId,
    WorkspaceId,
)
from app.repositories.tables import (
    dataset,
    dataset_version,
    project,
    schema_contract,
    source_file,
)

#: A column the detector was not confident about. The same bar the grid uses to
#: decide whether to show a "check" badge, kept in one place so the card and the
#: header cannot disagree about which columns are worth a second look.
UNSURE_CONFIDENCE = 0.8


@dataclass(frozen=True, slots=True)
class DatasetSummary:
    """What a dataset card needs, without opening the dataset."""

    dataset: Dataset
    version_count: int
    latest_version: DatasetVersion | None
    schema_version_no: int | None
    columns_needing_attention: int


def _unsure_columns(contract_row: Row[tuple[Any, ...]] | None) -> int:
    """Count columns the detector flagged, ignoring ones a human has settled.

    An overridden column is a decision, not a guess — surfacing it as needing
    attention would mean the badge never goes away no matter what the user does,
    which is how a warning becomes wallpaper.
    """
    if contract_row is None:
        return 0
    return sum(
        1
        for column in contract_row.columns
        if column.get("overridden_by") is None
        and column.get("detection_confidence", 1.0) < UNSURE_CONFIDENCE
    )


def _to_dataset(row: Row[tuple[object, ...]]) -> Dataset:
    return Dataset(
        id=DatasetId(row.id),
        project_id=ProjectId(row.project_id),
        name=row.name,
        created_at=row.created_at,
    )


def _to_version(row: Row[tuple[object, ...]]) -> DatasetVersion:
    return DatasetVersion(
        id=DatasetVersionId(row.id),
        dataset_id=DatasetId(row.dataset_id),
        version_no=row.version_no,
        content_hash=row.content_hash,
        parquet_uri=row.parquet_uri,
        row_count=row.row_count,
        column_count=row.column_count,
        byte_size=row.byte_size,
        ingested_at=row.ingested_at,
        ingested_by=UserId(row.ingested_by),
        ingest_options=row.ingest_options,
    )


class DatasetRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, *, project_id: ProjectId, name: str, now: datetime) -> Dataset:
        created = Dataset(
            id=DatasetId(uuid.uuid4()), project_id=project_id, name=name, created_at=now
        )
        await self._c.execute(
            sa.insert(dataset).values(
                id=created.id,
                project_id=created.project_id,
                name=created.name,
                created_at=created.created_at,
            )
        )
        return created

    async def get(self, dataset_id: DatasetId) -> Dataset | None:
        row = (
            await self._c.execute(sa.select(dataset).where(dataset.c.id == dataset_id))
        ).one_or_none()
        return _to_dataset(row) if row else None

    async def locate(self, dataset_id: DatasetId) -> tuple[Dataset, WorkspaceId] | None:
        """The dataset and its owning workspace, in one query.

        Same reasoning as :meth:`DatasetVersionRepository.locate`: two queries
        leave a window where the row is found and the ownership check is
        forgotten. A dataset has no ``DataHandle`` of its own — it holds no
        bytes — so this is what routes that address one by id must go through.
        """
        row = (
            await self._c.execute(
                sa.select(dataset, project.c.workspace_id)
                .join(project, project.c.id == dataset.c.project_id)
                .where(dataset.c.id == dataset_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return _to_dataset(row), WorkspaceId(row.workspace_id)

    async def list_for_project(self, project_id: ProjectId) -> list[Dataset]:
        rows = await self._c.execute(
            sa.select(dataset)
            .where(dataset.c.project_id == project_id)
            .order_by(dataset.c.created_at, dataset.c.id)
        )
        return [_to_dataset(row) for row in rows]

    async def summaries_for_project(self, project_id: ProjectId) -> list[DatasetSummary]:
        """Enough about each dataset to decide whether to open it.

        A list of names is a dead end: it tells someone what they uploaded and
        nothing about which one needs attention. Shape, version and the count of
        columns the detector was unsure about are what turn a list into a
        starting point — and that last number is the whole reason FR-C.6 exists.

        Three queries, not one per dataset. The join could be one statement with
        lateral subqueries; it would be shorter to run and considerably harder
        to read, and the number of datasets in a project is small enough that
        the difference is not worth the opacity (D-021 prefers explicit SQL).
        """
        datasets = await self.list_for_project(project_id)
        if not datasets:
            return []

        ids = [item.id for item in datasets]

        # The newest version of each dataset. DISTINCT ON is Postgres-specific,
        # and §10.3 allows leaning on Postgres beyond JSONB only where the
        # alternative is materially worse — a window function here would be.
        latest = {
            row.dataset_id: row
            for row in await self._c.execute(
                sa.select(dataset_version)
                .where(dataset_version.c.dataset_id.in_(ids))
                .distinct(dataset_version.c.dataset_id)
                .order_by(dataset_version.c.dataset_id, dataset_version.c.version_no.desc())
            )
        }
        counts = {
            row.dataset_id: row.n
            for row in await self._c.execute(
                sa.select(dataset_version.c.dataset_id, sa.func.count().label("n"))
                .where(dataset_version.c.dataset_id.in_(ids))
                .group_by(dataset_version.c.dataset_id)
            )
        }

        version_ids = [row.id for row in latest.values()]
        contracts = {
            row.dataset_version_id: row
            for row in await self._c.execute(
                sa.select(schema_contract)
                .where(schema_contract.c.dataset_version_id.in_(version_ids))
                .distinct(schema_contract.c.dataset_version_id)
                .order_by(
                    schema_contract.c.dataset_version_id,
                    schema_contract.c.version_no.desc(),
                )
            )
        }

        summaries: list[DatasetSummary] = []
        for item in datasets:
            version_row = latest.get(item.id)
            contract_row = None if version_row is None else contracts.get(version_row.id)
            summaries.append(
                DatasetSummary(
                    dataset=item,
                    version_count=int(counts.get(item.id, 0)),
                    latest_version=None if version_row is None else _to_version(version_row),
                    schema_version_no=None if contract_row is None else contract_row.version_no,
                    columns_needing_attention=_unsure_columns(contract_row),
                )
            )
        return summaries

    async def delete(self, dataset_id: DatasetId) -> int:
        """Really delete it (FR-B.6).

        Versions and source files go with it by ``ON DELETE CASCADE``. The
        audit trail survives, because it deliberately holds no foreign keys
        (D-023) — deletion of data is not deletion of the record that it existed.
        """
        result = await self._c.execute(sa.delete(dataset).where(dataset.c.id == dataset_id))
        return result.rowcount


class DatasetVersionRepository:
    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, version: DatasetVersion) -> DatasetVersion:
        """Takes a fully built domain object.

        INV-2 says a DatasetVersion never changes after commit, so there is no
        such thing as a partially built one to fill in later. The signature says
        so too.
        """
        await self._c.execute(
            sa.insert(dataset_version).values(
                id=version.id,
                dataset_id=version.dataset_id,
                version_no=version.version_no,
                content_hash=version.content_hash,
                parquet_uri=version.parquet_uri,
                row_count=version.row_count,
                column_count=version.column_count,
                byte_size=version.byte_size,
                ingested_at=version.ingested_at,
                ingested_by=version.ingested_by,
                ingest_options=dict(version.ingest_options),
            )
        )
        return version

    async def get(self, version_id: DatasetVersionId) -> DatasetVersion | None:
        row = (
            await self._c.execute(
                sa.select(dataset_version).where(dataset_version.c.id == version_id)
            )
        ).one_or_none()
        return _to_version(row) if row else None

    async def locate(
        self, version_id: DatasetVersionId
    ) -> tuple[DatasetVersion, WorkspaceId] | None:
        """The version and the workspace that owns it, in one query.

        This is the query authorization is built on. Two queries would open a
        window where the version is found and the workspace check is skipped
        because someone forgot the second call — precisely the class of mistake
        §13.3 exists to make impossible.
        """
        row = (
            await self._c.execute(
                sa.select(dataset_version, project.c.workspace_id)
                .join(dataset, dataset.c.id == dataset_version.c.dataset_id)
                .join(project, project.c.id == dataset.c.project_id)
                .where(dataset_version.c.id == version_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return _to_version(row), WorkspaceId(row.workspace_id)

    async def next_version_no(self, dataset_id: DatasetId) -> int:
        """The number the next upload to this dataset gets (FR-B.2).

        Racy on its own, and intentionally left that way: the real guarantee is
        the ``(dataset_id, version_no)`` unique constraint. Two simultaneous
        uploads make one of them fail on that constraint, which is correct —
        far better than a serialisable transaction that costs every upload, or
        a lock held across a multi-second file write.
        """
        current = (
            await self._c.execute(
                sa.select(sa.func.max(dataset_version.c.version_no)).where(
                    dataset_version.c.dataset_id == dataset_id
                )
            )
        ).scalar()
        return int(current or 0) + 1

    async def list_for_dataset(self, dataset_id: DatasetId) -> list[DatasetVersion]:
        rows = await self._c.execute(
            sa.select(dataset_version)
            .where(dataset_version.c.dataset_id == dataset_id)
            .order_by(dataset_version.c.version_no)
        )
        return [_to_version(row) for row in rows]


class SourceFileRepository:
    """The uploaded file, kept verbatim for audit and re-parse (§9.2)."""

    def __init__(self, connection: AsyncConnection) -> None:
        self._c = connection

    async def create(self, file: SourceFile) -> SourceFile:
        await self._c.execute(
            sa.insert(source_file).values(
                id=file.id,
                dataset_version_id=file.dataset_version_id,
                original_filename=file.original_filename,
                mime_detected=file.mime_detected,
                byte_size=file.byte_size,
                storage_uri=file.storage_uri,
            )
        )
        return file

    async def for_version(self, version_id: DatasetVersionId) -> SourceFile | None:
        row = (
            await self._c.execute(
                sa.select(source_file).where(source_file.c.dataset_version_id == version_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return SourceFile(
            id=SourceFileId(row.id),
            dataset_version_id=DatasetVersionId(row.dataset_version_id),
            original_filename=row.original_filename,
            mime_detected=row.mime_detected,
            byte_size=row.byte_size,
            storage_uri=row.storage_uri,
        )


__all__ = [
    "UNSURE_CONFIDENCE",
    "DatasetRepository",
    "DatasetSummary",
    "DatasetVersionRepository",
    "SourceFileRepository",
]
