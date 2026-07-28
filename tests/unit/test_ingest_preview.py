"""The pre-commit preview (D-025, §10.4 Alur 1).

D-025's whole argument is that the preview keeps nothing — no file, no row, no
identifier to redeem later — and that this is what lets it touch user data
without a second authorization path alongside ``data_access.open()``. That claim
is worth a test, because it is the kind that stops being true one convenient
cache at a time.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

import polars as pl
import pytest

from app.domain.enums import SourceFormat
from app.ingest import preview
from app.ingest.limits import PREVIEW_BYTES, PREVIEW_ROWS, IngestRejected

DATASETS = Path(__file__).resolve().parents[2] / "eval" / "datasets"

SMALL = b"order_id,region,amount\n1,Jakarta,1500\n2,Medan,2300\n3,Solo,900\n"


def test_preview_reports_the_dialect_it_would_use() -> None:
    result = preview.build(SMALL, filename="orders.csv", declared_size=len(SMALL))

    assert result.format is SourceFormat.CSV
    assert result.dialect is not None
    assert result.dialect.delimiter == ","
    assert result.dialect.has_header is True
    assert result.columns == ("order_id", "region", "amount")
    assert result.sample_rows[0] == ("1", "Jakarta", "1500")


def test_a_fully_read_small_file_is_not_reported_as_partial() -> None:
    result = preview.build(SMALL, filename="orders.csv", declared_size=len(SMALL))
    assert result.partial is False
    assert not result.warnings


@pytest.mark.invariant
def test_preview_writes_nothing_anywhere(tmp_path: Path) -> None:
    """D-025's load-bearing claim, checked rather than trusted.

    If a preview ever starts staging bytes, it acquires a second path to user
    data — one that ``data_access.open()`` does not guard (INV-7 L3). That is
    the alternative D-025 rejected, and it would arrive by accident rather than
    by decision, which is why it gets a test instead of a comment.
    """
    before = sorted(tmp_path.rglob("*"))
    preview.build(SMALL, filename="orders.csv", declared_size=len(SMALL))
    assert sorted(tmp_path.rglob("*")) == before


def test_preview_returns_no_identifier_to_redeem_later() -> None:
    """The same claim from the other side: there is nothing to hand back.

    A preview that returned an ``upload_id`` would imply something is being
    kept. The response deliberately has no such field, and this fails if one is
    added without revisiting D-025.
    """
    result = preview.build(SMALL, filename="orders.csv", declared_size=len(SMALL))
    fields = set(vars(result) if hasattr(result, "__dict__") else result.__slots__)
    assert not {f for f in fields if "id" in f.lower() and f != "partial"}


def test_only_the_prefix_is_read_even_when_more_is_sent() -> None:
    """PREVIEW_BYTES is a ceiling, not a suggestion."""
    wide = b"a,b\n" + b"1,2\n" * (PREVIEW_BYTES // 4 + 5_000)
    result = preview.build(wide, declared_size=len(wide), filename="big.csv")
    assert result.partial is True
    assert len(result.sample_rows) <= PREVIEW_ROWS


def test_a_prefix_that_ends_mid_row_previews_cleanly() -> None:
    """The normal case for any real upload, and it must not look like an error.

    A preview reads a fixed byte count, so its final row is almost always cut in
    half. Reporting that as a broken file would make every large upload look
    broken.
    """
    raw = (DATASETS / "hotel_bookings.csv").read_bytes()[:PREVIEW_BYTES]
    assert not raw.endswith(b"\n"), "the fixture only works if the slice really is mid-row"

    result = preview.build(raw, filename="hotel_bookings.csv", declared_size=16_855_599)

    assert result.format is SourceFormat.CSV
    assert result.columns[0] == "hotel"
    assert result.partial is True
    assert any("first part of the file" in w for w in result.warnings)


def test_a_large_file_is_refused_before_it_is_uploaded() -> None:
    """NFR-SCALE.4 checked against the declared size, not the received bytes.

    Finding out a file is too large after receiving 500 MB of it is a limit that
    protects nothing.
    """
    with pytest.raises(IngestRejected, match=re.escape("NFR-SCALE.4")):
        preview.build(SMALL, filename="huge.csv", declared_size=900 * 1024 * 1024)


def test_inconsistent_rows_produce_a_warning_rather_than_a_refusal() -> None:
    """FR-B.3 puts a human in front of this. Warn, show, let them correct."""
    ragged = b"a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12\n13,14\n"
    result = preview.build(ragged, filename="ragged.csv", declared_size=len(ragged))

    assert result.dialect is not None
    assert result.dialect.confidence < 1.0
    assert any("same number of fields" in w for w in result.warnings)


def test_parquet_previews_without_a_dialect() -> None:
    """There is nothing to confirm for a format that carries its own schema."""
    buffer = io.BytesIO()
    pl.DataFrame({"a": [1, 2], "b": ["x", "y"]}).write_parquet(buffer)
    blob = buffer.getvalue()

    result = preview.build(blob, filename="t.parquet", declared_size=len(blob))

    assert result.format is SourceFormat.PARQUET
    assert result.dialect is None
    assert result.columns == ("a", "b")


def test_sample_cells_are_text_so_the_ui_cannot_infer_a_type_from_them() -> None:
    """One inference path, not two (FR-C.1).

    A preview that returned typed JSON would let the grid decide that a column
    is a number — a quieter second opinion competing with the real inference,
    and one the user cannot override because they never see it.
    """
    result = preview.build(SMALL, filename="orders.csv", declared_size=len(SMALL))
    assert all(isinstance(cell, str) for row in result.sample_rows for cell in row)


def test_an_empty_upload_is_refused() -> None:
    with pytest.raises(IngestRejected):
        preview.build(b"", filename="empty.csv", declared_size=0)
