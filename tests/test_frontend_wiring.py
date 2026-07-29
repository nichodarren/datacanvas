"""Every call the API client offers must be reachable from the UI.

Written after finding that **FR-A.2 had no surface at all**. The requirement —
*"Sesi pengguna dapat dicabut (logout, logout semua perangkat)"*, P0 — was
implemented end to end: one ``Session`` row per device, tokens hashed, both
routes live, and two integration tests covering the behaviour
(``test_auth_flow.py``). ``api.logout`` even existed in the TypeScript client.

Nothing called it. The only way to sign out of DataCanvas was to delete the
cookie by hand in DevTools.

Every test that mattered was green, because each one checked its own layer. The
gap lived *between* layers, which is where this kind of gap always lives: a
route nobody reaches is indistinguishable from a route that works, right up
until a user goes looking for it.

So this test asks the one question no layer-local test can: **is anything built
but unreachable?** It is deliberately cheap and deliberately blunt — a name
defined on ``api`` and never mentioned outside ``lib/`` is dead weight or a
missing button, and both are worth a failure.

If a call is genuinely not meant to have a UI yet, add it to
``DELIBERATELY_UNREACHABLE`` **with the reason**. The list is the point: it
turns an invisible gap into a written one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "frontend" / "src" / "lib" / "api.ts"
SOURCE = ROOT / "frontend" / "src"

# Nothing is on this list today, and that is the intended steady state. An entry
# here is a promise the product does not yet keep, stated out loud.
DELIBERATELY_UNREACHABLE: dict[str, str] = {}


def _api_members(text: str) -> set[str]:
    """The keys of ``export const api = { … }``, and nothing else in the file.

    Bounded by the literal rather than scanned whole: ``request`` and ``json``
    are module-level helpers, and counting them would make the test assert
    something it does not mean.
    """
    start = text.index("export const api = {")
    end = text.index("\n};", start)
    body = text[start:end]
    # Top level only: exactly two spaces of indent. Nested object literals sit
    # deeper, so this cannot mistake an option name for a call.
    return set(re.findall(r"^  ([a-zA-Z][a-zA-Z0-9]*):", body, flags=re.MULTILINE))


def _callers() -> str:
    """Every frontend source file except the client itself."""
    files = [
        path
        for path in SOURCE.rglob("*.ts*")
        if path.is_file() and "lib" not in path.relative_to(SOURCE).parts
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


@pytest.mark.skipif(not CLIENT.is_file(), reason="frontend not present in this checkout")
def test_every_api_call_has_a_caller() -> None:
    members = _api_members(CLIENT.read_text(encoding="utf-8"))
    assert members, "the api client parsed to nothing — the literal must have moved"

    callers = _callers()
    unreachable = {name for name in members if not re.search(rf"\bapi\.{name}\b", callers)}

    unexplained = unreachable - set(DELIBERATELY_UNREACHABLE)
    assert not unexplained, (
        f"built but unreachable from the UI: {sorted(unexplained)}. "
        "Either give it a way in, or record why it has none in "
        "DELIBERATELY_UNREACHABLE."
    )


@pytest.mark.skipif(not CLIENT.is_file(), reason="frontend not present in this checkout")
def test_the_unreachable_list_does_not_go_stale() -> None:
    """A list of known gaps that outlives the gaps is worse than no list.

    It reads as an admission that is no longer true, and the next person trusts
    it instead of the code.
    """
    callers = _callers()
    fixed = {name for name in DELIBERATELY_UNREACHABLE if re.search(rf"\bapi\.{name}\b", callers)}
    assert not fixed, f"these now have a caller and should leave the list: {sorted(fixed)}"


@pytest.mark.skipif(not CLIENT.is_file(), reason="frontend not present in this checkout")
def test_signing_out_is_reachable() -> None:
    """The specific gap, named.

    The general test above would catch this again, but only by accident of
    ``logout`` being one of many. FR-A.2 is P0 and both halves of it — this
    device and every device — are worth failing by name.
    """
    callers = _callers()
    assert "api.logout(" in callers, "FR-A.2: nothing in the UI signs the user out"
    assert "api.logoutAll(" in callers, "FR-A.2: nothing in the UI revokes other devices"
