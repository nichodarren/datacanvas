"""The pre-commit preview (D-025, §10.4 Alur 1, FR-B.3).

Reads the **beginning** of a file, reports how it would be parsed, and keeps
nothing. No storage write, no database row, no identifier handed back to be
redeemed later — which is what makes this the one part of ingest that touches
user data without needing a ``DataHandle``: there is nothing to authorize
access *to*, because nothing is retained.

What it cannot do is state a column's logical type. That is not a shortcut: FR-B.3
requires type inference to scan the whole file, and a prefix by definition is not
the whole file. §10.4 has always run inference after commit. What the user
corrects here is the dialect, and a dialect is legible from the first rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl

from app.domain.enums import SourceFormat
from app.ingest import formats
from app.ingest.dialect import Dialect, detect
from app.ingest.limits import PREVIEW_BYTES, PREVIEW_ROWS, IngestRejected, check_upload_size
from app.ingest.normalize import read_sample


@dataclass(frozen=True, slots=True)
class IngestPreview:
    """What the user confirms before anything is committed."""

    format: SourceFormat
    dialect: Dialect | None
    columns: tuple[str, ...]
    sample_rows: tuple[tuple[str, ...], ...]
    #: True when the server saw only part of the file — always true in practice,
    #: and surfaced so the UI can say so rather than implying it read everything.
    partial: bool
    #: Set when detection is shaky enough that the user should look twice
    #: (FR-C.6 applies the same idea to types). Never a reason to block.
    warnings: tuple[str, ...] = ()


def _stringify(value: object) -> str:
    """Sample cells are for looking at, not for computing with.

    Rendering them as text here keeps the preview response free of type
    questions that inference has not answered yet — and stops the UI from
    inferring a type from a JSON number, which would be a second, quieter
    inference path competing with the real one.
    """
    return "" if value is None else str(value)


def build(
    head: bytes,
    *,
    filename: str | None = None,
    declared_size: int | None = None,
) -> IngestPreview:
    """Describe how ``head`` would be parsed.

    ``head`` is at most :data:`PREVIEW_BYTES`; anything beyond that is dropped
    rather than refused, since the caller sending too much is not the user's
    mistake. ``declared_size`` is the size the client says the whole file is,
    checked against NFR-SCALE.4 **before** the upload rather than after — the
    point of a limit is not to find out afterwards.
    """
    if declared_size is not None:
        check_upload_size(declared_size)
    if not head:
        raise IngestRejected("nothing to preview")

    sample = head[:PREVIEW_BYTES]
    partial = len(head) > PREVIEW_BYTES or declared_size is None or declared_size > len(sample)

    fmt = formats.sniff(sample, filename=filename)
    warnings: list[str] = []

    if fmt.is_delimited_text:
        dialect = detect(sample, is_prefix=True)
        if dialect.confidence < 0.9:
            warnings.append(
                f"rows do not all split into the same number of fields using "
                f"{dialect.delimiter!r} — check the delimiter, or expect some rows to fail"
            )
        if partial:
            warnings.append("detected from the first part of the file only; later rows may differ")
    else:
        dialect = None

    frame, tolerated = _sample_frame(sample, fmt, dialect)
    warnings.extend(tolerated)
    return IngestPreview(
        format=fmt,
        dialect=dialect,
        columns=tuple(frame.columns),
        sample_rows=tuple(
            tuple(_stringify(cell) for cell in row) for row in frame.head(PREVIEW_ROWS).iter_rows()
        ),
        partial=partial,
        warnings=tuple(warnings),
    )


def _sample_frame(
    sample: bytes, fmt: SourceFormat, dialect: Dialect | None
) -> tuple[pl.DataFrame, tuple[str, ...]]:
    """Parse the prefix, tolerating the fact that it ends mid-file.

    A truncated final row is normal here and must not be reported as a broken
    file — that would turn every large upload into a scary preview. The last
    line is dropped before parsing rather than after a failed attempt, because
    a half row is not an error condition, it is what a prefix looks like.

    Anything :func:`normalize.read_sample` had to tolerate beyond that comes
    back as a note, so leniency is always visible.
    """
    if fmt.is_delimited_text:
        head, separator, _ = sample.rpartition(b"\n")
        if separator:
            sample = head + separator
    if not sample:
        raise IngestRejected("the first rows of this file are unreadable")
    return read_sample(sample, fmt, dialect)


__all__ = ["IngestPreview", "build"]
