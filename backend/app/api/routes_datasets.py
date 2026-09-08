"""Upload, preview and dataset routes (FR-B.1..B.4, FR-B.6, §10.4 Alur 1).

Two shapes of route live here, and the difference is the whole of D-025.

``POST /uploads/preview`` is **authenticated but not tenant-scoped**: it reads a
prefix, says how it would be parsed, and keeps nothing. There is no resource to
scope it to, because nothing is stored.

Everything else goes through ``data_access.open_account_for_ingest``, which
is to writing what ``open_dataset`` is to reading. Neither route below
picks a storage path itself — the scope mints every URI from the account it was
opened for, so a handler cannot write outside its tenant even by mistake.

## Why the paths lost their prefix (D-039)

These routes read ``/workspaces/{id}/projects/{id}/datasets`` until the account
became the tenant. Two path parameters went, and with them a class of guard:
each handler used to re-check that the workspace in the URL matched the one
authorization had resolved, because a caller could name a workspace they were in
and a version they were not. There is no id in the path to disagree with the
session any more, so the guard has nothing left to compare — it was removed
rather than left as a tautology.

## Why the version routes became dataset routes (D-043)

``/dataset-versions/{id}`` was four routes — the version, its schema, its
profile, its rows — plus a fifth that created a new version of a dataset. A
dataset has one set of bytes now, so the id in all four is the dataset's, and
the fifth has nothing to create. Each still takes an id belonging to somebody,
so each is still tenant-scoped in the manifest and still swept.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import Connection, CurrentPrincipal, Engine, SettingsDep, Store
from app.api.schemas import (
    ArtifactResponse,
    AskRequest,
    AskResponse,
    ColumnDetailResponse,
    ColumnProfileResponse,
    ColumnSpecResponse,
    CommittedResponse,
    ComplaintResponse,
    DatasetProfileResponse,
    DatasetResponse,
    DatasetSummaryResponse,
    DialectResponse,
    HistoryResponse,
    IngestPreviewResponse,
    LoadSampleRequest,
    RanResponse,
    RowPageResponse,
    SampleDatasetResponse,
    SchemaContractResponse,
    SchemaOverrideRequest,
    TurnSummaryResponse,
)
from app.authz.data_access import (
    DataAccessDenied,
    IngestScope,
    open_account_for_ingest,
    open_dataset,
)
from app.clock import system_clock
from app.domain.audit import AuditAction
from app.domain.conversation import ConversationTurn
from app.domain.data import Dataset, SchemaContract
from app.domain.enums import LogicalType, PrivacyMode, SourceFormat
from app.domain.ids import DatasetId
from app.domain.principal import Principal
from app.ingest import formats, preview, samples
from app.ingest.dialect import Dialect, detect
from app.ingest.limits import PREVIEW_BYTES, IngestRejected
from app.ingest.service import IngestService
from app.llm.executor import RunnerExecutor
from app.llm.factory import cascade_for
from app.llm.planner import run_turn
from app.llm.privacy import PrivacyGate
from app.repositories.audit import AuditRepository
from app.repositories.conversation import ConversationRepository
from app.repositories.data import DatasetRepository
from app.repositories.execution import ComputationRepository
from app.repositories.identity import UserPolicyRepository
from app.repositories.schema import SchemaContractRepository
from app.schema import override
from app.schema.override import SchemaOverrideRejected
from app.storage.engine import EngineError, TableEngine
from app.storage.object_store import ObjectStore
from app.tools.contract import REGISTRY, ToolError, UnknownTool
from app.tools.runner import ToolRunner

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


def _scope(principal: Principal, store: ObjectStore) -> IngestScope:
    """Permission to write into the caller's own namespace.

    Kept as a named helper even though it now forwards one call. It is the
    single place every write route goes through, and a reader looking for
    *where is the write gate* should find one answer rather than eight
    identical inline constructions.
    """
    return open_account_for_ingest(principal, store=store)


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


def _contract_response(contract: SchemaContract) -> SchemaContractResponse:
    return SchemaContractResponse(
        id=contract.id,
        dataset_id=contract.dataset_id,
        version_no=contract.version_no,
        created_at=contract.created_at,
        derived_from=contract.derived_from,
        columns=[
            ColumnSpecResponse(
                name=column.name,
                ordinal=column.ordinal,
                physical_type=column.physical_type,
                logical_type=column.logical_type.value,
                null_markers=list(column.null_markers),
                detection_confidence=column.detection_confidence,
                detection_reason=column.detection_reason,
                overridden=column.is_user_overridden,
            )
            for column in sorted(contract.columns, key=lambda c: c.ordinal)
        ],
    )


def _dataset_response(item: Dataset, *, data_present: bool) -> DatasetResponse:
    """The dataset and the facts about its bytes, in one payload.

    ``data_present`` is passed rather than derived because deriving it needs the
    object store, and the only thing entitled to ask the store anything is a
    ``DataHandle`` (§13.3.1 L3). The caller has one; this function does not.
    """
    return DatasetResponse(
        id=item.id,
        owner_id=item.owner_id,
        name=item.name,
        content_hash=item.content_hash,
        row_count=item.row_count,
        column_count=item.column_count,
        byte_size=item.byte_size,
        created_at=item.created_at,
        data_present=data_present,
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


@router.get("/datasets")
async def list_datasets(
    connection: Connection,
    principal: CurrentPrincipal,
) -> list[DatasetSummaryResponse]:
    """Datasets with enough context to choose one.

    Returns summaries rather than names. A name on its own is a dead end — it
    says what was uploaded and nothing about which one wants attention — and
    that was exactly the complaint the first person to use this screen had.

    Authenticated rather than tenant-scoped: there is no id in the path, so
    there is nowhere for a caller to point but at their own account.
    """
    summaries = await DatasetRepository(connection).summaries_for_owner(principal.user_id)
    return [
        DatasetSummaryResponse(
            id=summary.dataset.id,
            name=summary.dataset.name,
            created_at=summary.dataset.created_at,
            row_count=summary.dataset.row_count,
            column_count=summary.dataset.column_count,
            schema_version_no=summary.schema_version_no,
        )
        for summary in summaries
    ]


@router.get("/samples")
async def list_samples(principal: CurrentPrincipal) -> list[SampleDatasetResponse]:
    """What the empty state can offer (FR-B.5).

    Authenticated but not tenant-scoped: this is a catalogue of what the server
    ships, identical for everyone, and it names no data belonging to anybody.
    """
    del principal
    return [
        SampleDatasetResponse(key=s.key, name=s.name, description=s.description)
        for s in samples.SAMPLES
    ]


@router.post(
    "/datasets/samples",
    status_code=status.HTTP_201_CREATED,
)
async def load_sample(
    payload: LoadSampleRequest,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    settings: SettingsDep,
) -> CommittedResponse:
    """Ingest a bundled sample (FR-B.5).

    Goes through **the same commit path** an upload does — same authorization,
    same normalization, same inference. A shortcut that produced a dataset by
    some other route would make the demo prove something the product does not
    do, which is worse than having no demo.
    """
    scope = _scope(principal, store)
    try:
        sample, path = samples.resolve(payload.key, settings.samples_root)
        with path.open("rb") as handle:
            committed = await IngestService(connection, scope=scope, engine=engine).commit(
                upload=handle,
                filename=sample.filename,
                declared_size=path.stat().st_size,
                fmt=SourceFormat.CSV,
                dialect=detect(path.open("rb").read(PREVIEW_BYTES), is_prefix=True),
                dataset_name=sample.name,
                actor=principal.user_id,
                now=system_clock(),
            )
    except IngestRejected as exc:
        raise _rejected(exc) from exc

    return CommittedResponse(
        dataset=_dataset_response(committed.dataset, data_present=True),
        schema_contract=_contract_response(committed.contract),
        original_filename=committed.source_file.original_filename,
    )


@router.post(
    "/datasets",
    status_code=status.HTTP_201_CREATED,
)
async def create_dataset(
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    file: Annotated[UploadFile, File()],
    name: Annotated[str | None, Form()] = None,
    delimiter: Annotated[str | None, Form()] = None,
    encoding: Annotated[str | None, Form()] = None,
    has_header: Annotated[bool | None, Form()] = None,
) -> CommittedResponse:
    """Commit an upload as a new Dataset (FR-B.1, FR-B.3, FR-B.4).

    ``POST /datasets/{id}/versions`` stood beside this and added a version to an
    existing dataset — FR-B.2, never an overwrite. D-043 removed the versions,
    so a re-upload is another dataset. The requirement went with them, in the
    changelog rather than quietly.
    """
    scope = _scope(principal, store)
    return await _commit(
        scope=scope,
        connection=connection,
        engine=engine,
        principal=principal,
        file=file,
        name=name,
        delimiter=delimiter,
        encoding=encoding,
        has_header=has_header,
    )


@router.get("/datasets/{dataset_id}")
async def get_dataset(
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> DatasetResponse:
    """The route that exercises INV-7 end to end.

    Note what is *absent*: no ownership check written here. The handler cannot
    reach the data without a handle, and only ``open_dataset`` produces one.
    That is the difference between a check somebody remembered and a check that
    cannot be skipped.

    It lived in ``routes_workspaces.py`` until D-039, which is why it moved
    rather than changed: the module went with the workspace, the route did not.
    What it lost is the guard that compared the workspace in the path with the
    one the handle was opened in — there is no id in the path to disagree with
    the session any more.
    """
    try:
        handle = await open_dataset(
            principal,
            DatasetId(dataset_id),
            connection=connection,
            store=store,
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    # The second query that used to be here is gone with the second table. It
    # fetched the dataset to read its name, and had to be ordered *after* the
    # handle so that "does this exist" was never answered to somebody with no
    # business asking. The name is on the handle now, so the ordering hazard
    # cannot be got wrong.
    return _dataset_response(handle.dataset, data_present=handle.exists())


@router.get("/datasets/{dataset_id}/schema")
async def get_schema_contract(
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> SchemaContractResponse:
    """The current interpretation of a Dataset (FR-C.1, FR-C.3).

    Goes through ``open_dataset`` rather than checking membership here.
    A schema describes data — column names are already sensitive on their own
    (K1, §13.5.1) — so it is guarded by exactly what guards the data.

    The handle is discarded on purpose: this route reads the contract, not the
    bytes. Opening it anyway is what makes the guard the same guard.
    """
    try:
        await open_dataset(principal, DatasetId(dataset_id), connection=connection, store=store)
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    contract = await SchemaContractRepository(connection).latest_for_dataset(DatasetId(dataset_id))
    if contract is None:
        raise NOT_FOUND
    return _contract_response(contract)


@router.get("/datasets/{dataset_id}/profile")
async def get_profile(
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
) -> DatasetProfileResponse:
    """The Profile tab (FR-D.5, §11.8) — one tool, one Computation.

    Note what this handler does *not* do: it computes nothing. It authorizes,
    finds the contract, and asks the runner for ``describe_dataset``. Whether
    the answer is fresh or three days old is invisible here and deliberately so
    — §9.4 makes a cached result and a recomputed one the same result, so a
    route that treated them differently would be inventing a distinction.

    Every number in the response carries ``computation_id`` beside it. That is
    INV-5, and it is why this route waited for `computation` to exist rather
    than shipping a plain read.
    """
    try:
        handle = await open_dataset(
            principal, DatasetId(dataset_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    contract = await SchemaContractRepository(connection).latest_for_dataset(DatasetId(dataset_id))
    if contract is None:
        raise NOT_FOUND

    if not handle.exists():
        # The rows are gone but the contract is not — `data_present: false` on
        # the version response says the same thing. Profiling absent bytes would
        # report zeros as though they were measurements.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the data for this version is not in storage",
        )

    try:
        computation = await ToolRunner(connection).run(
            "describe_dataset", handle=handle, contract=contract, engine=engine
        )
    except ToolError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    except EngineError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    result = computation.result
    return DatasetProfileResponse(
        computation_id=computation.id,
        fingerprint=computation.fingerprint,
        tool_name=computation.tool_name,
        tool_version=computation.tool_version,
        computed_at=computation.computed_at,
        duration_ms=computation.duration_ms,
        row_count=result["row_count"],
        columns=[ColumnProfileResponse(**column) for column in result["columns"]],
    )


@router.get("/datasets/{dataset_id}/columns/{column}/profile")
async def get_column_profile(
    dataset_id: uuid.UUID,
    column: str,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
) -> ColumnDetailResponse:
    """One column, in depth (FR-D.5, §11.7) — the panel behind a profile card.

    The same shape as `get_profile` above and for the same reasons: it computes
    nothing, it authorizes and asks the runner. What differs is which tool and
    that this one takes an argument, so two columns of one dataset are two
    fingerprints and two cache entries — which is right, they are two questions.

    A name that is not a column of this dataset comes back **422 and not 404**.
    404 in this API means *not there, or not yours* (§13.3.1 L2), and answering
    it here would tell a caller who already proved they own the dataset that
    their typo was an authorization problem.
    """
    try:
        handle = await open_dataset(
            principal, DatasetId(dataset_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    contract = await SchemaContractRepository(connection).latest_for_dataset(DatasetId(dataset_id))
    if contract is None:
        raise NOT_FOUND

    if not handle.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the data for this version is not in storage",
        )

    try:
        computation = await ToolRunner(connection).run(
            "profile_column",
            handle=handle,
            contract=contract,
            engine=engine,
            given={"column": column},
        )
    except (ToolError, EngineError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc

    return ColumnDetailResponse(
        computation_id=computation.id,
        fingerprint=computation.fingerprint,
        tool_name=computation.tool_name,
        tool_version=computation.tool_version,
        computed_at=computation.computed_at,
        duration_ms=computation.duration_ms,
        **computation.result,
    )


@router.post("/datasets/{dataset_id}/ask")
async def ask(
    dataset_id: uuid.UUID,
    body: AskRequest,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
    engine: Engine,
    settings: SettingsDep,
) -> AskResponse:
    """One copilot turn (§12.3), end to end.

    The route computes nothing and decides nothing. It opens the dataset —
    which is where authorization happens, once, through `data_access.open`
    (INV-7) — reads the account's privacy mode, and hands both to the planner.
    Everything after that is §12.3, and the planner cannot reach data except
    through the executor built here.

    **The privacy mode is read per turn rather than cached**, because a policy
    that took effect at process start is a policy that ignores the user
    changing it. The settings default is used only when the account has no
    policy row at all, which registration makes, so it is a fallback for a
    state that should not exist rather than a normal path.

    ⚠️ **No rate limit yet** (NFR-SEC.6). Auth is limited and this is not, and
    unlike the upload route this one spends somebody else's tokens per request.
    Recorded as debt rather than left unsaid.
    """
    try:
        handle = await open_dataset(
            principal, DatasetId(dataset_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    contract = await SchemaContractRepository(connection).latest_for_dataset(DatasetId(dataset_id))
    if contract is None:
        raise NOT_FOUND
    if not handle.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="the data for this version is not in storage",
        )

    policy = await UserPolicyRepository(connection).get(principal.user_id)
    mode = policy.llm_privacy_mode if policy is not None else settings.default_llm_privacy_mode
    gate = PrivacyGate(mode)

    # `local` is not a preference that ranks cloud lower — it removes cloud
    # entirely, so the cascade is built without it rather than filtered later.
    cascade = cascade_for(settings, local_only=mode is PrivacyMode.LOCAL)

    turn = await run_turn(
        body.question,
        client=cascade,
        registry=REGISTRY,
        contract=contract,
        gate=gate,
        executor=RunnerExecutor(
            ToolRunner(connection), handle=handle, contract=contract, engine=engine
        ),
        budget=settings.llm_monthly_token_budget,
    )

    # **Recorded before it is returned**, so a log entry exists for every
    # answer the reader saw — including the ones that stopped without one.
    # §12.4 keeps this for display and for debugging, and never sends it back
    # to a model.
    await ConversationRepository(connection).record(
        ConversationTurn(
            id=uuid.uuid4(),
            dataset_id=DatasetId(dataset_id),
            schema_contract_id=contract.id,
            asked_by=principal.user_id,
            asked_at=system_clock(),
            question=body.question,
            narrative=turn.narrative,
            grounded=turn.grounded,
            stopped=turn.stopped,
            steps=tuple(
                {"ref": step.ref, "tool": step.tool, "args": step.args} for step in turn.steps
            ),
            complaints=tuple(
                {"kind": item.kind, "detail": item.detail} for item in turn.complaints
            ),
            tokens=turn.tokens,
            provider=turn.provider,
            model=turn.model,
        )
    )

    return AskResponse(
        narrative=turn.narrative,
        grounded=turn.grounded,
        steps=[_ran(step.ref, step.tool, step.args) for step in turn.steps],
        complaints=[
            ComplaintResponse(kind=item.kind, detail=item.detail) for item in turn.complaints
        ],
        stopped=turn.stopped,
        rejections=list(turn.rejections),
        categories=list(turn.categories),
        tokens=turn.tokens,
        privacy_mode=mode.value,
        provider=turn.provider,
        model=turn.model,
    )


def _ran(ref: str, tool: str, args: dict[str, Any]) -> RanResponse:
    """One step, with the vocabulary the canvas renders by.

    `output_kind` is read from the registry rather than stored on the turn: it
    is a fact about the **tool**, and a copy of it in a row would be a second
    place to update the day a tool's shape changes (§11.2).

    An unknown name yields an empty kind rather than raising. A tool can be
    withdrawn from a build while rows that named it survive, and a history that
    refused to load because one old entry mentioned something retired would be
    the log punishing the reader for a decision somebody else made.
    """
    try:
        kind = REGISTRY.get(tool).output_kind
    except UnknownTool:
        kind = ""
    return RanResponse(ref=ref, tool=tool, args=args, output_kind=kind)


@router.get("/datasets/{dataset_id}/computations/{computation_id}")
async def artifact(
    dataset_id: uuid.UUID,
    computation_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> ArtifactResponse:
    """One computation's result, for the canvas to draw (INV-5).

    Opened through `data_access.open` like every other read, and then looked up
    **within this dataset** — so a computation belonging to somebody else comes
    back as not found rather than as forbidden (§13.3.1). Two gates, and the
    second is in the query rather than after it.

    ⚠️ **The Privacy Gate does not run here, and that is INV-9 rather than an
    omission.** PG-1 and PG-2 are outbound *to a model*; the person who owns
    the data always sees it whole. Filtering this would hide a reader's own
    rows from them to protect them from themselves.
    """
    try:
        await open_dataset(principal, DatasetId(dataset_id), connection=connection, store=store)
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    found = await ComputationRepository(connection).within(computation_id, DatasetId(dataset_id))
    if found is None:
        raise NOT_FOUND

    try:
        kind = REGISTRY.get(found.tool_name).output_kind
    except UnknownTool:
        kind = ""

    return ArtifactResponse(
        ref=str(found.id),
        tool=found.tool_name,
        tool_version=found.tool_version,
        output_kind=kind,
        result=found.result,
    )


@router.delete(
    "/datasets/{dataset_id}/history/{turn_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def forget(
    dataset_id: uuid.UUID,
    turn_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> None:
    """Forget one question (NFR-PRIV.3).

    Opened through `data_access.open` like every other read of a dataset, then
    deleted **within** that dataset — so a turn belonging to somebody else is
    not matched at all and comes back as not found rather than as forbidden
    (§13.3.1).

    ⚠️ **The computations it named survive, and that is the design.** A
    `Computation` is identified by its fingerprint (§9.4) and shared by every
    turn that asked the same question of the same data; deleting one because a
    log entry was tidied away would empty a cache entry another turn still
    cites. What NFR-PRIV.3 asks to be removable is the sentence a person typed,
    and that is what goes — the same reason §13.7.1 keeps only
    `sha256(prompt)` in the audit log, and the reason this table alone carries
    no immutability trigger.

    Idempotent: a turn that is already gone answers 204 rather than 404. The
    caller asked for it to not exist, and it does not.
    """
    try:
        await open_dataset(principal, DatasetId(dataset_id), connection=connection, store=store)
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    await ConversationRepository(connection).forget(turn_id, DatasetId(dataset_id))


@router.get("/datasets/{dataset_id}/history")
async def history(
    dataset_id: uuid.UUID,
    connection: Connection,
    principal: CurrentPrincipal,
    store: Store,
) -> HistoryResponse:
    """Every question asked of this dataset, newest first (§12.4).

    Opened through `data_access.open` like every other read, so a dataset
    somebody else owns is **not found** rather than forbidden (INV-7,
    §13.3.1). The log is not a side channel around that gate.

    Nothing here is ever sent to a model. §12.4 is explicit: the transcript is
    stored to be shown to the person who wrote it, and what a planner receives
    is structured state assembled fresh each turn.
    """
    try:
        await open_dataset(principal, DatasetId(dataset_id), connection=connection, store=store)
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    turns = await ConversationRepository(connection).history(DatasetId(dataset_id))
    return HistoryResponse(
        turns=[
            TurnSummaryResponse(
                id=turn.id,
                asked_at=turn.asked_at,
                question=turn.question,
                narrative=turn.narrative,
                grounded=turn.grounded,
                stopped=turn.stopped,
                steps=[
                    _ran(
                        str(step.get("ref", "")),
                        str(step.get("tool", "")),
                        dict(step.get("args") or {}),
                    )
                    for step in turn.steps
                ],
                complaints=[
                    ComplaintResponse(
                        kind=str(item.get("kind", "")), detail=str(item.get("detail", ""))
                    )
                    for item in turn.complaints
                ],
                provider=turn.provider,
                model=turn.model,
            )
            for turn in turns
        ]
    )


@router.get("/datasets/{dataset_id}/rows")
async def get_rows(
    dataset_id: uuid.UUID,
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
        handle = await open_dataset(
            principal, DatasetId(dataset_id), connection=connection, store=store
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc
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
        total_rows=handle.dataset.row_count,
    )


@router.post(
    "/datasets/{dataset_id}/schema",
    status_code=status.HTTP_201_CREATED,
)
async def override_schema(
    dataset_id: uuid.UUID,
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

    **An override that would discard values is accepted and recorded.** The user
    knows what the column means and we do not (§10.2), but D-029 exists because
    losing values silently is the failure this whole design avoids — so the new
    contract states how many values do not conform, in words.
    """
    try:
        handle = await open_dataset(
            principal,
            DatasetId(dataset_id),
            connection=connection,
            store=store,
        )
    except DataAccessDenied as exc:
        raise NOT_FOUND from exc

    repository = SchemaContractRepository(connection)
    current = await repository.latest_for_dataset(DatasetId(dataset_id))
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
        actor_user_id=principal.user_id,
        target_type="schema_contract",
        target_id=updated.id,
        # Ordinals, not names: a column name is sensitive (K1, §13.5.1) and
        # this table can never be deleted from (§13.7.1).
        metadata={
            "dataset_id": str(dataset_id),
            "version_no": updated.version_no,
            "derived_from": str(current.id),
            "changed_ordinals": sorted(
                column.ordinal for column in updated.columns if column.is_user_overridden
            ),
        },
    )
    return _contract_response(updated)


@router.delete(
    "/datasets/{dataset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_dataset(
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
    scope = _scope(principal, store)

    located = await DatasetRepository(connection).locate(DatasetId(dataset_id))
    if located is None or not principal.owns(located[1]):
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
    name: str | None,
    delimiter: str | None,
    encoding: str | None,
    has_header: bool | None,
) -> CommittedResponse:
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
            dataset_name=name or filename,
            actor=principal.user_id,
            now=system_clock(),
        )
    except IngestRejected as exc:
        raise _rejected(exc) from exc

    return CommittedResponse(
        dataset=_dataset_response(committed.dataset, data_present=True),
        schema_contract=_contract_response(committed.contract),
        original_filename=committed.source_file.original_filename,
    )


__all__ = ["router"]
