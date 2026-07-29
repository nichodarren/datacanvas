"""Working out what an upload is, before anything is committed.

Covers the three guesses FR-B.3 requires be shown for correction — encoding,
delimiter, header row — plus format acceptance under D-027.

The bar for these is not "always right". FR-B.3 puts a human in front of the
answer, so the bar is: right on ordinary files, and wrong in a way that is
visible. What must never happen is being wrong *silently* — the header case
below is the sharp edge, because a data row mistaken for a header deletes a row
and names the columns after it.
"""

from __future__ import annotations

import codecs
import io
import re

import polars as pl
import pytest

from app.domain.enums import SourceFormat
from app.ingest import formats, text
from app.ingest.dialect import (
    SINGLE_COLUMN_DELIMITER,
    detect,
    detect_delimiter,
    detect_header,
)
from app.ingest.limits import IngestRejected, check_decompression_ratio, check_upload_size

# --------------------------------------------------------------- encoding ---


def test_utf8_is_recognised_without_a_bom() -> None:
    decoded = text.decode(b"nama,kota\nBudi,Yogyakarta\n")
    assert decoded.encoding == "utf-8"
    assert "Yogyakarta" in decoded.text


def test_utf8_bom_is_consumed_rather_than_left_in_the_first_column_name() -> None:
    """A BOM left in place becomes part of column one's name.

    It is invisible in every UI, so the column looks correctly named and every
    lookup by that name fails. Worth its own test because the symptom never
    points at the cause.
    """
    decoded = text.decode(codecs.BOM_UTF8 + b"id,amount\n1,2\n")
    assert decoded.text.startswith("id,")


@pytest.mark.parametrize(
    ("bom", "encoding"),
    [(codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF16_BE, "utf-16-be")],
)
def test_utf16_is_detected_from_its_bom(bom: bytes, encoding: str) -> None:
    decoded = text.decode(bom + "a,b\n".encode(encoding))
    assert decoded.encoding == encoding
    assert decoded.text == "a,b\n"


def test_windows_encoded_bytes_fall_back_to_cp1252() -> None:
    """The common non-UTF-8 case: whatever Excel wrote on a Windows machine."""
    decoded = text.decode("kota;provinsi\nBogor;Jawa Barat — panas\n".encode("cp1252"))
    assert decoded.encoding == text.FALLBACK_ENCODING
    assert "Jawa Barat — panas" in decoded.text


@pytest.mark.parametrize("undefined", [b"\x81", b"\x8d", b"\x8f", b"\x90", b"\x9d"])
def test_decoding_never_raises_whatever_the_bytes_are(undefined: bytes) -> None:
    """The promise the whole ladder exists to keep: an encoding never blocks ingest.

    Written first as an assertion about cp1252 alone, which is how it was
    discovered that cp1252 leaves these five bytes undefined and raises on them.
    A "safe last resort" that raises is not one — hence the latin-1 rung, which
    maps all 256 bytes by construction.
    """
    decoded = text.decode(b"kota;provinsi\nBogor;Jawa Barat\n" + undefined)
    assert decoded.encoding == text.TOTAL_FALLBACK_ENCODING
    assert "Bogor" in decoded.text


def test_every_possible_byte_decodes() -> None:
    """The property above, stated exhaustively rather than by example."""
    decoded = text.decode(bytes(range(256)))
    assert len(decoded.text) == 256


def test_a_prefix_cut_through_a_character_is_still_utf8() -> None:
    """The bug this prevents appears and disappears with file size.

    Slice a UTF-8 file at a fixed byte count and sooner or later the cut lands
    inside a multi-byte character. Without trimming, that file is reported as
    cp1252 and the preview shows mojibake — for a file that is perfectly good
    UTF-8, and only for some upload sizes.
    """
    full = "nama,kota\nBudi,Yogyakarta — kota pelajar\n".encode()
    cut = full[: full.index("—".encode()) + 1]  # one byte into a 3-byte character

    assert text.decode(cut, is_prefix=False).encoding == text.FALLBACK_ENCODING
    prefix = text.decode(cut, is_prefix=True)
    assert prefix.encoding == "utf-8"
    assert prefix.truncated


def test_a_complete_file_is_never_silently_repaired() -> None:
    """Same bytes, different claim: for a whole file, a partial character is corruption."""
    broken = b"amount\n1\n" + b"\xe2\x80"
    assert text.decode(broken, is_prefix=False).encoding == text.FALLBACK_ENCODING


def test_partial_last_line_is_dropped_only_when_incomplete() -> None:
    assert text.drop_partial_last_line("a,b\nc,d\ne,") == "a,b\nc,d\n"
    assert text.drop_partial_last_line("a,b\nc,d\n") == "a,b\nc,d\n"
    assert text.drop_partial_last_line("only-one-partial-line") == ""


# -------------------------------------------------------------- delimiters ---


@pytest.mark.parametrize("delimiter", [",", ";", "\t", "|"])
def test_each_candidate_delimiter_is_found(delimiter: str) -> None:
    rows = (("a", "b", "c"), ("1", "2", "3"), ("4", "5", "6"))
    body = "\n".join(delimiter.join(row) for row in rows)
    found, confidence = detect_delimiter(body + "\n")
    assert found == delimiter
    assert confidence == 1.0


def test_consistency_beats_frequency() -> None:
    """The case that defeats "pick the most common character".

    Every row here contains more commas than semicolons, because a text column
    is full of them. Only the semicolon splits every row into the same number of
    fields, and that is what makes it the delimiter.
    """
    body = (
        "id;description;city\n"
        "1;Jakarta, Bandung, Surabaya;JKT\n"
        "2;Medan, Padang;MDN\n"
        "3;Solo, Semarang, Kudus, Salatiga;SLO\n"
    )
    delimiter, confidence = detect_delimiter(body)
    assert delimiter == ";"
    assert confidence == 1.0


def test_quoted_delimiters_do_not_change_the_answer() -> None:
    """Titanic's ``Name`` column is exactly this shape: ``"Braund, Mr. Owen"``."""
    body = 'id,name,fare\n1,"Braund, Mr. Owen",7.25\n2,"Cumings, Mrs. John",71.28\n'
    assert detect_delimiter(body)[0] == ","


def test_ragged_rows_lower_confidence_rather_than_being_hidden() -> None:
    """A file that does not split evenly must say so — that is what the UI shows."""
    body = "a,b,c\n1,2,3\n4,5\n6,7,8,9\n10,11,12\n"
    _, confidence = detect_delimiter(body)
    assert confidence < 1.0


def test_a_file_where_nothing_splits_is_a_single_column_file() -> None:
    """This test used to assert a refusal, and the assertion was wrong.

    "No separator found" is an answer, not a failure: a list of order ids is an
    ordinary CSV that FR-B.1 says we accept, and refusing it refused a real
    file. With one column every candidate delimiter yields the same table, so
    there is nothing to get wrong and nothing to ask the user about.

    The genuinely broken single-column case — rows never split because the
    delimiter was wrong — is caught in ``normalize``, which can tell the two
    apart because that one is visibly full of some other separator.
    """
    delimiter, confidence = detect_delimiter("one\ntwo\nthree\n")
    assert delimiter == SINGLE_COLUMN_DELIMITER
    assert confidence == 1.0


# ------------------------------------------------------------------ header ---


def test_text_row_over_numeric_columns_is_a_header() -> None:
    rows = [["order_id", "amount"], ["1", "1500"], ["2", "2300"], ["3", "900"]]
    assert detect_header(rows) is True


def test_numeric_first_row_over_numeric_columns_is_data() -> None:
    """The expensive mistake, tested from the side that loses a row."""
    rows = [["1", "1500"], ["2", "2300"], ["3", "900"], ["4", "1200"]]
    assert detect_header(rows) is False


def test_a_repeated_value_in_row_zero_rules_out_a_header() -> None:
    """Column names are unique (§9.2); a row with repeats cannot be one."""
    rows = [["Jakarta", "Jakarta"], ["Bandung", "Medan"], ["Solo", "Padang"]]
    assert detect_header(rows) is False


def test_an_all_text_file_defaults_to_having_a_header() -> None:
    """No signal either way. The default is chosen by which error is worse.

    Treating a header as data adds one odd-looking row, which someone notices.
    Treating data as a header removes a row and misnames every column, which
    nobody notices.
    """
    rows = [["city", "province"], ["Bogor", "Jawa Barat"], ["Solo", "Jawa Tengah"]]
    assert detect_header(rows) is True


def test_detect_reports_all_three_guesses_together() -> None:
    dialect = detect(b"id;kota\n1;Bogor\n2;Solo\n", is_prefix=False)
    assert (dialect.delimiter, dialect.encoding, dialect.has_header) == (";", "utf-8", True)
    assert dialect.as_options() == {"delimiter": ";", "encoding": "utf-8", "has_header": True}


# ------------------------------------------------------------------ format ---


def test_parquet_is_recognised_by_its_signature() -> None:
    buffer = io.BytesIO()
    pl.DataFrame({"a": [1, 2]}).write_parquet(buffer)
    blob = buffer.getvalue()
    assert formats.sniff(blob, filename="mystery.bin", tail=blob[-8:]) is SourceFormat.PARQUET


def test_content_wins_over_extension_in_both_directions() -> None:
    """D-027 stated as the two cases that make it a rule rather than a preference."""
    buffer = io.BytesIO()
    pl.DataFrame({"a": [1]}).write_parquet(buffer)
    parquet = buffer.getvalue()

    assert formats.sniff(parquet, filename="report.csv", tail=parquet[-8:]) is SourceFormat.PARQUET
    assert formats.sniff(b"a,b\n1,2\n", filename="data.parquet") is SourceFormat.CSV


def test_a_truncated_parquet_says_so_instead_of_being_read_as_text() -> None:
    with pytest.raises(IngestRejected, match="truncated"):
        formats.sniff(b"PAR1\x00\x01\x02\x03", filename="x.parquet", tail=b"\x00\x01\x02\x03")


def test_tsv_and_csv_are_told_apart_by_the_extension_hint_only() -> None:
    """The one tie the extension is allowed to break, and the reason it is safe.

    Both answers are delimited text; the delimiter recorded in ``ingest_options``
    comes from the dialect detector either way, so the hint decides a label and
    not how the file is read.
    """
    body = b"a\tb\n1\t2\n"
    assert formats.sniff(body, filename="x.tsv") is SourceFormat.TSV
    assert formats.sniff(body, filename="x.csv") is SourceFormat.CSV
    assert detect(body, is_prefix=False).delimiter == "\t"


def test_json_records_are_recognised_from_a_prefix() -> None:
    assert formats.sniff(b'[{"a": 1}, {"a": 2}] ', filename="x.json") is SourceFormat.JSON


def test_a_zip_that_is_not_a_workbook_is_refused_by_name() -> None:
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")

    with pytest.raises(IngestRejected, match="not an Excel workbook"):
        formats.sniff(buffer.getvalue(), filename="book.xlsx")


def test_an_empty_upload_is_refused(tmp_path_factory: pytest.TempPathFactory) -> None:
    del tmp_path_factory
    with pytest.raises(IngestRejected, match="empty"):
        formats.sniff(b"", filename="x.csv")


# ------------------------------------------------------------------ limits ---


def test_upload_size_limit_names_itself() -> None:
    with pytest.raises(IngestRejected, match=re.escape("NFR-SCALE.4")):
        check_upload_size(600 * 1024 * 1024)
    with pytest.raises(IngestRejected, match="empty"):
        check_upload_size(0)


def test_decompression_ratio_is_refused_before_anything_expands() -> None:
    check_decompression_ratio(compressed=1_000, uncompressed=50_000)
    with pytest.raises(IngestRejected, match="decompression bomb"):
        check_decompression_ratio(compressed=1_000, uncompressed=50_000_000)


def test_an_archive_claiming_no_compressed_size_is_refused_not_divided_by() -> None:
    with pytest.raises(IngestRejected):
        check_decompression_ratio(compressed=0, uncompressed=1_000_000)
