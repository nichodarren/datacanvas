"""Reading uploads and writing normalized Parquet (FR-B.3, FR-B.4, D-026, D-027).

The most important test here is the determinism one. INV-6 says *fingerprint
sama ⟹ hasil sama*, and ``content_hash`` can only carry that if writing the same
table twice produces the same bytes. D-026 pins the write options for exactly
this reason, and this is where the pin is held down.
"""

from __future__ import annotations

import io
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq
import pytest

from app.domain.enums import SourceFormat
from app.ingest import normalize
from app.ingest.dialect import Dialect, detect
from app.ingest.limits import IngestRejected, check_row_count

DATASETS = Path(__file__).resolve().parents[2] / "eval" / "datasets"

CSV = Dialect(delimiter=",", encoding="utf-8", has_header=True, confidence=1.0)


def _frame() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "order_id": ["1", "2", "3"],
            "region": ["Jakarta", "Surabaya", "Medan"],
            "amount": ["1500.5", "2300.0", "900.25"],
        }
    )


# ------------------------------------------------------------ determinism ---


@pytest.mark.invariant
def test_the_same_table_writes_the_same_bytes_every_time() -> None:
    """INV-6 at the level ``content_hash`` depends on.

    Not "usually the same": a hash that changes between two writes of one table
    would make every identity claim built on it meaningless, and the failure
    would look like a caching bug rather than a serialisation one.
    """
    written = {normalize.to_parquet(_frame()) for _ in range(10)}
    assert len(written) == 1


@pytest.mark.invariant
def test_the_same_csv_ingests_to_the_same_hash() -> None:
    """End to end, because that is the path a re-upload actually takes."""
    raw = b"order_id,region\n1,Jakarta\n2,Medan\n"
    hashes = {normalize.normalize(raw, SourceFormat.CSV, CSV).content_hash for _ in range(5)}
    assert len(hashes) == 1


def test_a_different_table_gets_a_different_hash() -> None:
    """Determinism is only worth having if the hash still distinguishes things."""
    one = normalize.normalize(b"a\n1\n", SourceFormat.CSV, CSV)
    two = normalize.normalize(b"a\n2\n", SourceFormat.CSV, CSV)
    assert one.content_hash != two.content_hash


def test_write_options_are_pinned_rather_than_inherited() -> None:
    """The pin is load-bearing, not decorative — shown by what it changes.

    polars' default embeds each column's min and max in the footer, so a salary
    column ships its highest and lowest salary as metadata. Ours does not. If
    someone drops the pinned options, this fails instead of quietly changing
    what every Parquet file carries.
    """
    frame = pl.DataFrame({"salary": [11_111_111, 5_000], "name": ["a", "b"]})

    default = io.BytesIO()
    frame.write_parquet(default)
    default_stats = pq.read_metadata(io.BytesIO(default.getvalue())).row_group(0)
    assert default_stats.column(0).statistics is not None

    pinned = pq.read_metadata(io.BytesIO(normalize.to_parquet(frame))).row_group(0)
    assert all(pinned.column(i).statistics is None for i in range(pinned.num_columns))


# --------------------------------------------------------------- reading ----


def test_every_column_is_read_as_text() -> None:
    """FR-B.3: inference is a later, whole-file step — never a side effect of reading.

    Reading as text is what makes a full scan possible at all. It also means the
    reader cannot fail on a value that contradicts a type it guessed, because it
    guessed nothing.
    """
    frame = normalize.read(b"n,when\n1,2024-01-01\n2,2024-02-01\n", SourceFormat.CSV, CSV)
    assert set(frame.dtypes) == {pl.String}


@pytest.mark.golden
def test_the_column_that_broke_sample_based_inference_survives() -> None:
    """FR-B.3's rationale, kept as a regression test against the real file.

    ``messy_sales.legacy_code`` is 97% digits and its first alphanumeric value
    sits far past any sample window, so sample-based inference guesses integer
    and then explodes mid-file. This is the failure that made "scan the whole
    file" a requirement rather than a preference; it deserves a test that uses
    the actual bytes, not a reconstruction of them.
    """
    raw = (DATASETS / "messy_sales.csv").read_bytes()
    dialect = detect(raw, is_prefix=False)

    table = normalize.normalize(raw, SourceFormat.CSV, dialect)

    assert table.row_count == 5_000
    assert "legacy_code" in table.frame.columns
    codes = table.frame["legacy_code"].drop_nulls().to_list()
    assert any(not code.isdigit() for code in codes), (
        "the non-numeric values are what makes this file the regression case"
    )


def test_a_headerless_file_gets_positional_names() -> None:
    dialect = Dialect(delimiter=",", encoding="utf-8", has_header=False, confidence=1.0)
    frame = normalize.read(b"1,Jakarta\n2,Medan\n", SourceFormat.CSV, dialect)
    assert frame.columns == ["column_1", "column_2"]
    assert frame.height == 2


def test_parquet_round_trips_without_a_dialect() -> None:
    buffer = io.BytesIO()
    _frame().write_parquet(buffer)
    frame = normalize.read(buffer.getvalue(), SourceFormat.PARQUET)
    assert frame.columns == ["order_id", "region", "amount"]


# -------------------------------------------------------------- refusals ----


def test_a_wrong_delimiter_is_refused_instead_of_silently_succeeding() -> None:
    """The failure mode this test was written to prove *does not* exist — and did.

    Reading a comma file with ``;`` does not raise. Every row becomes one long
    field and ingest reports success on a single-column table of unsplit lines,
    which then gets committed, profiled and analysed. D-025 accepts that a
    dialect detected from a prefix can be wrong; that is only tolerable if being
    wrong is loud.
    """
    wrong = Dialect(delimiter=";", encoding="utf-8", has_header=True, confidence=0.4)
    with pytest.raises(IngestRejected) as failure:
        normalize.read(b"a,b,c\n1,2,3\n4,5,6\n", SourceFormat.CSV, wrong)

    message = str(failure.value)
    assert "';'" in message, "must name the delimiter that was used"
    assert "','" in message, "must name the one to try instead"


def test_a_genuinely_single_column_file_is_still_accepted() -> None:
    """The control for the test above.

    Without this, "reject one-column results" would pass every test while
    breaking a list of ids — a legitimate upload, and the reason the check keys
    on the presence of another delimiter rather than on width alone.
    """
    frame = normalize.read(b"order_id\n1001\n1002\n1003\n", SourceFormat.CSV, CSV)
    assert frame.columns == ["order_id"]
    assert frame.height == 3


def test_a_short_row_is_padded_rather_than_refused() -> None:
    """Ordinary messiness in the data our persona actually receives.

    Written after measuring what polars does rather than assuming it. Refusing
    short rows would refuse most real files. The cost — the padded nulls look
    exactly like nulls that were in the file — is stated in ``read_delimited``
    and paid by profiling in Phase 4, not hidden.
    """
    frame = normalize.read(b"a,b,c\n1,2,3\n4,5\n", SourceFormat.CSV, CSV)
    assert frame.height == 2
    assert frame.row(1) == ("4", "5", None)


def test_a_row_with_extra_fields_fails_with_something_to_act_on() -> None:
    """The other half of the asymmetry: too many fields means the layout is wrong.

    NFR-REL.2 — a parse failure is a message naming what to reconsider, never a
    stack trace.
    """
    with pytest.raises(IngestRejected) as failure:
        normalize.read(b"a,b,c\n1,2,3\n4,5,6,7\n", SourceFormat.CSV, CSV)

    message = str(failure.value)
    assert "delimiter" in message
    assert "','" in message


def test_every_upload_format_has_a_reader() -> None:
    """FR-B.1 is complete, and this is what keeps it complete.

    Replaces a pair of tests that asserted an "unsupported format" message.
    Those became unreachable the moment XLSX and JSON landed — every member of
    ``SourceFormat`` now has a reader, so nothing could produce the message any
    more. Rather than delete the guard, the check moves to where the omission
    would actually happen: adding a format to the enum without adding a reader
    fails here, at the point of the omission, instead of at runtime for a user.
    """
    assert {fmt for fmt in SourceFormat} == set(normalize.READERS)


def test_a_file_with_only_a_header_is_refused() -> None:
    with pytest.raises(IngestRejected, match="no data rows"):
        normalize.read(b"a,b\n", SourceFormat.CSV, CSV)


def test_too_many_rows_is_refused_at_ingest_not_discovered_later() -> None:
    """NFR-SCALE.1 enforced where it can still be acted on.

    §8: honestly refusing at five million beats silently crawling at ten.
    """
    frame = pl.DataFrame({"a": ["1"]})
    with pytest.raises(IngestRejected, match="5,000,000"):
        check_row_count(frame.height + 5_000_000)


def test_delimited_reading_needs_a_dialect() -> None:
    with pytest.raises(IngestRejected, match="dialect"):
        normalize.read(b"a,b\n1,2\n", SourceFormat.CSV, None)
