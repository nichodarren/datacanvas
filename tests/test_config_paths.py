"""Path settings must not depend on where the process was started.

Found by running the app rather than by a test: started from ``backend/``, the
API booted, logged nothing unusual and answered ``/health`` with 200. The first
symptom was a user clicking a bundled sample and being told it "is not installed
on this server" — because ``samples_root`` defaulted to ``./eval/datasets`` and
``.`` was wherever the operator happened to be standing.

That is the shape this project keeps recording: something correct because the
caller was in the right place by luck, with nothing stating the requirement.
``the project notes`` said ``python -m app`` and could not have warned anyone, because
the constraint was never written down anywhere.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.config import PROJECT_ROOT, Settings


def test_relative_defaults_anchor_to_the_repository(tmp_path: Path) -> None:
    """The whole point: the same answer from any working directory."""
    here = Settings()

    previous = Path.cwd()
    try:
        os.chdir(tmp_path)
        elsewhere = Settings()
    finally:
        os.chdir(previous)

    assert here.samples_root == elsewhere.samples_root
    assert here.storage_root == elsewhere.storage_root


def test_the_bundled_samples_are_actually_there() -> None:
    """Anchoring is only useful if it anchors somewhere real.

    A validator that resolved to a tidy, wrong directory would pass the test
    above and still fail every user who clicked a sample.
    """
    root = Settings().samples_root
    assert root.is_dir(), f"{root} is not a directory"
    assert (root / "titanic.csv").is_file(), f"titanic.csv missing from {root}"


def test_an_absolute_setting_is_left_alone(tmp_path: Path) -> None:
    """Deployments that name a real location still mean it.

    Anchoring must apply to the relative defaults only — rewriting an operator's
    ``/var/lib/...`` into something under the repository would be a far worse
    surprise than the one this fixes.
    """
    assert Settings(storage_root=tmp_path).storage_root == tmp_path


def test_the_anchor_points_at_the_repository_root() -> None:
    """Guards the `parents[2]` above, which is the one fragile line here.

    Moving this module one directory deeper would silently anchor everything to
    ``backend/`` and put the failure back, one level along.
    """
    assert (PROJECT_ROOT / "pyproject.toml").is_file()
    assert (PROJECT_ROOT / "eval" / "datasets").is_dir()
