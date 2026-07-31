"""Every text colour in the palette must clear WCAG AA on every surface.

NFR-UX.3 asks for AA contrast, and ``globals.css`` opened with a comment
claiming it — *"Contrast targets WCAG AA (NFR-UX.3)"*. Nothing measured it, and
the claim was false: ``--ink-faint`` measured **4.1:1** on ``--bg``, **3.8:1** on
``--panel`` and **3.4:1** on ``--panel-2`` — under the 4.5:1 AA floor for text
below 24px on every surface it is drawn on.

That token is not decoration. It carries the word ``null`` in a grid cell — a
fact about the data — plus row numbers, the row and column counts, the sample
descriptions and the upload hint. All of it below the readable floor, on the one
requirement that says people must be able to read the thing.

**This asserts the ratio, not the hex.** A test pinned to ``#8290a6`` would have
to be edited by whoever next changes the palette, and editing a test to make a
change pass is how the guarantee quietly disappears. Pinned to the ratio, the
palette can move freely and this fails only when it moves somewhere unreadable.

Kept in Python beside ``test_docs_contract.py`` and ``test_frontend_wiring.py``:
all three read a source file and assert a property of it, and none needs Node
installed to run.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STYLESHEET = ROOT / "frontend" / "src" / "app" / "globals.css"

#: WCAG 2.1 SC 1.4.3, normal-sized text. Every token below is used at 11-13px.
AA_NORMAL_TEXT = 4.5

#: The three background tokens. Anything readable has to be readable on all of
#: them: the grid draws on ``--panel`` and its hover state on ``--panel-2``, and
#: popups sit on ``--panel-2`` over a ``--bg`` page.
SURFACES = ("--bg", "--panel", "--panel-2")

#: Tokens that are used as *text* somewhere. ``--line`` is a border and never
#: carries a glyph, so it is deliberately absent.
TEXT = ("--ink", "--ink-dim", "--ink-faint", "--accent", "--ok", "--warn", "--danger")

#: Text on a coloured fill rather than on a surface. ``button.primary`` and the
#: current entry of the type menu both paint this ink onto ``--accent``.
ON_ACCENT = "#0b1020"


def _tokens() -> dict[str, str]:
    """The custom properties declared in the ``:root`` block."""
    text = STYLESHEET.read_text(encoding="utf-8")
    start = text.index(":root {")
    end = text.index("\n}", start)
    return dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", text[start:end]))


def _channel(value: int) -> float:
    """One sRGB channel, linearised (WCAG 2.1 relative luminance)."""
    ratio = value / 255
    return ratio / 12.92 if ratio <= 0.04045 else ((ratio + 0.055) / 1.055) ** 2.4


def _luminance(hex_colour: str) -> float:
    red, green, blue = (int(hex_colour[index : index + 2], 16) for index in (1, 3, 5))
    return 0.2126 * _channel(red) + 0.7152 * _channel(green) + 0.0722 * _channel(blue)


def contrast(foreground: str, background: str) -> float:
    """The WCAG contrast ratio between two ``#rrggbb`` colours, 1.0 to 21.0."""
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_palette_parses() -> None:
    """A stylesheet that stopped matching would make every check below vacuous."""
    tokens = _tokens()
    missing = [name for name in (*SURFACES, *TEXT) if name not in tokens]
    assert not missing, f"tokens missing from the :root block: {missing}"


@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("ink", TEXT)
def test_text_clears_aa_on_every_surface(ink: str, surface: str) -> None:
    tokens = _tokens()
    ratio = contrast(tokens[ink], tokens[surface])
    assert ratio >= AA_NORMAL_TEXT, (
        f"{ink} ({tokens[ink]}) on {surface} ({tokens[surface]}) is {ratio:.2f}:1; "
        f"NFR-UX.3 needs {AA_NORMAL_TEXT}:1. Lighten the text token rather than "
        f"lowering this threshold."
    )


def test_primary_button_ink_clears_aa_on_its_fill() -> None:
    """``button.primary`` paints a near-black ink onto ``--accent``."""
    ratio = contrast(ON_ACCENT, _tokens()["--accent"])
    assert ratio >= AA_NORMAL_TEXT, (
        f"{ON_ACCENT} on --accent is {ratio:.2f}:1; NFR-UX.3 needs {AA_NORMAL_TEXT}:1"
    )
