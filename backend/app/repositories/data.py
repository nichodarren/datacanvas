"""Dataset repositories.

Phase 1 only needs enough of these for ``data_access.open()`` to have something
to open and to answer one question: *which workspace does this
DatasetVersion belong to?* Ingestion arrives in Phase 2 and will extend, not
reshape, what is here.
"""

from __future__ import annotations

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.engine import Row
from sqlalchemy.ext.asyncio import AsyncConnection

from app.domain.data import Dataset, DatasetVersion
from app.domain.ids import DatasetId, DatasetVersionId, ProjectId, UserId, WorkspaceId
from app.repositories.tables import dataset, dataset_version, project


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


__all__ = ["DatasetRepository", "DatasetVersionRepository"]
