"""Every text colour must clear WCAG AA on every surface, **in both grounds**.

NFR-UX.3 asks for AA contrast, and ``globals.css`` once opened with a comment
claiming it — *"Contrast targets WCAG AA"*. Nothing measured it, and the claim
was false: ``--ink-faint`` measured **4.1:1** on ``--bg``, **3.8:1** on
``--panel`` and **3.4:1** on ``--panel-2``, under the 4.5:1 floor on every
surface it was drawn on. That token carries the word ``null`` in a grid cell —
a fact about the data — plus row numbers, counts and hints.

**This asserts ratios, never hexes.** A test pinned to ``#8290a6`` has to be
edited by whoever next moves the palette, and editing a test to make a change
pass is how a guarantee quietly disappears. Pinned to the ratio, the palette
moves freely and this fails only when it moves somewhere unreadable.

## Why one file yields two palettes

The stylesheet declares each token once, as ``light-dark(<light>, <dark>)``.
There is no second ``:root`` block and no duplicated dark palette — which is the
point: two blocks that must agree are two blocks that eventually will not, and
this project has spent enough sessions on things that drifted because nothing
compared them. Here the two values are on the same line, and this file reads
both out of it.

Kept in Python beside ``test_docs_contract.py`` and ``test_frontend_wiring.py``:
all three read a source file and assert a property of it, and none needs Node.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
STYLESHEET = ROOT / "frontend" / "src" / "app" / "globals.css"

#: WCAG 2.1 SC 1.4.3, normal-sized text. Every token below is used at 11-14px.
AA_NORMAL_TEXT = 4.5

#: WCAG 2.1 SC 1.4.11, non-text contrast. Applies to the visual information
#: needed to *identify a control* — a button's boundary, a focus indicator.
AA_NON_TEXT = 3.0

#: The grounds. ``light`` is first because that is the order ``light-dark()``
#: takes its arguments in, and matching that order keeps the parser honest.
GROUNDS = ("light", "dark")

#: Every surface a glyph is ever drawn on: the page, the panels that hold
#: content, and the raised surface used by table headers, buttons and popups.
SURFACES = ("--bg", "--panel", "--panel-2")

#: Tokens used as *text* somewhere.
#:
#: ``--accent`` and ``--ok`` are gone rather than merely absent from this list.
#: D-037 removes the accent hue entirely — emphasis is carried by weight and by
#: inversion — and drops the success hue because success is the ordinary outcome
#: rather than an exception, so green encoded nothing the word did not.
TEXT = ("--ink", "--ink-dim", "--ink-faint", "--warn", "--danger")

#: Borders, and the three different jobs they do. Only ``--edge`` is held to
#: 1.4.11: it is what tells you something is a control. ``--line`` separates
#: regions and ``--line-soft`` separates rows of the same thing — neither is
#: the sole means of identifying anything, and holding table gridlines to 3:1
#: would draw a grid in jail bars.
CONTROL_EDGE = "--edge"


def _tokens(ground: str) -> dict[str, str]:
    """The ``:root`` custom properties, resolved for one ground.

    ``light-dark(#aaa, #bbb)`` yields the first value for light and the second
    for dark. Plain ``#rrggbb`` values are ground-independent and returned as-is.
    """
    text = STYLESHEET.read_text(encoding="utf-8")
    start = text.index(":root {")
    end = text.index("\n}", start)
    block = text[start:end]

    index = 0 if ground == "light" else 1
    paired = {
        name: (light, dark)[index]
        for name, light, dark in re.findall(
            r"(--[a-z0-9-]+):\s*light-dark\(\s*(#[0-9a-fA-F]{6})\s*,\s*(#[0-9a-fA-F]{6})\s*\)",
            block,
        )
    }
    plain = dict(re.findall(r"(--[a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\s*;", block))
    return {**plain, **paired}


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


@pytest.mark.parametrize("ground", GROUNDS)
def test_the_palette_parses_in_both_grounds(ground: str) -> None:
    """A stylesheet that stopped matching would make every check below vacuous.

    This is the guard that matters most in this file. Every assertion under it
    reads its colours through the same regex, so a syntax change that silently
    matched nothing would turn the whole suite green while measuring air.
    """
    tokens = _tokens(ground)
    missing = [name for name in (*SURFACES, *TEXT, CONTROL_EDGE) if name not in tokens]
    assert not missing, f"tokens missing from the :root block for {ground}: {missing}"


def test_the_two_grounds_are_actually_different() -> None:
    """Both grounds must really be declared, not one palette read twice.

    Without this, a stylesheet that dropped ``light-dark()`` and went back to a
    single value per token would still pass everything else — and would pass it
    by testing the same palette twice.
    """
    light, dark = _tokens("light"), _tokens("dark")
    same = [name for name in SURFACES if light[name] == dark[name]]
    assert not same, f"these surfaces are identical in both grounds: {same}"


@pytest.mark.parametrize("ground", GROUNDS)
@pytest.mark.parametrize("surface", SURFACES)
@pytest.mark.parametrize("ink", TEXT)
def test_text_clears_aa_on_every_surface(ink: str, surface: str, ground: str) -> None:
    tokens = _tokens(ground)
    ratio = contrast(tokens[ink], tokens[surface])
    assert ratio >= AA_NORMAL_TEXT, (
        f"[{ground}] {ink} ({tokens[ink]}) on {surface} ({tokens[surface]}) is "
        f"{ratio:.2f}:1; NFR-UX.3 needs {AA_NORMAL_TEXT}:1. Move the token rather "
        f"than lowering this threshold."
    )


@pytest.mark.parametrize("ground", GROUNDS)
@pytest.mark.parametrize("surface", SURFACES)
def test_a_control_boundary_is_visible_against_what_it_sits_on(surface: str, ground: str) -> None:
    """WCAG 1.4.11: you must be able to *see* that a control is a control.

    ``--edge`` draws the outline of buttons and inputs. Writing this test is
    what produced the token: the palette had one border colour doing three
    different jobs, and holding that one colour to 3:1 would have drawn the
    grid's thousands of row separators in the same heavy line.
    """
    tokens = _tokens(ground)
    ratio = contrast(tokens[CONTROL_EDGE], tokens[surface])
    assert ratio >= AA_NON_TEXT, (
        f"[{ground}] {CONTROL_EDGE} ({tokens[CONTROL_EDGE]}) on {surface} "
        f"({tokens[surface]}) is {ratio:.2f}:1; SC 1.4.11 needs {AA_NON_TEXT}:1"
    )


@pytest.mark.parametrize("ground", GROUNDS)
@pytest.mark.parametrize("surface", SURFACES)
def test_the_focus_ring_is_visible_on_every_surface(surface: str, ground: str) -> None:
    """The ring is ``--ink``, which is why it survives both grounds.

    Chosen for exactly this: an accent hue has to be re-proved on every surface
    in every ground, and the one colour guaranteed to contrast with the page is
    the colour the page writes its text in.
    """
    tokens = _tokens(ground)
    ratio = contrast(tokens["--ink"], tokens[surface])
    assert ratio >= AA_NON_TEXT, (
        f"[{ground}] the focus ring on {surface} is {ratio:.2f}:1; needs {AA_NON_TEXT}:1"
    )


@pytest.mark.parametrize("ground", GROUNDS)
def test_the_primary_button_is_readable_inverted(ground: str) -> None:
    """``button.primary`` paints ``--bg`` onto ``--ink`` (D-037).

    The inversion *is* the emphasis, now that there is no accent hue to carry
    it. It is also the safest possible pair to check — but checking it is what
    stops a later palette move from quietly making the one primary action on a
    screen unreadable.
    """
    tokens = _tokens(ground)
    ratio = contrast(tokens["--bg"], tokens["--ink"])
    assert ratio >= AA_NORMAL_TEXT, (
        f"[{ground}] --bg on --ink is {ratio:.2f}:1; NFR-UX.3 needs {AA_NORMAL_TEXT}:1"
    )


def test_no_accent_token_survives() -> None:
    """D-037 removed the accent hue; this stops it drifting back in.

    Not pedantry. ``--accent`` marked links, logical types, the primary button,
    every hover border and the focus ring — five jobs on one hue. Re-adding it
    for one of those would quietly restore the habit for all five, and the whole
    direction is that colour is spent only on exceptions.
    """
    declared = _tokens("light")
    assert "--accent" not in declared, (
        "--accent is back in :root; direction B spends no hue on affordance"
    )
    assert "--ok" not in declared, (
        "--ok is back in :root; success is the ordinary outcome, not an exception"
    )
