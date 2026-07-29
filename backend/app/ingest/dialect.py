"""Detecting how a delimited file is laid out (FR-B.3).

Three things have to be guessed before a CSV can be read at all: the encoding,
the delimiter, and whether the first row is a header. FR-B.3 requires all three
to be **shown to the user for correction before commit**, which changes what a
good detector is: it does not have to be right every time, it has to be right
often and wrong *visibly*.

``csv.Sniffer`` is not used. It raises on files it cannot decide, decides badly
on files with quoted delimiters, and gives no signal about how confident it was
— so there is nothing to show the user beyond a verdict. The detector here
scores candidates on consistency across rows, which produces both an answer and
a reason.
"""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from typing import Final

from app.ingest.limits import IngestRejected
from app.ingest.text import decode, drop_partial_last_line

#: Ordered by how common they are in the wild. Order only breaks exact ties.
CANDIDATE_DELIMITERS: Final = (",", ";", "\t", "|")

#: Recorded when a file turns out to have a single column. The value is
#: arbitrary and that is the point: with one column every candidate yields the
#: same table, so what goes into `ingest_options` only has to be stable.
SINGLE_COLUMN_DELIMITER: Final = ","

#: Rows examined when scoring delimiters. Enough to see a pattern, few enough
#: that the work is bounded no matter how large the preview is.
_SCORING_ROWS: Final = 40


@dataclass(frozen=True, slots=True)
class Dialect:
    """How to read a delimited file. Recorded in ``ingest_options`` (§9.2).

    This is part of reproducibility, not a transient detail: re-reading the same
    source file later has to produce the same table, and that is only true if
    the dialect that produced it was written down.
    """

    delimiter: str
    encoding: str
    has_header: bool
    #: 0..1. Not a probability — a consistency score, used to decide how loudly
    #: the UI should ask the user to confirm (FR-C.6 applies the same idea to
    #: types).
    confidence: float

    def as_options(self) -> dict[str, object]:
        return {
            "delimiter": self.delimiter,
            "encoding": self.encoding,
            "has_header": self.has_header,
        }


def _rows_for(text: str, delimiter: str) -> list[list[str]]:
    reader = csv.reader(StringIO(text), delimiter=delimiter)
    rows: list[list[str]] = []
    try:
        for row in reader:
            rows.append(row)
            if len(rows) >= _SCORING_ROWS:
                break
    except csv.Error:
        # A field longer than the parser's limit, or a stray NUL. Score it as
        # unusable rather than letting one candidate crash the comparison.
        return []
    return rows


def _score(rows: list[list[str]]) -> tuple[int, float]:
    """(field count, consistency) for one candidate delimiter.

    The winning delimiter is the one that splits rows into the **same** number
    of fields every time. That is a stronger signal than "the character that
    appears most often": a text column full of commas beats a semicolon
    delimiter on frequency, but loses badly on consistency, because it splits
    different rows into different numbers of fields.
    """
    usable = [row for row in rows if row]
    if len(usable) < 2:
        return 0, 0.0

    widths = Counter(len(row) for row in usable)
    most_common_width, agreeing = widths.most_common(1)[0]
    if most_common_width < 2:
        # One field per row means this character never split anything.
        return 0, 0.0
    return most_common_width, agreeing / len(usable)


def detect_delimiter(text: str) -> tuple[str, float]:
    """Pick the delimiter and say how consistent it was.

    **A file where nothing splits is a single-column file, not a broken one.**
    An earlier version raised here, which refused a list of order ids — a
    perfectly ordinary CSV, and one that FR-B.1 says we accept. The mistake was
    treating "found no separator" as a failure when it is an answer: with one
    column, every candidate delimiter produces the same table, so there is
    nothing to get wrong and nothing to ask the user about.

    What still has to be caught is the *other* single-column case — rows that
    were never split because the delimiter was wrong. That is
    :func:`normalize._reject_unsplit_rows`, and it can tell the two apart
    because the wrong-delimiter case is visibly full of some other separator.
    """
    best: tuple[str, int, float] | None = None
    for candidate in CANDIDATE_DELIMITERS:
        width, consistency = _score(_rows_for(text, candidate))
        if width < 2:
            continue
        if best is None or (consistency, width) > (best[2], best[1]):
            best = (candidate, width, consistency)

    if best is None:
        return SINGLE_COLUMN_DELIMITER, 1.0
    return best[0], best[2]


def _looks_numeric(value: str) -> bool:
    """Deliberately narrow. Only used to compare row 0 against the rest."""
    candidate = value.strip().replace(" ", "").replace(",", "")
    if not candidate:
        return False
    try:
        float(candidate)
    except ValueError:
        return False
    return True


def detect_header(rows: list[list[str]]) -> bool:
    """Is row 0 a header?

    Two signals, and neither alone is enough:

    * **Row 0 is non-numeric where the body is numeric.** The strongest signal
      there is — a column of amounts under the label ``amount``.
    * **Row 0 has no blanks and no repeats.** Column names are unique and
      present; data rows frequently are neither.

    Where the body is entirely text both signals go quiet, and the answer
    defaults to *yes*. That is the right default rather than a coin toss: a
    header wrongly treated as data shows up as one odd row that a person will
    notice, while data wrongly treated as a header **silently deletes a row**
    and names every column after it.
    """
    body = [row for row in rows[1:] if row]
    if not rows or not rows[0] or not body:
        return True

    first = rows[0]
    if any(not cell.strip() for cell in first):
        return False
    if len(set(first)) != len(first):
        return False

    votes_for = 0
    votes_against = 0
    for column in range(len(first)):
        body_values = [row[column] for row in body if len(row) > column]
        if not body_values:
            continue
        numeric_share = sum(_looks_numeric(v) for v in body_values) / len(body_values)
        if numeric_share <= 0.8:
            continue
        # This column is numeric data. Whether row 0 joins in is the question.
        if _looks_numeric(first[column]):
            votes_against += 1
        else:
            votes_for += 1

    if votes_for or votes_against:
        return votes_for >= votes_against
    return True


def detect(data: bytes, *, is_prefix: bool = True) -> Dialect:
    """Everything needed to read a delimited file, from its first bytes.

    ``is_prefix`` defaults to True because the caller is normally the preview
    (D-025). The consequence is stated in that decision and worth repeating
    here: a dialect that is right for the first megabyte can still be wrong for
    the rest of the file, so the commit path must fail honestly rather than
    assume this answer holds.
    """
    decoded = decode(data, is_prefix=is_prefix)
    text = drop_partial_last_line(decoded.text) if is_prefix else decoded.text
    if not text.strip():
        raise IngestRejected("the file contains no readable rows")

    delimiter, confidence = detect_delimiter(text)
    has_header = detect_header(_rows_for(text, delimiter))

    return Dialect(
        delimiter=delimiter,
        encoding=decoded.encoding,
        has_header=has_header,
        confidence=confidence,
    )


__all__ = [
    "CANDIDATE_DELIMITERS",
    "SINGLE_COLUMN_DELIMITER",
    "Dialect",
    "detect",
    "detect_delimiter",
    "detect_header",
]
