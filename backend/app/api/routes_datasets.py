"""Upload, preview and dataset routes (FR-B.1..B.4, FR-B.6, §10.4 Alur 1).

Two shapes of route live here, and the difference is the whole of D-025.

``POST /uploads/preview`` is **authenticated but not tenant-scoped**: it reads a
prefix, says how it would be parsed, and keeps nothing. There is no resource to
scope it to, because nothing is stored.

Everything else is tenant-scoped and goes through
``data_access.open_project_for_ingest``, which is to writing what
``open_dataset_version`` is to reading. Neither route below picks a storage path
itself — the scope mints every URI from the workspace it was opened for, so a
handler cannot write outside its tenant even by mistake.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import Connection, CurrentPrincipal, Engine, Store
from app.api.schemas import (
    ColumnSpecResponse,
    DatasetResponse,
    DatasetVersionResponse,
    DatasetWithVersionResponse,
    DialectResponse,
    IngestPreviewResponse,
    RowPageResponse,
    SchemaContractResponse,
    SchemaOverrideRequest,
)
from app.authz.data_access import (
    DataAccessDenied,
    IngestScope,
    open_dataset_version,
    open_project_for_ingest,
)
from app.clock import system_clock
from app.domain.audit import AuditAction
from app.domain.data import Dataset, DatasetVersion, SchemaContract
from app.domain.enums import ColumnRole, LogicalType, Role, SourceFormat
from app.domain.ids import DatasetId, DatasetVersionId, ProjectId, WorkspaceId
from app.domain.principal import Principal
from app.ingest import formats, preview
from app.ingest.dialect import Dialect, detect
from app.ingest.limits import PREVIEW_BYTES, IngestRejected
from app.ingest.service import IngestService
from app.repositories.audit import AuditRepository
from app.repositories.data import DatasetRepository
from app.repositories.schema import SchemaContractRepository
from app.schema import override
from app.schema.override import SchemaOverrideRejected
from app.storage.engine import EngineError, TableEngine
from app.storage.object_store import ObjectStore

router = APIRouter(tags=["datasets"])

NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

#: Parquet closes with the same four bytes it opens with. Reading the last few
#: lets a truncated upload be named as truncated instead of failing later as
#: "unreadable", which sends the user looking in the wrong place.
_TAIL_BYTES = 8


def _rejected(exc: IngestRejected) -> HTTPException:
    """422, with the reason.

    Ingest failures are the user's to act on (P6, NFR-REL.2), so the message
    goes back. It never contains data — only what was wrong with the shape of
    the file and what to try instead.
    """
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


async def _scope(
    principal: Principal,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    connection: Connection,
    store: ObjectStore,
) -> IngestScope:
    """Authorize, and confirm the path is not lying about where it points."""
    try:
        scope = await open_project_for_ingest(
            principal, ProjectId(project_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc
    if scope.workspace_id != WorkspaceId(workspace_id):
        raise NOT_FOUND
    return scope


def _dialect_from_form(
    delimiter: str | None, encoding: str | None, has_header: bool | None, detected: Dialect | None
) -> Dialect | None:
    """The user's corrections win over detection (FR-B.3).

    Fields are merged rather than all-or-nothing: correcting only the delimiter
    should not silently reset the encoding to a default. Anything the client
    does not mention keeps the detected value.
    """
    if detected is None:
        return None
    return Dialect(
        delimiter=delimiter if delimiter else detected.delimiter,
        encoding=encoding if encoding else detected.encoding,
        has_header=detected.has_header if has_header is None else has_header,
        # A user-supplied dialect is a statement, not a guess.
        confidence=1.0
        if (delimiter or encoding or has_header is not None)
        else detected.confidence,
    )


async def _inspect(upload: UploadFile) -> tuple[SourceFormat, Dialect | None]:
    """Work out format and dialect from the head of the upload, then rewind.

    Reading the head is enough for both, and rewinding leaves the stream ready
    to be copied verbatim — so the file is still streamed, not buffered, on the
    way to storage.
    """
    head = await upload.read(PREVIEW_BYTES)
    size = upload.size or len(head)
    tail: bytes | None = None
    if size > _TAIL_BYTES:
        await upload.seek(max(0, size - _TAIL_BYTES))
        tail = await upload.read(_TAIL_BYTES)
    await upload.seek(0)

    fmt = formats.sniff(head, filename=upload.filename, tail=tail)
    detected = detect(head, is_prefix=size > len(head)) if fmt.is_delimited_text else None
    return fmt, detected


def _version_response(version: DatasetVersion, *, data_present: bool) -> DatasetVersionResponse:
    return DatasetVersionResponse(
        id=version.id,
        dataset_id=version.dataset_id,
        version_no=version.version_no,
        content_hash=version.content_hash,
        row_count=version.row_count,
        column_count=version.column_count,
        byte_size=version.byte_size,
        ingested_at=version.ingested_at,
        data_present=data_present,
    )


def _contract_response(contract: SchemaContract) -> SchemaContractResponse:
    return SchemaContractResponse(
        id=contract.id,
        dataset_version_id=contract.dataset_version_id,
        version_no=contract.version_no,
        created_at=contract.created_at,
        derived_from=contract.derived_from,
        columns=[
            ColumnSpecResponse(
                name=column.name,
                ordinal=column.ordinal,
                physical_type=column.physical_type,
                logical_type=column.logical_type.value,
                role=None if column.role is None else column.role.value,
                null_markers=list(column.null_markers),
                detection_confidence=column.detection_confidence,
                detection_reason=column.detection_reason,
                overridden=column.is_user_overridden,
            )
            for column in sorted(contract.columns, key=lambda c: c.ordinal)
        ],
    )


def _dataset_response(item: Dataset) -> DatasetResponse:
    return DatasetResponse(
        id=item.id, project_id=item.project_id, name=item.name, created_at=item.created_at
    )


@router.post("/uploads/preview")
async def preview_upload(
    principal: CurrentPrincipal,
    file: Annotated[UploadFile, File()],
) -> IngestPreviewResponse:
    """Say how this file would be parsed. Store nothing (D-025).

    Authenticated but not tenant-scoped, and that is not an oversight: there is
    no resource here to belong to anyone. The caller sends bytes and gets back a
    reading of those same bytes. Nothing is written, nothing is recorded, and
    nothing can be fetched afterwards.

    The client is expected to send only the first megabyte. More is truncated
    rather than refused — sending too much is the client's mistake, not the
    user's, and failing the upload over it would be a poor trade.
    """
    del principal  # required for authentication only; nothing here is per-user
    head = await file.read(PREVIEW_BYTES)
    try:
        result = preview.build(head, filename=file.filename, declared_size=file.size)
    except IngestRejected as exc:
        raise _rejected(exc) from exc

    return IngestPreviewResponse(
        format=result.format.value,
        dialect=(
            None
            if result.dialect is None
            else DialectResponse(
                delimiter=result.dialect.delimiter,
                encoding=result.dialect.encoding,
                has_header=result.dialect.has_header,
                confidence=result.dialect.confidence,
            )
        ),
        columns=list(result.columns),
        sample_rows=[list(row) for row in result.sample_rows],
        partial=result.partial,
        warnings=list(result.warnings),
    )


@router.get("/workspaces/{workspace_id}/projects/{project_id}/datasets")
async def list_datasets(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> list[DatasetResponse]:
    scope = await _scope(principal, workspace_id, project_id, connection, store)
    items = await DatasetRepository(connection).list_for_project(scope.project_id)
    return [_dataset_response(item) for item in items]


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/datasets",
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    delimiter: Annotated[str | None, Form()] = None,
    encoding: Annotated[str | None, Form()] = None,
    has_header: Annotated[bool | None, Form()] = None,
) -> DatasetWithVersionResponse:
    """Commit an upload as a new Dataset at version 1 (FR-B.1..B.4)."""
    scope = await _scope(principal, workspace_id, project_id, connection, store)
    return await _commit(
        scope=scope,
        connection=connection,
        engine=engine,
        principal=principal,
        file=file,
        dataset_id=None,
        name=name,
        delimiter=delimiter,
        encoding=encoding,
        has_header=has_header,
    )


@router.post(
    "/workspaces/{workspace_id}/projects/{project_id}/datasets/{dataset_id}/versions",
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset_version(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    file: Annotated[UploadFile, File()],
    delimiter: Annotated[str | None, Form()] = None,
    encoding: Annotated[str | None, Form()] = None,
    has_header: Annotated[bool | None, Form()] = None,
) -> DatasetWithVersionResponse:
    """Add a version to an existing Dataset (FR-B.2).

    Never an overwrite. The previous version keeps its bytes, its rows and its
    id — which is what makes an analysis bound to it (§9.2) still mean what it
    meant when it ran.
    """
    scope = await _scope(principal, workspace_id, project_id, connection, store)
    return await _commit(
        scope=scope,
        connection=connection,
        engine=engine,
        principal=principal,
        file=file,
        dataset_id=DatasetId(dataset_id),
        name=None,
        delimiter=delimiter,
        encoding=encoding,
        has_header=has_header,
    )


@router.get("/workspaces/{workspace_id}/dataset-versions/{version_id}/schema")
async def get_schema_contract(
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> SchemaContractResponse:
    """The current interpretation of a DatasetVersion (FR-C.1, FR-C.3).

    Goes through ``open_dataset_version`` rather than checking membership here.
    A schema describes data — column names are already sensitive on their own
    (K1, §13.5.1) — so it is guarded by exactly what guards the data.
    """
    try:
        handle = await open_dataset_version(
            principal, DatasetVersionId(version_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc
    if handle.workspace_id != WorkspaceId(workspace_id):
        raise NOT_FOUND

    contract = await SchemaContractRepository(connection).latest_for_version(
        DatasetVersionId(version_id)
    )
    if contract is None:
        raise NOT_FOUND
    return _contract_response(contract)


@router.get("/workspaces/{workspace_id}/dataset-versions/{version_id}/rows")
async def get_rows(
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    offset: int = 0,
    limit: int = 100,
) -> RowPageResponse:
    """Server-side pagination for the preview grid (FR-D.1, FR-D.2).

    The whole point of FR-D.1 is that a million-row dataset never reaches the
    browser. The cap lives in the engine (``MAX_PAGE_SIZE``) rather than here,
    so it holds for every caller and not only for this route.

    Row order is file order and is stable across requests — see
    ``DuckDBEngine.page``. Without that, paging forward would show rows twice
    and skip others, silently.
    """
    try:
        handle = await open_dataset_version(
            principal, DatasetVersionId(version_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc
    if handle.workspace_id != WorkspaceId(workspace_id):
        raise NOT_FOUND
    if not handle.exists():
        # The row outlived its bytes. Saying so beats a 500 (P6), and the grid
        # can show it rather than spinning forever.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the data for this version is no longer present in storage",
        )

    try:
        page = engine.page(handle, offset=offset, limit=limit)
    except EngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return RowPageResponse(
        columns=list(page.columns),
        rows=[[None if cell is None else str(cell) for cell in row] for row in page.rows],
        offset=page.offset,
        limit=page.limit,
        total_rows=handle.version.row_count,
    )


@router.post(
    "/workspaces/{workspace_id}/dataset-versions/{version_id}/schema",
    status_code=status.HTTP_201_CREATED,
)
async def override_schema(
    workspace_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: SchemaOverrideRequest,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
) -> SchemaContractResponse:
    """Correct a schema, producing the **next** contract version (FR-C.2, FR-C.3).

    Never an edit — INV-3, and the database refuses an UPDATE independently of
    anything written here. The response is the new version, so a client that
    ignores it still cannot end up thinking it changed the old one.

    ``editor`` is required. §13.3 gives a ``viewer`` read access and read-only
    tools; an interpretation that every later number depends on is not that.

    **An override that would discard values is accepted and recorded.** The user
    knows what the column means and we do not (§10.2), but D-029 exists because
    losing values silently is the failure this whole design avoids — so the new
    contract states how many values do not conform, in words.
    """
    try:
        handle = await open_dataset_version(
            principal,
            DatasetVersionId(version_id),
            connection=connection,
            store=store,
            required_role=Role.EDITOR,
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc
    if handle.workspace_id != WorkspaceId(workspace_id):
        raise NOT_FOUND

    repository = SchemaContractRepository(connection)
    current = await repository.latest_for_version(DatasetVersionId(version_id))
    if current is None:
        raise NOT_FOUND

    try:
        updated = override.apply(
            current,
            [
                override.ColumnOverride(
                    name=column.name,
                    logical_type=(
                        None if column.logical_type is None else LogicalType(column.logical_type)
                    ),
                    role=None if column.role is None else ColumnRole(column.role),
                    null_markers=(
                        None if column.null_markers is None else tuple(column.null_markers)
                    ),
                    format_hint=column.format_hint,
                )
                for column in payload.columns
            ],
            actor=principal.user_id,
            now=system_clock(),
            # Measured, not assumed: the cost of an override is only knowable by
            # looking at the data it applies to.
            #
            # **Unless the data is gone.** A row can outlive its bytes — that is
            # what ``data_present: false`` means, and it is why the field
            # exists. Refusing to let someone fix a type because the file is
            # missing would hold the metadata hostage to a storage problem it
            # has nothing to do with, so the correction still goes through and
            # simply records no conformance count.
            statistics=(
                {s.name: s for s in engine.column_statistics(handle)} if handle.exists() else None
            ),
        )
    except SchemaOverrideRejected as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    await repository.create(updated)
    await AuditRepository(connection).record(
        action=AuditAction.SCHEMA_CONTRACT_CREATED,
        now=updated.created_at,
        workspace_id=handle.workspace_id,
        actor_user_id=principal.user_id,
        target_type="schema_contract",
        target_id=updated.id,
        # Ordinals, not names: a column name is sensitive (K1, §13.5.1) and
        # this table can never be deleted from (§13.7.1).
        metadata={
            "dataset_version_id": str(version_id),
            "version_no": updated.version_no,
            "derived_from": str(current.id),
            "changed_ordinals": sorted(
                column.ordinal for column in updated.columns if column.is_user_overridden
            ),
        },
    )
    return _contract_response(updated)


@router.delete(
    "/workspaces/{workspace_id}/projects/{project_id}/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dataset(
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
) -> None:
    """FR-B.6 — the files really go, not only the rows.

    The engine is not used here and is asked for anyway: ``IngestService`` is
    one object with one set of collaborators, and giving deletion a second,
    thinner constructor would mean two ways to build the thing that deletes
    data. One of them would eventually skip something.
    """
    scope = await _scope(principal, workspace_id, project_id, connection, store)

    located = await DatasetRepository(connection).locate(DatasetId(dataset_id))
    if located is None or located[1] != scope.workspace_id:
        raise NOT_FOUND

    try:
        await IngestService(connection, scope=scope, engine=engine).delete_dataset(
            DatasetId(dataset_id), actor=principal.user_id, now=system_clock()
        )
    except IngestRejected as exc:
        raise NOT_FOUND from exc


async def _commit(
    *,
    scope: IngestScope,
    connection: Connection,
    engine: TableEngine,
    principal: Principal,
    file: UploadFile,
    dataset_id: DatasetId | None,
    name: str | None,
    delimiter: str | None,
    encoding: str | None,
    has_header: bool | None,
) -> DatasetWithVersionResponse:
    filename = file.filename or "upload"
    try:
        fmt, detected = await _inspect(file)
        dialect = _dialect_from_form(delimiter, encoding, has_header, detected)

        committed = await IngestService(connection, scope=scope, engine=engine).commit(
            upload=file.file,
            filename=filename,
            declared_size=file.size or 0,
            fmt=fmt,
            dialect=dialect,
            dataset_id=dataset_id,
            dataset_name=name or filename,
            actor=principal.user_id,
            now=system_clock(),
        )
    except IngestRejected as exc:
        raise _rejected(exc) from exc

    return DatasetWithVersionResponse(
        dataset=_dataset_response(committed.dataset),
        version=_version_response(committed.version, data_present=True),
        schema_contract=_contract_response(committed.contract),
        original_filename=committed.source_file.original_filename,
    )


__all__ = ["router"]
