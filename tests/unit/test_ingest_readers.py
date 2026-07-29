"""XLSX and JSON readers (FR-B.1).

Both formats carry their own types, and both throw them away here. That is the
decision worth testing: CSV has no choice about arriving as text, and letting
XLSX and JSON arrive typed would mean **two inference paths** — one over
strings, one over whatever the source claimed — where D-029's rules are written
for the first.

Discarding Excel's opinion costs little. Excel is the program that turns gene
names into dates; re-deriving the type from the value loses a guess, not an
authority. What must survive is the *shape*, and that is most of what is tested
below.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from pathlib import Path

import openpyxl
import pytest

from app.domain.enums import LogicalType, SourceFormat
from app.ingest import formats, normalize
from app.ingest.limits import IngestRejected
from app.schema.inference import build_columns
from app.storage.engine import ColumnStatistics


def _cell(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> dt.datetime:
    """A spreadsheet timestamp, which is naive by construction.

    ruff's DTZ rule wants a timezone on every ``datetime``, and it is right
    almost everywhere. Not here: an Excel cell carries no zone at all, so
    attaching one would test something the format cannot produce.
    """
    return dt.datetime(year, month, day, hour, minute)  # noqa: DTZ001


def _workbook(rows: list[list[object]]) -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    assert sheet is not None
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


# ----------------------------------------------------------------- xlsx -----


def test_a_workbook_arrives_as_text_like_every_other_format() -> None:
    frame = normalize.read(_workbook([["a", "b"], [1, "x"], [2, "y"]]), SourceFormat.XLSX)
    assert frame.columns == ["a", "b"]
    assert frame.rows() == [("1", "x"), ("2", "y")]


def test_excel_dates_become_iso_dates_rather_than_timestamps() -> None:
    """The shape has to survive, or the date rule will not recognise it.

    Excel stores a date as a datetime at midnight. Writing that out as
    ``2024-03-01 00:00:00`` would make every spreadsheet date column a
    ``datetime`` with a time nobody entered.
    """
    frame = normalize.read(
        _workbook([["when"], [_cell(2024, 3, 1)], [_cell(2024, 3, 2)]]),
        SourceFormat.XLSX,
    )
    assert frame["when"].to_list() == ["2024-03-01", "2024-03-02"]


def test_a_real_time_of_day_is_kept() -> None:
    """The control for the rule above: midnight is special, other times are not."""
    frame = normalize.read(_workbook([["when"], [_cell(2024, 3, 1, 14, 30)]]), SourceFormat.XLSX)
    assert frame["when"].to_list() == ["2024-03-01 14:30:00"]


def test_whole_numbers_do_not_acquire_a_decimal_point() -> None:
    """Excel stores every number as a float, and ``str(3.0)`` is ``'3.0'``.

    Left alone, that would make an integer column ``decimal`` for a reason that
    has nothing to do with the data — the shape rules read exactly this text.
    """
    frame = normalize.read(_workbook([["n"], [3], [4]]), SourceFormat.XLSX)
    assert frame["n"].to_list() == ["3", "4"]


def test_excel_booleans_become_the_words_the_detector_knows() -> None:
    frame = normalize.read(_workbook([["ok"], [True], [False]]), SourceFormat.XLSX)
    assert frame["ok"].to_list() == ["true", "false"]


def test_trailing_blank_rows_are_not_data() -> None:
    """A spreadsheet's idea of "empty" is a row of Nones, not the end of the file."""
    frame = normalize.read(_workbook([["a"], [1], [None], [None]]), SourceFormat.XLSX)
    assert frame.height == 1


def test_an_empty_worksheet_is_refused_with_a_reason() -> None:
    with pytest.raises(IngestRejected, match="empty"):
        normalize.read(_workbook([]), SourceFormat.XLSX)


def test_a_worksheet_with_only_a_header_is_refused() -> None:
    with pytest.raises(IngestRejected, match="no data rows"):
        normalize.read(_workbook([["a", "b"]]), SourceFormat.XLSX)


def test_a_zip_that_is_not_a_workbook_never_reaches_the_reader() -> None:
    """D-027: the format is decided by content, and this content is not a workbook."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("notes.txt", "hello")

    with pytest.raises(IngestRejected, match="not an Excel workbook"):
        formats.sniff(buffer.getvalue(), filename="book.xlsx")


def test_a_workbook_round_trips_through_the_file_path(tmp_path: Path) -> None:
    source = tmp_path / "book.xlsx"
    source.write_bytes(_workbook([["a", "b"], [1, "x"], [2, "y"]]))

    result = normalize.normalize_file(source, SourceFormat.XLSX, tmp_path / "out.parquet")

    assert result.columns == ("a", "b")
    assert result.row_count == 2


# ----------------------------------------------------------------- json -----


def test_an_array_of_objects_becomes_a_table() -> None:
    frame = normalize.read(b'[{"a": 1, "b": "x"}, {"a": 2, "b": "y"}]', SourceFormat.JSON)
    assert frame.columns == ["a", "b"]
    assert frame.rows() == [("1", "x"), ("2", "y")]


def test_a_key_missing_from_some_records_becomes_a_null() -> None:
    """Objects are not required to agree, and the union of keys is the schema."""
    frame = normalize.read(b'[{"a": 1}, {"a": 2, "b": "late"}]', SourceFormat.JSON)
    assert frame.columns == ["a", "b"]
    assert frame["b"].to_list() == [None, "late"]


def test_json_booleans_and_nulls_arrive_as_the_detector_expects() -> None:
    frame = normalize.read(b'[{"ok": true, "n": null}, {"ok": false, "n": 1}]', SourceFormat.JSON)
    assert frame["ok"].to_list() == ["true", "false"]
    assert frame["n"].to_list() == [None, "1"]


def test_nested_values_are_refused_by_column_name() -> None:
    """§9.6 is single-table. Flattening invents a structure nobody wrote.

    Naming the column matters: the file may have fifty of them and only one is
    the problem (P6).
    """
    with pytest.raises(IngestRejected, match="'address'"):
        normalize.read(b'[{"address": {"city": "Bogor"}}]', SourceFormat.JSON)


def test_json_that_is_not_an_array_says_what_it_is() -> None:
    with pytest.raises(IngestRejected, match="dict"):
        normalize.read(b'{"a": 1}', SourceFormat.JSON)


def test_an_element_that_is_not_an_object_is_located() -> None:
    with pytest.raises(IngestRejected, match="element 1"):
        normalize.read(b'[{"a": 1}, 7]', SourceFormat.JSON)


def test_malformed_json_is_refused_rather_than_crashing() -> None:
    with pytest.raises(IngestRejected, match="could not read this as JSON"):
        normalize.read(b'[{"a": ', SourceFormat.JSON)


# ------------------------------------------------------- one pipeline -------


def test_a_spreadsheet_and_a_csv_of_the_same_data_infer_the_same_types(
    tmp_path: Path,
) -> None:
    """The reason both readers throw the source's typing away.

    If XLSX kept Excel's types and CSV did not, the same table would get two
    different schemas depending on which button the user exported with — and
    every downstream number with it.
    """
    rows: list[list[object]] = [
        ["order_id", "amount", "when", "kota"],
        [1, 1500.5, _cell(2024, 3, 1), "Bogor"],
        [2, 2300, _cell(2024, 3, 2), "Solo"],
    ]
    from_xlsx = normalize.read(_workbook(rows), SourceFormat.XLSX)
    from_csv = normalize.read(
        b"order_id,amount,when,kota\n1,1500.5,2024-03-01,Bogor\n2,2300,2024-03-02,Solo\n",
        SourceFormat.CSV,
        normalize.Dialect(delimiter=",", encoding="utf-8", has_header=True, confidence=1.0),
    )
    assert from_xlsx.rows() == from_csv.rows()


def test_the_inference_rules_apply_unchanged_to_spreadsheet_columns() -> None:
    """One pipeline means the D-029 rules need no XLSX-specific branch."""
    stats = ColumnStatistics(
        name="when",
        ordinal=0,
        physical_type="VARCHAR",
        total=2,
        non_null=2,
        distinct=2,
        integer_like=0,
        decimal_like=0,
        boolean_like=0,
        date_like=2,
        datetime_like=0,
    )
    assert build_columns([stats])[0].logical_type is LogicalType.DATE
