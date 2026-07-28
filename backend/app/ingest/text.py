"""Turning uploaded bytes into text, and saying which encoding got us there.

No ``chardet``. Statistical encoding detection is a guess dressed as an answer,
and it is wrong most often on exactly the files that matter: short ones, and
ones whose non-ASCII characters are rare. The ladder here is deliberately
boring — BOM, then strict UTF-8, then a single legacy fallback — and every rung
is a fact rather than a probability. It also keeps a dependency out (P9).

There are two fallback rungs rather than one, and the reason is a correction:
**cp1252 does not decode every byte.** 0x81, 0x8D, 0x8F, 0x90 and 0x9D are
undefined in it, so a "safe last resort" built on cp1252 alone still raises —
found by a test written to assert the opposite. cp1252 goes first because it is
what Windows Excel writes when it is not writing UTF-8, and that is where our
files come from. **latin-1** goes last because it is the only one of the two
that maps all 256 bytes, which is what "never fails" actually requires.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from typing import Final

#: Tried in order. Each entry is (BOM, encoding name); an empty BOM never
#: matches and is handled separately.
_BOMS: Final = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)

#: Tried when UTF-8 fails. Covers the common Windows/Excel case, but has five
#: undefined bytes, so it cannot be the last rung.
FALLBACK_ENCODING: Final = "cp1252"

#: The last rung. Maps all 256 bytes by construction, so ingest can promise that
#: an encoding never stops a file from being read.
TOTAL_FALLBACK_ENCODING: Final = "latin-1"

#: Longest character a UTF-8 sequence can be. A prefix may end inside one.
_MAX_UTF8_CHAR_BYTES: Final = 4


@dataclass(frozen=True, slots=True)
class DecodedText:
    """Text, plus what it took to get there."""

    text: str
    encoding: str
    #: True when the input was a prefix and trailing bytes were dropped because
    #: they were an incomplete character. Only meaningful for previews.
    truncated: bool


def _trim_incomplete_utf8_tail(data: bytes) -> bytes | None:
    """Drop a partial multi-byte character at the end of a prefix.

    Returns ``None`` when no such trim makes the data valid UTF-8 — meaning the
    failure was somewhere other than the cut, so the data really is not UTF-8.

    Without this, a 1 MB preview slice that happens to cut through a ``é``
    fails strict UTF-8 and the file gets reported as cp1252 — so the preview
    shows mojibake for a file that is perfectly good UTF-8, and the user
    "corrects" an encoding that was never wrong. The bug would appear and
    disappear depending on where the byte boundary landed, which is the worst
    kind to chase.
    """
    for drop in range(1, _MAX_UTF8_CHAR_BYTES):
        if drop >= len(data):
            break
        candidate = data[:-drop]
        try:
            candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
        return candidate
    return None


def decode(data: bytes, *, is_prefix: bool = False) -> DecodedText:
    """Decode ``data``, reporting which encoding worked.

    ``is_prefix=True`` says the caller handed over the beginning of a file
    rather than all of it, which permits trimming an incomplete final
    character. For a complete file, a partial character at the end is a corrupt
    file and must not be silently repaired.
    """
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            body = data if encoding == "utf-8-sig" else data[len(bom) :]
            try:
                return DecodedText(body.decode(encoding), encoding, truncated=False)
            except UnicodeDecodeError:
                # A declared BOM that then fails to decode is a damaged file,
                # not an invitation to guess a different encoding.
                break

    try:
        return DecodedText(data.decode("utf-8"), "utf-8", truncated=False)
    except UnicodeDecodeError:
        pass

    if is_prefix:
        trimmed = _trim_incomplete_utf8_tail(data)
        if trimmed is not None:
            return DecodedText(trimmed.decode("utf-8"), "utf-8", truncated=True)

    try:
        return DecodedText(data.decode(FALLBACK_ENCODING), FALLBACK_ENCODING, truncated=False)
    except UnicodeDecodeError:
        return DecodedText(
            data.decode(TOTAL_FALLBACK_ENCODING), TOTAL_FALLBACK_ENCODING, truncated=False
        )


def drop_partial_last_line(text: str) -> str:
    """Remove a final line that the prefix cut in half.

    A preview reads a fixed number of bytes, so its last line is almost always
    incomplete. Counting delimiters in a half-line is how a detector talks
    itself into the wrong delimiter on an otherwise obvious file.
    """
    if not text:
        return text
    if text.endswith(("\n", "\r")):
        return text
    head, separator, _ = text.rpartition("\n")
    return head + separator if separator else ""


__all__ = [
    "FALLBACK_ENCODING",
    "TOTAL_FALLBACK_ENCODING",
    "DecodedText",
    "decode",
    "drop_partial_last_line",
]
