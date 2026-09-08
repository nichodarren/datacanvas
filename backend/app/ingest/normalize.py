"""Reading an upload into a table, and writing it back out as Parquet (FR-B.4).

Two rules govern this module, and both were decided after being measured rather
than assumed.

**D-027 — acceptance is parsing.** Every reader either produces a table or
raises :class:`IngestRejected` with something the user can act on. A reader is
never asked "is this yours?"; it is asked to do the work, and failing *is* the
answer. Adding a format therefore means adding one reader and one registry
entry, and touching nothing else — the same shape NFR-MAINT.1 requires of tools.

**D-026 — the Parquet write is deterministic and pinned.** Every option is
stated here instead of inherited from whatever polars currently defaults to.
The same input has to produce the same bytes, because that is what makes
``content_hash`` mean anything and what lets INV-6 be tested rather than hoped
for. ``tests/unit/test_normalize.py`` is where that is enforced.
"""

from __future__ import annotations

import codecs
import hashlib
import io
import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Final, Literal, TypedDict

import openpyxl
import polars as pl

from app.domain.enums import SourceFormat
from app.ingest.dialect import CANDIDATE_DELIMITERS, Dialect
from app.ingest.limits import MAX_ROWS, IngestRejected, check_row_count


class ParquetWriteOptions(TypedDict):
    """Typed so both writers are checked against the same options.

    A bare ``dict[str, object]`` type-checks nothing at either call site, and
    the entire value of pinning these is that the two paths — in-memory and
    streaming — cannot drift apart. A typo would otherwise surface as different
    bytes from different code paths, which is to say two ``content_hash`` values
    for one table.
    """

    compression: Literal["zstd"]
    compression_level: int
    statistics: bool
    row_group_size: int


#: D-026. Pinned, not defaulted. Changing any of these changes the
#: ``content_hash`` of everything written afterwards, so they change together
#: with a deliberate decision and never as a side effect of an upgrade.
#:
#: ``compression`` — zstd is polars' current default; naming it means an
#: upstream change of default does not silently change our bytes.
#: ``statistics`` — off. Measured: the default writes each column's min and max
#: into the footer, so a salary column ships its highest and lowest salary in
#: metadata. **This one is a genuine trade-off, not a free win:** statistics are
#: what lets a reader skip row groups, so filtering (FR-D.6, P1) may cost more
#: without them. Chosen because Phase 2 only ever scans and pages, and a value
#: that never enters the file cannot leak from it. Revisit with a measurement
#: when FR-D.6 lands — not before, and not on intuition.
#: ``row_group_size`` — fixed, because the default is derived from the frame
#: and would make byte output depend on how the data happened to be chunked.
PARQUET_WRITE_OPTIONS: Final[ParquetWriteOptions] = {
    "compression": "zstd",
    "compression_level": 3,
    "statistics": False,
    "row_group_size": 122_880,
}

#: A table has to have at least one column. The *interesting* single-column
#: case — rows that were never split because the delimiter was wrong — is
#: :func:`_reject_unsplit_rows`, not this.
_MIN_COLUMNS: Final = 1

#: Read size when transcoding or hashing a file. Bounded work per iteration is
#: the entire point of the file-based path.
TRANSCODE_CHUNK_BYTES: Final = 1024 * 1024

#: A reader turns bytes plus an optional dialect into a frame, or raises.
Reader = Callable[[bytes, Dialect | None], pl.DataFrame]


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    """A table on its way to becoming a Dataset."""

    frame: pl.DataFrame
    parquet: bytes
    content_hash: str

    @property
    def row_count(self) -> int:
        return self.frame.height

    @property
    def column_count(self) -> int:
        return self.frame.width

    @property
    def byte_size(self) -> int:
        return len(self.parquet)


def _require_dialect(dialect: Dialect | None, fmt: SourceFormat) -> Dialect:
    if dialect is None:
        raise IngestRejected(f"{fmt.value} needs a dialect (delimiter, encoding, header row)")
    return dialect


def is_utf8(encoding: str) -> bool:
    """Only plain UTF-8 goes to polars untouched — a BOM counts as *not* plain."""
    return encoding.lower() == "utf-8"


def to_utf8(data: bytes, encoding: str) -> bytes:
    """Re-encode to UTF-8 using the encoding the detector actually reported.

    **This exists because of a data-loss bug, and the bug is worth stating.**
    polars speaks two encodings: ``utf8`` and ``utf8-lossy``. An earlier version
    of this module handed non-UTF-8 files to ``utf8-lossy`` — which does not
    convert anything, it *replaces every byte it cannot read* with U+FFFD. A
    cp1252 file saying ``café dekat alun-alun`` came back as ``caf? dekat
    alun-alun``. Nothing raised. The dialect detector had reported ``cp1252``
    correctly the whole time; the reader simply ignored it.

    That is the worst shape a defect can take here: silent, total for every
    non-ASCII character, and aimed squarely at the files our persona receives —
    Indonesian text out of Excel on a Windows machine.
    """
    if is_utf8(encoding):
        return data
    return data.decode(encoding).encode("utf-8")


def transcode_to_utf8(source: Path, destination: Path, encoding: str) -> None:
    """The same conversion for a file too large to hold in memory.

    Chunked through an *incremental* decoder, which is the whole difficulty: a
    fixed-size read almost always lands inside a multi-byte character, and a
    plain ``decode`` per chunk would corrupt one character per chunk boundary —
    a defect that scales with file size and vanishes on the small files anyone
    would test with.
    """
    decoder = codecs.getincrementaldecoder(encoding)()
    with source.open("rb") as reader, destination.open("wb") as writer:
        while chunk := reader.read(TRANSCODE_CHUNK_BYTES):
            writer.write(decoder.decode(chunk).encode("utf-8"))
        writer.write(decoder.decode(b"", True).encode("utf-8"))


def read_delimited(data: bytes, dialect: Dialect | None) -> pl.DataFrame:
    """CSV and TSV.

    ``infer_schema=False`` reads **every column as text**, on purpose. FR-B.3
    requires type inference to scan the whole file, and it was written that way
    because of a real failure: ``messy_sales.legacy_code`` is 97% digits, and
    the first alphanumeric value sits far past any sample window, so
    sample-based inference guesses integer and then explodes mid-file. Reading
    as text cannot explode, and inference (P0-7) gets to see all of it.

    **Ragged rows are treated asymmetrically, and the asymmetry is deliberate.**
    A row with *too few* fields is padded with nulls; a row with *too many*
    raises. Measured rather than assumed — polars does exactly this, and it is
    the behaviour we want: a short row is ordinary messiness in the data our
    persona actually receives, and refusing it would refuse most real files.
    A long row means the layout does not hold, which is a different claim.

    The cost is real and must not be hidden: **padding is silent**. Those nulls
    are indistinguishable from nulls that were in the file. Profiling is what
    surfaces them (PQ warnings, FR-E.5) — so this is a debt paid in Phase 4, not
    a problem solved here.
    """
    chosen = _require_dialect(dialect, SourceFormat.CSV)
    try:
        frame = pl.read_csv(
            io.BytesIO(to_utf8(data, chosen.encoding)),
            separator=chosen.delimiter,
            has_header=chosen.has_header,
            encoding="utf8",
            infer_schema=False,
            null_values=None,
            truncate_ragged_lines=False,
        )
    except (pl.exceptions.PolarsError, ValueError) as exc:
        raise IngestRejected(_explain_csv_failure(exc, chosen)) from exc

    if not chosen.has_header:
        frame = frame.rename({name: f"column_{i + 1}" for i, name in enumerate(frame.columns)})
    _reject_unsplit_rows(frame, chosen)
    return frame


def _reject_unsplit_rows(frame: pl.DataFrame, dialect: Dialect) -> None:
    """Catch the wrong delimiter, which otherwise succeeds.

    Found by a test written to assert the opposite. Reading a comma file with
    ``;`` does **not** fail — every row simply becomes one long field, and ingest
    reports success on a single-column table full of unsplit lines. That is worse
    than an error: an error is noticed, and this is committed, profiled and
    analysed before anyone looks closely.

    A genuinely single-column file is legitimate (a list of ids), so width alone
    cannot be the test. What distinguishes the two is that the unsplit case is
    *full of some other candidate delimiter* — so the check is not "one column"
    but "one column, and the data is visibly asking for a different separator",
    which is also what lets the message name it.
    """
    if frame.width != 1:
        return

    column = frame.columns[0]
    sample = [column, *(str(v) for v in frame[column].head(20).to_list() if v is not None)]
    counts = {
        candidate: sum(line.count(candidate) for line in sample)
        for candidate in CANDIDATE_DELIMITERS
        if candidate != dialect.delimiter
    }
    likely = max(counts, key=lambda c: counts[c], default=None)
    if likely is None or counts[likely] < len(sample):
        return

    raise IngestRejected(
        f"reading this with delimiter {dialect.delimiter!r} produced a single column, and "
        f"the rows are full of {likely!r}. Set the delimiter to {likely!r} and try again."
    )


def _explain_csv_failure(exc: Exception, dialect: Dialect) -> str:
    """Turn a parser error into something a person can act on (P6, NFR-REL.2).

    This is where D-025's admitted weakness surfaces: a dialect detected from
    the first megabyte can be wrong for the rest of the file. When that happens
    the user needs to be told *which* setting to reconsider, not handed a stack
    trace.
    """
    detail = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
    return (
        f"could not read the file as delimited text using delimiter "
        f"{dialect.delimiter!r} and encoding {dialect.encoding!r}: {detail}. "
        "Rows further into the file may not match the layout detected from its "
        "first rows — check the delimiter, or whether some rows have extra columns."
    )


def read_sample(
    data: bytes, fmt: SourceFormat, dialect: Dialect | None
) -> tuple[pl.DataFrame, tuple[str, ...]]:
    """A deliberately lenient read, for the preview only (D-025, FR-B.3).

    **Preview and commit parse differently, and that is the design.** Commit
    must be exact — it produces the Dataset every later number depends
    on. A preview exists so a person can *correct* something, and a preview that
    refuses hands them nothing to correct: they cannot tell a wrong delimiter
    from a genuinely ragged file, which are the two problems it is there to
    distinguish.

    So this tolerates over-wide rows and reports what it tolerated. The
    divergence has a cost — a preview can look fine where commit then fails —
    and it is paid honestly: whatever was tolerated comes back as a note, and
    D-025 already requires the commit failure to be actionable.
    """
    if not fmt.is_delimited_text:
        return read(data, fmt, dialect), ()

    chosen = _require_dialect(dialect, fmt)
    try:
        return read(data, fmt, chosen), ()
    except IngestRejected:
        pass

    frame = pl.read_csv(
        io.BytesIO(data),
        separator=chosen.delimiter,
        has_header=chosen.has_header,
        encoding="utf8" if chosen.encoding.startswith("utf-8") else "utf8-lossy",
        infer_schema=False,
        truncate_ragged_lines=True,
    )
    if not chosen.has_header:
        frame = frame.rename({name: f"column_{i + 1}" for i, name in enumerate(frame.columns)})
    return frame, (
        "some rows have more fields than the header and were trimmed for this preview; "
        "committing will refuse them until the delimiter or the file is corrected",
    )


def read_parquet(data: bytes, dialect: Dialect | None) -> pl.DataFrame:
    """Parquet needs no dialect; it carries its own schema."""
    del dialect
    try:
        return pl.read_parquet(io.BytesIO(data))
    except (pl.exceptions.PolarsError, ValueError, OSError) as exc:
        raise IngestRejected(f"could not read this as Parquet: {exc}") from exc


def _cell_text(value: object) -> str | None:
    """One spreadsheet or JSON value, as the text every other format arrives as.

    **Everything becomes text, deliberately.** CSV has no choice; XLSX and JSON
    do, and taking it would mean two inference paths — one over strings and one
    over whatever the source claimed. D-029's rules are written for the first,
    and a second path is a second set of bugs.

    Discarding Excel's own typing costs less than it sounds. Excel is famously
    unreliable about it — it is the program that turns gene names into dates —
    so re-deriving the type from the value is not a loss of authority, only of
    a guess. What *is* preserved carefully is the shape: dates are written ISO
    so the date rule recognises them, and floats keep full repr so nothing is
    rounded on the way through.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        # Midnight means "a date" in every spreadsheet ever exported.
        if value.hour == value.minute == value.second == 0 and value.microsecond == 0:
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        # Excel stores every number as a float. Writing 3 as "3.0" would make an
        # integer column decimal for a reason that has nothing to do with the
        # data (D-029: the shape rules read exactly this text).
        return str(int(value))
    return str(value)


def read_xlsx(data: bytes, dialect: Dialect | None) -> pl.DataFrame:
    """The first worksheet of an Excel workbook (FR-B.1).

    **One sheet**, as FR-B.1 says. A workbook with several is not one table, and
    silently picking the first *and not saying so* would be the wrong kind of
    convenient — so the sheet name comes back in ``ingest_options``.

    Read in openpyxl's read-only mode, which streams rather than building the
    whole workbook in memory. The decompression ratio was already checked at
    sniff time (§13.6); the row bound here is the other half, because a zip
    bomb that passes the ratio check can still be very tall.
    """
    del dialect
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises a wide family of its own errors
        raise IngestRejected(f"could not read this as an Excel workbook: {exc}") from exc

    try:
        sheet = workbook.worksheets[0]
        rows = sheet.iter_rows(values_only=True)
        try:
            header = next(rows)
        except StopIteration as exc:
            raise IngestRejected("the worksheet is empty") from exc

        names = [
            (_cell_text(cell) or f"column_{i + 1}").strip() or f"column_{i + 1}"
            for i, cell in enumerate(header)
        ]
        _reject_duplicate_names(names)

        records: list[list[str | None]] = []
        for row in rows:
            if all(cell is None for cell in row):
                # Trailing blank rows are what a spreadsheet looks like, not a
                # data row full of nulls.
                continue
            values = [_cell_text(cell) for cell in row[: len(names)]]
            values.extend([None] * (len(names) - len(values)))
            records.append(values)
            if len(records) > MAX_ROWS:
                raise IngestRejected(f"worksheet has more than {MAX_ROWS:,} rows (NFR-SCALE.1)")
    finally:
        workbook.close()

    if not records:
        raise IngestRejected("the worksheet has a header but no data rows")
    return pl.DataFrame(
        {name: [row[i] for row in records] for i, name in enumerate(names)},
        schema={name: pl.String for name in names},
    )


def read_json_records(data: bytes, dialect: Dialect | None) -> pl.DataFrame:
    """A JSON array of objects (FR-B.1), and nothing else.

    Not "any JSON". A nested document is not a table, and flattening one into
    column names like ``a.b.c`` invents a structure the user did not write —
    §9.6 is single-table, and P6 prefers saying so to guessing.
    """
    del dialect
    try:
        parsed = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IngestRejected(f"could not read this as JSON: {exc}") from exc

    if not isinstance(parsed, list):
        raise IngestRejected(
            "JSON uploads must be an array of objects, and this is a "
            f"{type(parsed).__name__}. Wrap the rows in a list."
        )
    if not parsed:
        raise IngestRejected("the JSON array is empty")

    names: list[str] = []
    for index, record in enumerate(parsed):
        if not isinstance(record, dict):
            raise IngestRejected(
                f"element {index} of the array is a {type(record).__name__}, not an object"
            )
        for key in record:
            if key not in names:
                names.append(key)

    for name in names:
        values = [record.get(name) for record in parsed]
        if any(isinstance(value, dict | list) for value in values):
            raise IngestRejected(
                f"column {name!r} contains nested objects or arrays. "
                "The MVP works on flat tables (§9.6); flatten it before uploading."
            )

    return pl.DataFrame(
        {name: [_cell_text(record.get(name)) for record in parsed] for name in names},
        schema={name: pl.String for name in names},
    )


#: One entry per format. Adding one is a reader and a line here, and nothing
#: else — the shape NFR-MAINT.1 asks of tools, applied to formats.
READERS: Final[dict[SourceFormat, Reader]] = {
    SourceFormat.CSV: read_delimited,
    SourceFormat.TSV: read_delimited,
    SourceFormat.PARQUET: read_parquet,
    SourceFormat.XLSX: read_xlsx,
    SourceFormat.JSON: read_json_records,
}


def read(data: bytes, fmt: SourceFormat, dialect: Dialect | None = None) -> pl.DataFrame:
    """Parse, or refuse with a reason (D-027)."""
    reader = READERS.get(fmt)
    if reader is None:
        raise IngestRejected(
            f"{fmt.value} uploads are not supported yet. "
            f"Supported now: {', '.join(sorted(f.value for f in READERS))}."
        )

    frame = reader(data, dialect)
    if frame.width < _MIN_COLUMNS:
        raise IngestRejected("the file produced no columns")
    if frame.height == 0:
        raise IngestRejected("the file has a header but no data rows")
    check_row_count(frame.height)
    _reject_duplicate_columns(frame)
    return frame


def _reject_duplicate_columns(frame: pl.DataFrame) -> None:
    """A SchemaContract cannot hold two columns with one name (§9.2).

    Caught here rather than at contract construction so the message names the
    file, not an invariant the user has never heard of.
    """
    _reject_duplicate_names(frame.columns)


def _reject_duplicate_names(names: list[str]) -> None:
    duplicates = sorted(name for name, n in Counter(names).items() if n > 1)
    if duplicates:
        raise IngestRejected(
            f"column names must be unique; these repeat: {', '.join(duplicates)}. "
            "Rename them in the source file before uploading."
        )


def to_parquet(frame: pl.DataFrame) -> bytes:
    """Serialise with every option pinned (D-026)."""
    buffer = io.BytesIO()
    frame.write_parquet(buffer, **PARQUET_WRITE_OPTIONS)
    return buffer.getvalue()


def content_hash(parquet: bytes) -> str:
    """SHA-256 of the normalized Parquet (§9.2).

    Identity and integrity — **not** a dedup key. D-026 explains why the earlier
    claim was withdrawn: this hash is a property of the writer as much as of the
    data, and nothing in the MVP deduplicates anything.
    """
    return hashlib.sha256(parquet).hexdigest()


def normalize(data: bytes, fmt: SourceFormat, dialect: Dialect | None = None) -> NormalizedTable:
    """The whole path from uploaded bytes to something ready to be committed.

    In-memory, so it is for previews, fixtures and tests. A real upload goes
    through :func:`normalize_file`, which never holds the table at all.
    """
    frame = read(data, fmt, dialect)
    parquet = to_parquet(frame)
    return NormalizedTable(frame=frame, parquet=parquet, content_hash=content_hash(parquet))


# ------------------------------------------------------- the file-based path --


@dataclass(frozen=True, slots=True)
class IngestedFile:
    """The facts a Dataset needs, gathered without holding the table.

    Everything here is read back from the Parquet footer or from the file on
    disk, which is why none of it requires the frame to still exist.
    """

    content_hash: str
    row_count: int
    column_count: int
    byte_size: int
    columns: tuple[str, ...]


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(TRANSCODE_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def _scan(source: Path, fmt: SourceFormat, dialect: Dialect | None) -> pl.LazyFrame:
    """A lazy view of the source, streamed where the format allows it.

    Only CSV, TSV and Parquet can genuinely be scanned. XLSX and JSON are read
    whole and then made lazy — which is honest rather than lazy-in-name: a
    worksheet caps at about a million rows and a JSON array has to be parsed
    entirely before its first row is known, so there is no streaming to be had.
    The 500 MB upload cap (NFR-SCALE.4) is what bounds them.
    """
    if fmt is SourceFormat.PARQUET:
        return pl.scan_parquet(source)
    if not fmt.is_delimited_text:
        reader = READERS.get(fmt)
        if reader is None:
            raise IngestRejected(
                f"{fmt.value} uploads are not supported yet. "
                f"Supported now: {', '.join(sorted(f.value for f in READERS))}."
            )
        return reader(source.read_bytes(), dialect).lazy()

    chosen = _require_dialect(dialect, fmt)
    frame = pl.scan_csv(
        source,
        separator=chosen.delimiter,
        has_header=chosen.has_header,
        encoding="utf8",
        infer_schema=False,
        truncate_ragged_lines=False,
    )
    if not chosen.has_header:
        names = frame.collect_schema().names()
        frame = frame.rename({name: f"column_{i + 1}" for i, name in enumerate(names)})
    return frame


def normalize_file(
    source: Path,
    fmt: SourceFormat,
    destination: Path,
    dialect: Dialect | None = None,
) -> IngestedFile:
    """Stream ``source`` into normalized Parquet at ``destination``.

    The table is never materialised: polars scans the input and sinks Parquet,
    and every fact afterwards comes from the written file's footer. That is what
    makes a 500 MB upload (NFR-SCALE.4) bounded work rather than a bet on how
    much memory the box has.

    Verified before this was relied on: **streaming and in-memory writes produce
    byte-identical Parquet** for the same input. Without that, one CSV could end
    up with two different ``content_hash`` values depending on which path
    ingested it, and D-026 would mean nothing.

    Any temporary file this needs is created **beside the destination**, inside
    the workspace-namespaced tree (§10.5), never in the OS temp directory.
    """
    working = source
    scratch: Path | None = None
    # Before anything is written, including the scratch file — which also lives
    # here. Doing it later worked only because the caller happened to have
    # created the directory already, and a function that depends on that is a
    # function that breaks the first time someone calls it differently.
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        if fmt.is_delimited_text:
            chosen = _require_dialect(dialect, fmt)
            if not is_utf8(chosen.encoding):
                scratch = destination.with_name(f"{destination.name}.utf8")
                transcode_to_utf8(source, scratch, chosen.encoding)
                working = scratch

        lazy = _scan(working, fmt, dialect)
        _reject_unsplit_lazy(lazy, fmt, dialect)

        try:
            lazy.sink_parquet(destination, **PARQUET_WRITE_OPTIONS)
        except (pl.exceptions.PolarsError, ValueError, OSError) as exc:
            destination.unlink(missing_ok=True)
            if fmt.is_delimited_text and dialect is not None:
                raise IngestRejected(_explain_csv_failure(exc, dialect)) from exc
            raise IngestRejected(f"could not read this as {fmt.value}: {exc}") from exc
    finally:
        if scratch is not None:
            scratch.unlink(missing_ok=True)

    metadata = pl.read_parquet_schema(destination)
    row_count = pl.scan_parquet(destination).select(pl.len()).collect().item()

    # Checked after writing rather than before. Counting rows in a CSV means
    # scanning it, so checking first would cost a full extra pass on every
    # successful upload to catch a case the 500 MB limit already makes rare.
    # The file is removed, so nothing over the limit ever becomes a version.
    try:
        check_row_count(row_count)
    except IngestRejected:
        destination.unlink(missing_ok=True)
        raise

    return IngestedFile(
        content_hash=hash_file(destination),
        row_count=row_count,
        column_count=len(metadata),
        byte_size=destination.stat().st_size,
        columns=tuple(metadata),
    )


def _reject_unsplit_lazy(lazy: pl.LazyFrame, fmt: SourceFormat, dialect: Dialect | None) -> None:
    """The wrong-delimiter guard, without reading the whole file.

    ``collect_schema`` costs nothing and answers the only question that matters
    first: how many columns came out. Rows are only pulled when the answer is
    one, which is when the guard actually has work to do.
    """
    names = lazy.collect_schema().names()
    if len(names) < _MIN_COLUMNS:
        raise IngestRejected("the file produced no columns")
    _reject_duplicate_names(names)
    if len(names) != 1 or not fmt.is_delimited_text or dialect is None:
        return
    _reject_unsplit_rows(lazy.head(20).collect(), dialect)


__all__ = [
    "PARQUET_WRITE_OPTIONS",
    "READERS",
    "TRANSCODE_CHUNK_BYTES",
    "Dialect",
    "IngestedFile",
    "NormalizedTable",
    "Reader",
    "content_hash",
    "hash_file",
    "is_utf8",
    "normalize",
    "normalize_file",
    "read",
    "read_delimited",
    "read_json_records",
    "read_parquet",
    "read_sample",
    "read_xlsx",
    "to_parquet",
    "to_utf8",
    "transcode_to_utf8",
]
