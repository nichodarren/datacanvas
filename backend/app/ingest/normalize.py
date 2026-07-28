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

import hashlib
import io
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

import polars as pl

from app.domain.enums import SourceFormat
from app.ingest.dialect import CANDIDATE_DELIMITERS, Dialect
from app.ingest.limits import IngestRejected, check_row_count

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
PARQUET_WRITE_OPTIONS: Final[dict[str, object]] = {
    "compression": "zstd",
    "compression_level": 3,
    "statistics": False,
    "row_group_size": 122_880,
}

#: A table has to have at least one column. The *interesting* single-column
#: case — rows that were never split because the delimiter was wrong — is
#: :func:`_reject_unsplit_rows`, not this.
_MIN_COLUMNS: Final = 1

#: A reader turns bytes plus an optional dialect into a frame, or raises.
Reader = Callable[[bytes, Dialect | None], pl.DataFrame]


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    """A table on its way to becoming a DatasetVersion."""

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
            io.BytesIO(data),
            separator=chosen.delimiter,
            has_header=chosen.has_header,
            encoding="utf8" if chosen.encoding.startswith("utf-8") else "utf8-lossy",
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
    must be exact — it produces the DatasetVersion every later number depends
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


#: One entry per format. Adding XLSX and JSON is one reader and one line here.
READERS: Final[dict[SourceFormat, Reader]] = {
    SourceFormat.CSV: read_delimited,
    SourceFormat.TSV: read_delimited,
    SourceFormat.PARQUET: read_parquet,
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
    counts = Counter(frame.columns)
    duplicates = sorted(name for name, n in counts.items() if n > 1)
    if duplicates:
        raise IngestRejected(
            f"column names must be unique; these repeat: {', '.join(duplicates)}. "
            "Rename them in the source file before uploading."
        )


def to_parquet(frame: pl.DataFrame) -> bytes:
    """Serialise with every option pinned (D-026)."""
    buffer = io.BytesIO()
    frame.write_parquet(buffer, **PARQUET_WRITE_OPTIONS)  # type: ignore[arg-type]
    return buffer.getvalue()


def content_hash(parquet: bytes) -> str:
    """SHA-256 of the normalized Parquet (§9.2).

    Identity and integrity — **not** a dedup key. D-026 explains why the earlier
    claim was withdrawn: this hash is a property of the writer as much as of the
    data, and nothing in the MVP deduplicates anything.
    """
    return hashlib.sha256(parquet).hexdigest()


def normalize(data: bytes, fmt: SourceFormat, dialect: Dialect | None = None) -> NormalizedTable:
    """The whole path from uploaded bytes to something ready to be committed."""
    frame = read(data, fmt, dialect)
    parquet = to_parquet(frame)
    return NormalizedTable(frame=frame, parquet=parquet, content_hash=content_hash(parquet))


__all__ = [
    "PARQUET_WRITE_OPTIONS",
    "READERS",
    "NormalizedTable",
    "Reader",
    "content_hash",
    "normalize",
    "read",
    "read_delimited",
    "read_parquet",
    "read_sample",
    "to_parquet",
]
