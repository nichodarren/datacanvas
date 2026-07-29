"""Bundled sample datasets (FR-B.5).

§14.5 is direct about why these exist: *"Jangan tampilkan kanvas kosong — orang
perlu melihat produknya bekerja sebelum mengunggah data mereka."* Someone whose
first act must be handing over their own file has to trust the product before it
has shown them anything.

They are also the cheapest possible demo. The two here are chosen to teach
different things: one where detection is unremarkable, and one where it is the
point.

**The files are the ones ``eval/datasets`` already holds**, read from a
configured directory rather than copied into the package. The duplication would
be small, but two copies of a file whose SHA-256 is a contract
(``golden_queries.md`` §3) is two things that can drift — and the one that
drifts would be the one nobody runs the checks against. The cost is stated
rather than hidden: a deployment that does not ship ``eval/`` must point
``DATACANVAS_SAMPLES_ROOT`` somewhere that has them, or samples are simply
unavailable and the route says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.ingest.limits import IngestRejected


@dataclass(frozen=True, slots=True)
class Sample:
    """One offer on the empty state."""

    key: str
    name: str
    filename: str
    description: str


#: Deliberately two, not five. A wall of choices at the empty state is another
#: decision to make before anything happens, which is the problem this is
#: supposed to solve.
SAMPLES: tuple[Sample, ...] = (
    Sample(
        key="titanic",
        name="Titanic passengers",
        filename="titanic.csv",
        description="891 rows. Clean and familiar — a good look at what detection does normally.",
    ),
    Sample(
        key="messy-sales",
        name="Messy sales",
        filename="messy_sales.csv",
        description=(
            "5,000 rows with deliberate problems. Three columns come back flagged, "
            "each with a reason — this is the one worth opening."
        ),
    ),
)

BY_KEY = {sample.key: sample for sample in SAMPLES}


def resolve(key: str, root: Path) -> tuple[Sample, Path]:
    """Find a sample's file, or refuse in a way that says which part is missing.

    An unknown key and a missing file are different problems — one is a bad
    request, the other is a deployment that did not ship the data — and telling
    them apart is the difference between the user retrying and an operator
    fixing something (P6).
    """
    sample = BY_KEY.get(key)
    if sample is None:
        raise IngestRejected(f"no sample called {key!r}. Available: {', '.join(sorted(BY_KEY))}.")

    path = root / sample.filename
    if not path.is_file():
        raise IngestRejected(
            f"the sample data for {sample.name!r} is not installed on this server "
            f"(expected {sample.filename})."
        )
    return sample, path


__all__ = ["BY_KEY", "SAMPLES", "Sample", "resolve"]
