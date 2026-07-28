"""Menjaga agar tidak ada kode sumber yang hilang dari git.

Ditulis setelah `backend/app/storage/` — seluruh paket ObjectStore, termasuk
lapisan yang menegakkan §13.3.1 L3 — ditemukan tidak pernah masuk git. Pola
`storage/` di `.gitignore` dimaksudkan untuk direktori data runtime di akar
repo, tapi tanpa garis miring di depan ia cocok di kedalaman mana pun.

Kegagalannya sepenuhnya senyap: `git status` bersih, test lulus, coverage
menghitungnya. Satu-satunya sinyal adalah `git ls-files`, dan tidak ada yang
membacanya. Dengan R-16 (project hanya ada di satu mesin, tanpa remote), file
yang tidak terlacak git adalah file yang tidak punya salinan sama sekali.

Karena itu ini bukan test kosmetik: ia menjaga properti "apa yang ada di disk
sama dengan apa yang ada di riwayat".
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

#: Direktori yang isinya adalah kode sumber dan karenanya wajib terlacak.
SOURCE_TREES = ("backend", "tests", "eval", "scripts")

#: Ekstensi yang dihitung sebagai kode sumber. Sengaja sempit — menambah pola
#: di sini lebih murah daripada menjelaskan kenapa sebuah file terlewat.
SOURCE_SUFFIXES = {".py", ".sh", ".mako"}


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture(scope="module")
def tracked_files() -> set[str]:
    try:
        output = _git("ls-files")
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git tidak tersedia atau ini bukan repo git: {exc}")
    return set(output.splitlines())


def _source_files() -> list[str]:
    found: list[str] = []
    for tree in SOURCE_TREES:
        for path in (ROOT / tree).rglob("*"):
            if not path.is_file() or path.suffix not in SOURCE_SUFFIXES:
                continue
            if "__pycache__" in path.parts or ".venv" in path.parts:
                continue
            found.append(path.relative_to(ROOT).as_posix())
    return sorted(found)


def test_every_source_file_is_tracked_by_git(tracked_files: set[str]) -> None:
    """Tidak boleh ada file sumber yang hanya hidup di disk.

    Kalau test ini gagal, kemungkinan besar sebuah pola di `.gitignore` terlalu
    luas — periksa dengan `git check-ignore -v <path>` sebelum menambahkan
    pengecualian.
    """
    untracked = [p for p in _source_files() if p not in tracked_files]
    assert not untracked, (
        f"file sumber tidak terlacak git (kehilangan disk = kehilangan file, R-16): {untracked}"
    )


def test_source_trees_are_not_ignored() -> None:
    """Serangan langsung ke akar penyebabnya: pola yang cocok ke dalam paket.

    Test di atas menangkap gejalanya. Yang ini menangkap sebabnya, dan tetap
    berguna kalau suatu saat seseorang menambahkan pola luas baru sebelum ada
    file yang jatuh ke dalamnya.
    """
    packages = sorted(
        p.relative_to(ROOT).as_posix()
        for tree in SOURCE_TREES
        for p in (ROOT / tree).rglob("*")
        if p.is_dir() and "__pycache__" not in p.parts and ".venv" not in p.parts
    )
    if not packages:  # pragma: no cover - hanya kalau struktur repo berubah total
        pytest.skip("tidak ada direktori sumber untuk diperiksa")

    # Dua detail yang keduanya sempat membuat test ini lulus tanpa memeriksa apa
    # pun — dicatat karena keduanya gagal secara senyap:
    #
    # 1. `--no-index` wajib. Tanpanya `check-ignore` melewatkan apa pun yang
    #    sudah ada di index, sehingga test berhenti menjaga persis setelah
    #    seseorang meng-`git add -f` file yang terlanjur tertelan.
    # 2. Path dikirim sebagai argumen, bukan lewat `--stdin`. Dengan
    #    `text=True`, Python di Windows menerjemahkan `\n` menjadi `\r\n` saat
    #    menulis ke stdin; git lalu mencari path yang berakhiran `\r` dan tidak
    #    pernah menemukannya. Keluarannya kosong dan assertion-nya lulus.
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--", *packages],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ignored = [line for line in result.stdout.splitlines() if line]
    assert not ignored, f"direktori sumber di-ignore oleh .gitignore: {ignored}"
