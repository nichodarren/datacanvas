"""The file-based ingest path (``normalize_file``) and its encoding handling.

A real upload never goes through the in-memory path — a 500 MB file (NFR-SCALE.4)
cannot be held as ``bytes`` and then again as a frame. So this is the path that
matters in production, and it needs its own tests rather than inheriting
confidence from the in-memory one.

The property tying the two together is that **they must agree**: the same input
has to produce the same ``content_hash`` whichever path ingested it, or D-026
means nothing.
"""

from __future__ import annotations

import codecs
from pathlib import Path

import polars as pl
import pytest

from app.domain.enums import SourceFormat
from app.ingest import normalize
from app.ingest.dialect import Dialect, detect
from app.ingest.limits import IngestRejected

DATASETS = Path(__file__).resolve().parents[2] / "eval" / "datasets"

CSV = Dialect(delimiter=",", encoding="utf-8", has_header=True, confidence=1.0)
ORDERS = b"order_id,region,amount\n1,Jakarta,1500\n2,Medan,2300\n3,Solo,900\n"


def _write(tmp_path: Path, data: bytes, name: str = "in.csv") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


# --------------------------------------------------------- the two agree ----


@pytest.mark.invariant
def test_streaming_and_in_memory_produce_the_same_hash(tmp_path: Path) -> None:
    """One table, one ``content_hash`` — whichever path wrote it.

    Verified before the streaming path was relied on, and kept as a test because
    it is a property of two independent polars entry points. If a future release
    changes either, one CSV starts producing two different hashes depending on
    how it arrived, and every identity claim built on ``content_hash`` quietly
    stops meaning what it says.
    """
    in_memory = normalize.normalize(ORDERS, SourceFormat.CSV, CSV)
    streamed = normalize.normalize_file(
        _write(tmp_path, ORDERS), SourceFormat.CSV, tmp_path / "out.parquet", CSV
    )

    assert streamed.content_hash == in_memory.content_hash
    assert streamed.row_count == in_memory.row_count == 3
    assert streamed.column_count == in_memory.column_count == 3
    assert streamed.columns == ("order_id", "region", "amount")


@pytest.mark.golden
def test_the_messy_fixture_survives_the_file_path_too(tmp_path: Path) -> None:
    """FR-B.3's regression case, through the path a real upload takes."""
    raw = (DATASETS / "messy_sales.csv").read_bytes()
    dialect = detect(raw, is_prefix=False)

    result = normalize.normalize_file(
        _write(tmp_path, raw), SourceFormat.CSV, tmp_path / "out.parquet", dialect
    )

    assert result.row_count == 5_000
    assert "legacy_code" in result.columns
    assert result.content_hash == normalize.normalize(raw, SourceFormat.CSV, dialect).content_hash


# ------------------------------------------------------------- encoding -----


def test_a_cp1252_file_keeps_its_characters(tmp_path: Path) -> None:
    """The data-loss bug, at the layer that fixed it.

    ``utf8-lossy`` does not convert; it replaces. Every non-ASCII character in a
    cp1252 file became U+FFFD and nothing raised — while the dialect detector
    had reported ``cp1252`` correctly all along.
    """
    content = "kota,catatan\nBogor,café dekat alun-alun\nSolo,Jawa Barat — panas\n".encode("cp1252")
    dialect = detect(content, is_prefix=False)
    assert dialect.encoding == "cp1252"

    out = tmp_path / "out.parquet"
    normalize.normalize_file(_write(tmp_path, content), SourceFormat.CSV, out, dialect)

    values = pl.read_parquet(out)["catatan"].to_list()
    assert values == ["café dekat alun-alun", "Jawa Barat — panas"]


def test_transcoding_survives_a_character_split_across_chunks(tmp_path: Path) -> None:
    """The bug an incremental decoder exists to prevent.

    Decoding chunk-by-chunk with a plain ``decode`` corrupts one character per
    chunk boundary — a defect that scales with file size and is invisible on any
    file small enough to be a convenient fixture. Built here by making the file
    deliberately larger than the chunk size.
    """
    line = "kota,catatan\n"
    rows = "".join(f"Bogor,café panas — {i}\n" for i in range(120_000))
    content = (line + rows).encode("cp1252")
    assert len(content) > normalize.TRANSCODE_CHUNK_BYTES * 2, "must span several chunks"

    destination = tmp_path / "utf8.csv"
    normalize.transcode_to_utf8(_write(tmp_path, content), destination, "cp1252")

    text = destination.read_text(encoding="utf-8")
    assert "�" not in text, "a replacement character means a chunk boundary corrupted one"
    assert text.count("café panas — ") == 120_000


def test_a_utf8_bom_does_not_become_part_of_the_first_column_name(tmp_path: Path) -> None:
    """Invisible in every UI, and it breaks every lookup by name.

    ``utf-8-sig`` is deliberately *not* treated as plain UTF-8 by
    :func:`normalize.is_utf8`, precisely so this goes through transcoding.
    """
    content = codecs.BOM_UTF8 + ORDERS
    dialect = detect(content, is_prefix=False)
    assert dialect.encoding == "utf-8-sig"

    out = tmp_path / "out.parquet"
    result = normalize.normalize_file(_write(tmp_path, content), SourceFormat.CSV, out, dialect)
    assert result.columns[0] == "order_id"


def test_the_transcoding_scratch_file_does_not_survive(tmp_path: Path) -> None:
    """Whatever transcoding needs, it cleans up.

    The scratch file lives beside the destination — inside the workspace tree
    (§10.5), not in the OS temp directory — so a leak here would be user data
    left in the store with no row describing it.
    """
    content = "kota,catatan\nBogor,café\n".encode("cp1252")
    out = tmp_path / "nested" / "out.parquet"
    normalize.normalize_file(
        _write(tmp_path, content), SourceFormat.CSV, out, detect(content, is_prefix=False)
    )

    assert sorted(p.name for p in out.parent.iterdir()) == ["out.parquet"]


# ------------------------------------------------------------- refusals -----


def test_a_wrong_delimiter_is_refused_on_the_file_path_too(tmp_path: Path) -> None:
    """The guard has to exist on both paths, not just the one with a test."""
    wrong = Dialect(delimiter=";", encoding="utf-8", has_header=True, confidence=0.4)
    with pytest.raises(IngestRejected) as failure:
        normalize.normalize_file(
            _write(tmp_path, ORDERS), SourceFormat.CSV, tmp_path / "out.parquet", wrong
        )
    assert "','" in str(failure.value)


def test_a_refused_file_leaves_no_parquet_behind(tmp_path: Path) -> None:
    """A half-written output is not a version, and must not look like one."""
    wrong = Dialect(delimiter=";", encoding="utf-8", has_header=True, confidence=0.4)
    out = tmp_path / "out.parquet"
    with pytest.raises(IngestRejected):
        normalize.normalize_file(_write(tmp_path, ORDERS), SourceFormat.CSV, out, wrong)
    assert not out.exists()


def test_too_many_rows_is_refused_and_the_file_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NFR-SCALE.1, including the cleanup.

    The limit is checked *after* writing, because counting CSV rows means
    scanning the file and doing it twice would cost every successful upload to
    catch a case the 500 MB cap already makes rare. That trade is only
    acceptable if the oversized output does not survive.
    """
    monkeypatch.setattr("app.ingest.limits.MAX_ROWS", 2)
    monkeypatch.setattr("app.ingest.normalize.check_row_count", _reject_over_two)

    out = tmp_path / "out.parquet"
    with pytest.raises(IngestRejected, match="rows"):
        normalize.normalize_file(_write(tmp_path, ORDERS), SourceFormat.CSV, out, CSV)
    assert not out.exists()


def _reject_over_two(row_count: int) -> None:
    if row_count > 2:
        raise IngestRejected(f"file has {row_count} rows; the limit is 2 rows per dataset version")


def test_parquet_ingests_without_a_dialect(tmp_path: Path) -> None:
    source = tmp_path / "in.parquet"
    pl.DataFrame({"a": ["1", "2"], "b": ["x", "y"]}).write_parquet(source)

    result = normalize.normalize_file(source, SourceFormat.PARQUET, tmp_path / "out.parquet")

    assert result.columns == ("a", "b")
    assert result.row_count == 2


def test_an_unsupported_format_says_what_is_supported(tmp_path: Path) -> None:
    with pytest.raises(IngestRejected, match="csv"):
        normalize.normalize_file(
            _write(tmp_path, b'[{"a":1}]'), SourceFormat.JSON, tmp_path / "out.parquet"
        )
