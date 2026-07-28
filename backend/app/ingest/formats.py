"""Deciding what an upload is (D-027, §13.6.1).

The rule: **a file is format F if and only if it parses as F.** The extension
only decides what we try first. Three of the five formats FR-B.1 requires — CSV,
TSV, JSON — have no signature at all, so any rule phrased purely in terms of
magic bytes can only cover two of them and quietly falls back to the extension
for the rest. That is the failure D-027 exists to prevent.

What lives here is the *ordering* half: cheap signatures where they exist, cheap
structural hints where they do not. Acceptance itself happens in the reader,
which either parses the file or refuses it. Nothing here is trusted enough to
skip that step.
"""

from __future__ import annotations

import zipfile
from io import BytesIO
from typing import Final

from app.domain.enums import SourceFormat
from app.ingest.limits import IngestRejected, check_decompression_ratio
from app.ingest.text import decode, drop_partial_last_line

#: The only two signatures that exist among our formats.
PARQUET_MAGIC: Final = b"PAR1"
ZIP_MAGIC: Final = b"PK\x03\x04"

#: A ZIP is only an XLSX if it contains a workbook. Without this check every
#: .jar, .docx and .apk on the machine is "a spreadsheet" until the reader says
#: otherwise, and the error the user gets names the wrong problem.
_XLSX_MARKER: Final = "xl/workbook.xml"

_EXTENSION_HINTS: Final = {
    "csv": SourceFormat.CSV,
    "tsv": SourceFormat.TSV,
    "tab": SourceFormat.TSV,
    "txt": SourceFormat.CSV,
    "parquet": SourceFormat.PARQUET,
    "pq": SourceFormat.PARQUET,
    "xlsx": SourceFormat.XLSX,
    "json": SourceFormat.JSON,
}


def extension_hint(filename: str | None) -> SourceFormat | None:
    """What the filename claims. A claim, never a conclusion (D-027)."""
    if not filename or "." not in filename:
        return None
    return _EXTENSION_HINTS.get(filename.rsplit(".", 1)[-1].strip().lower())


def looks_like_parquet(head: bytes, tail: bytes | None = None) -> bool:
    """``PAR1`` opens and closes every Parquet file.

    ``tail`` is optional because a preview only ever holds the head. Checking
    both is strictly better — the footer is the authoritative one, and a file
    that starts with ``PAR1`` but does not end with it is truncated rather than
    unreadable, which is a more useful thing to tell someone.
    """
    if not head.startswith(PARQUET_MAGIC):
        return False
    if tail is None:
        return True
    return tail.endswith(PARQUET_MAGIC)


def looks_like_xlsx(data: bytes) -> bool:
    """A ZIP archive that actually contains a workbook.

    Reading the central directory also gives the declared uncompressed sizes,
    which is the only chance to refuse a decompression bomb *before* expanding
    anything (§13.6). Doing it later means doing it after the damage.
    """
    if not data.startswith(ZIP_MAGIC):
        return False
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            if _XLSX_MARKER not in names:
                return False
            uncompressed = sum(info.file_size for info in archive.infolist())
    except (zipfile.BadZipFile, OSError):
        # A truncated prefix of a real XLSX lands here. Saying "not XLSX" is
        # correct for the prefix we were given; the commit path sees the whole
        # file and gets the final word.
        return False

    check_decompression_ratio(len(data), uncompressed)
    return True


def looks_like_json_records(text: str) -> bool:
    """FR-B.1 accepts *array of objects* JSON, not arbitrary JSON.

    Detected structurally rather than by parsing, because a preview holds a
    prefix and a prefix of a valid JSON array is never itself valid JSON. A
    leading ``[`` followed by a ``{`` is as much as a prefix can honestly say.
    """
    stripped = text.lstrip()
    if not stripped.startswith("["):
        return False
    rest = stripped[1:].lstrip()
    return rest.startswith("{")


def sniff(data: bytes, *, filename: str | None = None, tail: bytes | None = None) -> SourceFormat:
    """Best available answer from the bytes in hand.

    Signatures first because they are decisive and cost nothing. Then structure.
    The extension hint breaks the remaining tie between CSV and TSV *only* — the
    one place where two formats are genuinely indistinguishable without looking
    at delimiters, and where :mod:`app.ingest.dialect` is about to look anyway.

    Raises :class:`IngestRejected` when nothing matches, rather than returning a
    default. A wrong guess here becomes a confusing parse error three steps
    later; an honest refusal here names the actual problem (P6).
    """
    if not data:
        raise IngestRejected("the file is empty")

    if looks_like_parquet(data, tail):
        return SourceFormat.PARQUET
    if data.startswith(PARQUET_MAGIC) and tail is not None:
        raise IngestRejected(
            "this looks like a Parquet file but its footer is missing — "
            "the upload is probably truncated"
        )
    if data.startswith(ZIP_MAGIC):
        if looks_like_xlsx(data):
            return SourceFormat.XLSX
        raise IngestRejected(
            "this is a ZIP archive but not an Excel workbook. Upload the .xlsx itself, "
            "not an archive containing it."
        )

    decoded = decode(data, is_prefix=tail is None)
    text = drop_partial_last_line(decoded.text) or decoded.text

    if looks_like_json_records(text):
        return SourceFormat.JSON

    if not text.strip():
        raise IngestRejected("the file contains no readable text")

    hint = extension_hint(filename)
    if hint in {SourceFormat.CSV, SourceFormat.TSV}:
        return hint
    # No usable hint: let the delimiter decide, which is what the dialect
    # detector does next anyway. CSV is the label for "delimited text" here and
    # the detected delimiter is what actually gets recorded in ingest_options.
    return SourceFormat.CSV


__all__ = [
    "PARQUET_MAGIC",
    "ZIP_MAGIC",
    "extension_hint",
    "looks_like_json_records",
    "looks_like_parquet",
    "looks_like_xlsx",
    "sniff",
]
