"""Menjaga agar dokumen dan repo tidak menyimpang satu sama lain.

DESIGN.md §0.3 menyatakan dokumen adalah SSOT dan tidak boleh menyimpang dari
kode. Test ini menegakkan bagian dari klaim itu secara mekanis, bukan lewat
kedisiplinan — sesuai prinsip yang sama yang dipakai produknya sendiri:
"prompt adalah preferensi; kode adalah jaminan".
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
DATASETS = ROOT / "eval" / "datasets"

EXPECTED_DATASETS = ("titanic.csv", "tips.csv", "hotel_bookings.csv", "messy_sales.csv")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def test_ssot_documents_exist() -> None:
    assert (DOCS / "DESIGN.md").is_file()
    assert (DOCS / "golden_queries.md").is_file()
    assert (ROOT / "the project notes").is_file()


@pytest.mark.parametrize("name", EXPECTED_DATASETS)
def test_eval_dataset_bundled(name: str) -> None:
    """Dataset eval harus ada di repo — reproducibility menuntut byte yang sama."""
    assert (DATASETS / name).is_file(), f"{name} tidak ada di eval/datasets/"


@pytest.mark.parametrize("name", EXPECTED_DATASETS)
def test_dataset_hash_matches_golden_queries_doc(name: str) -> None:
    """SHA-256 di golden_queries.md §3 harus cocok dengan file sebenarnya.

    Kalau test ini gagal, sebuah dataset berubah tanpa dokumen ikut diperbarui —
    artinya nilai harapan golden query mungkin sudah tidak valid. Jalankan
    ``python eval/verify_expected_values.py`` lalu perbarui §3.
    """
    doc = (DOCS / "golden_queries.md").read_text(encoding="utf-8")
    stem = name.removesuffix(".csv")

    row = next((ln for ln in doc.splitlines() if ln.startswith(f"| `{stem}`")), None)
    assert row is not None, f"baris `{stem}` tidak ditemukan di tabel dataset golden_queries.md §3"

    m = re.search(r"`([0-9a-f]{8,})…([0-9a-f]{6,})`", row)
    assert m is not None, f"SHA-256 tidak terbaca pada baris `{stem}`"

    actual = _sha256(DATASETS / name)
    head, tail = m.group(1), m.group(2)
    assert actual.startswith(head), f"{name}: awal hash berbeda dari dokumen"
    assert actual.endswith(tail), f"{name}: akhir hash berbeda dari dokumen"


@pytest.mark.invariant
def test_every_invariant_is_listed_in_project_notes() -> None:
    """Setiap INV-n di DESIGN.md harus muncul juga di the project notes.

    the project notes dimuat setiap sesi; invariant yang hanya ada di DESIGN.md mudah
    terlewat saat implementasi.
    """
    design = (DOCS / "DESIGN.md").read_text(encoding="utf-8")
    notes = (ROOT / "the project notes").read_text(encoding="utf-8")

    declared = sorted(set(re.findall(r"\*\*(INV-\d+)\*\*", design)))
    assert declared, "tidak ada invariant terdeteksi di DESIGN.md — pola berubah?"

    missing = [inv for inv in declared if inv not in notes]
    assert not missing, f"invariant belum tercantum di the project notes: {missing}"
