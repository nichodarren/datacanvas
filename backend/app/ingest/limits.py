"""Resource limits for ingest (NFR-SCALE.4, §13.6).

These are policy, not tuning. §8 is explicit that a limit which is assumed
rather than enforced is worse than no limit at all: *"produk yang diam-diam
melambat di 10 juta baris jauh lebih merusak kepercayaan daripada produk yang
jujur menolak di 5 juta."* So every number here has somewhere that rejects, and
every rejection says which limit was hit.

Kept in one module so the answer to "what are the limits?" is a file, not a
search.
"""

from __future__ import annotations

from typing import Final

from app.domain.errors import DomainError

#: NFR-SCALE.4. Above this an upload is refused, with the limit named.
MAX_UPLOAD_BYTES: Final = 500 * 1024 * 1024

#: D-025: how much of the file the preview endpoint reads. Large enough that
#: dialect detection sees many rows of a wide table, small enough that it costs
#: nothing to send. The preview keeps none of it.
PREVIEW_BYTES: Final = 1024 * 1024

#: How many parsed rows a preview returns. The user is confirming a dialect, not
#: reading the data — the grid (FR-D.1) is where reading happens.
PREVIEW_ROWS: Final = 50

#: NFR-SCALE.1, enforced at ingest rather than discovered during analysis.
MAX_ROWS: Final = 5_000_000

#: Zip-bomb ceiling (§13.6). XLSX is a ZIP archive, so it is the one format
#: where a small upload can expand without bound. Applies to the *sum* of
#: uncompressed member sizes, because a bomb is usually many small entries
#: rather than one large one.
MAX_DECOMPRESSION_RATIO: Final = 100

#: Seconds a single parse attempt may run before it is abandoned (§13.6).
#: D-027 accepts a file by parsing it, which means a malicious file gets to
#: choose how much work we do — unless we choose first.
PARSE_TIMEOUT_SECONDS: Final = 120


class IngestRejected(DomainError):
    """The upload was refused, with a reason a user can act on.

    Ingest failures are shown to people, so they are not exceptions to be
    logged and swallowed (P6, NFR-REL.2). Every raise site states what was
    wrong and, wherever there is one, what to do about it.
    """


def check_upload_size(byte_size: int) -> None:
    if byte_size < 0:
        raise IngestRejected("upload size cannot be negative")
    if byte_size == 0:
        raise IngestRejected("the file is empty")
    if byte_size > MAX_UPLOAD_BYTES:
        raise IngestRejected(
            f"file is {byte_size / 1024 / 1024:.1f} MB; the limit is "
            f"{MAX_UPLOAD_BYTES // 1024 // 1024} MB per upload (NFR-SCALE.4)"
        )


def check_row_count(row_count: int) -> None:
    if row_count > MAX_ROWS:
        raise IngestRejected(
            f"file has {row_count:,} rows; the limit is {MAX_ROWS:,} per dataset version "
            f"(NFR-SCALE.1). Filter or split the file before uploading."
        )


def check_decompression_ratio(compressed: int, uncompressed: int) -> None:
    """Guard the one format where a small file can become a large one.

    ``compressed <= 0`` is treated as a rejection rather than as a division to
    avoid: a zero-byte archive claiming megabytes of contents is exactly the
    shape of the attack.
    """
    if compressed <= 0:
        raise IngestRejected("archive reports no compressed size")
    ratio = uncompressed / compressed
    if ratio > MAX_DECOMPRESSION_RATIO:
        raise IngestRejected(
            f"archive expands {ratio:.0f}x, above the {MAX_DECOMPRESSION_RATIO}x limit "
            f"(§13.6 decompression bomb)"
        )


__all__ = [
    "MAX_DECOMPRESSION_RATIO",
    "MAX_ROWS",
    "MAX_UPLOAD_BYTES",
    "PARSE_TIMEOUT_SECONDS",
    "PREVIEW_BYTES",
    "PREVIEW_ROWS",
    "IngestRejected",
    "check_decompression_ratio",
    "check_row_count",
    "check_upload_size",
]
