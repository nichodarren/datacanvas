"""Enforce the layering rule of DESIGN.md §10.6 mechanically.

the project notes states that ``domain/`` must not import from ``api/``,
``repositories/`` or ``ai/``. Stated in a document, that rule survives exactly
as long as everyone remembers it. Parsed from the source tree, it survives
whoever joins next.

Same reasoning the product itself runs on: a prompt is a preference, a test is
a guarantee.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

DOMAIN = Path(__file__).resolve().parents[2] / "backend" / "app" / "domain"

#: The rule from §10.6, verbatim.
FORBIDDEN_APP_PACKAGES = ("app.api", "app.repositories", "app.ai")

#: I/O and framework packages. The domain describes rules, it does not reach
#: anything: no database, no HTTP, no analytics engine, no event loop. Keeping
#: these out is what makes every rule here testable without a fixture.
FORBIDDEN_EXTERNAL = (
    "asyncio",
    "duckdb",
    "fastapi",
    "httpx",
    "polars",
    "psycopg",
    "psycopg_pool",
    "requests",
    "socket",
    "sqlalchemy",
    "starlette",
)


def _domain_modules() -> list[Path]:
    modules = sorted(DOMAIN.rglob("*.py"))
    assert modules, "no domain modules found — did the package move?"
    return modules


def _imported_modules(tree: ast.AST, source: Path) -> list[str]:
    """Every module name a file imports, with relative imports resolved."""
    package_parts = ["app", "domain"]
    found: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module:
                    found.append(node.module)
            else:
                # level 1 = this package, level 2 = its parent, and so on.
                base = package_parts[: len(package_parts) - (node.level - 1)]
                if not base:
                    pytest.fail(f"{source.name}: relative import escapes the package")
                found.append(".".join([*base, node.module] if node.module else base))
    return found


def _is_under(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


@pytest.mark.invariant
@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: p.name)
def test_domain_does_not_import_outer_layers(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    violations = [
        imported
        for imported in _imported_modules(tree, module_path)
        for forbidden in FORBIDDEN_APP_PACKAGES
        if _is_under(imported, forbidden)
    ]
    assert not violations, (
        f"{module_path.name} imports {violations} — DESIGN.md §10.6 forbids domain/ "
        f"from depending on api/, repositories/ or ai/"
    )


@pytest.mark.invariant
@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: p.name)
def test_domain_performs_no_io(module_path: Path) -> None:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    violations = [
        imported
        for imported in _imported_modules(tree, module_path)
        for forbidden in FORBIDDEN_EXTERNAL
        if _is_under(imported, forbidden)
    ]
    assert not violations, (
        f"{module_path.name} imports {violations} — the domain layer must stay free of I/O "
        f"and framework dependencies (DESIGN.md §10.6)"
    )


@pytest.mark.invariant
@pytest.mark.parametrize("module_path", _domain_modules(), ids=lambda p: p.name)
def test_domain_never_reads_the_clock(module_path: Path) -> None:
    """The current time is always an argument, never a lookup.

    A rule that reads the clock itself cannot be tested without freezing time,
    and — worse — changes meaning depending on when it runs. This is the same
    reasoning behind the project notes's ban on ``datetime.now()`` in fixtures, applied
    to the layer where the rules actually live.
    """
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))

    offenders = [
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"now", "utcnow", "today", "time", "monotonic"}
    ]
    assert not offenders, (
        f"{module_path.name} reads the clock via {offenders} — pass the current time in as "
        f"an argument instead"
    )
