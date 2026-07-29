"""Bukti Gerbang 2 (§20) — diukur, bukan diklaim.

Gerbang 2 berbunyi: *unggah 3 dataset berbeda karakter (bersih / kotor / besar);
tipe terdeteksi masuk akal; koreksi menghasilkan SchemaContract v2; NFR-PERF.1
terpenuhi.*

Skrip ini menjalankan tiga dari empat kriteria itu terhadap **jalur kode yang
sebenarnya** — normalisasi, engine, dan aturan inferensi yang sama yang dipakai
API — lalu mencetak angkanya. Kriteria keempat (koreksi → v2) butuh basis data
dan sudah dibuktikan `tests/integration/test_schema_override.py`; ia disebut di
sini agar gerbangnya terbaca utuh, bukan diukur ulang.

**Kenapa ada sebagai skrip terpisah, bukan test.** Ia butuh `wide_orders.csv`
(480 MB, tidak di-commit) dan memakan puluhan detik. Menjadikannya test berarti
seluruh suite bergantung pada file yang tidak ada di checkout bersih — atau,
lebih buruk, test-nya di-skip diam-diam dan gerbangnya lolos tanpa diukur.

Jalankan:
    python eval/fixtures/build_wide_orders.py     # sekali, ± 1 menit
    python eval/gate2_evidence.py
"""

from __future__ import annotations

import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.authz import data_access
from app.authz.data_access import DataHandle
from app.domain.data import DatasetVersion
from app.domain.enums import SourceFormat
from app.domain.ids import (
    DatasetId,
    DatasetVersionId,
    SessionId,
    UserId,
    WorkspaceId,
)
from app.domain.principal import Principal
from app.ingest import normalize
from app.ingest.dialect import detect
from app.ingest.limits import PREVIEW_BYTES
from app.schema.inference import build_columns
from app.storage.engine import DuckDBEngine
from app.storage.object_store import FilesystemObjectStore
from app.storage.uri import dataset_version_data_uri

DATASETS = Path(__file__).resolve().parent / "datasets"
T0 = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)

#: NFR-PERF.1 — halaman pertama preview grid, p95, dataset <= 5 juta baris.
FIRST_PAGE_BUDGET_S = 1.0
#: NFR-PERF.4 — ingest + normalisasi file 100 MB.
INGEST_BUDGET_S_PER_100MB = 30.0
#: Berapa kali halaman pertama diambil. p95 dari satu pengukuran bukan p95.
PAGE_SAMPLES = 20


@dataclass(frozen=True, slots=True)
class Result:
    name: str
    character: str
    source_mb: float
    rows: int
    columns: int
    ingest_s: float
    infer_s: float
    first_page_p95_ms: float
    types: dict[str, str]


def _measure(store: FilesystemObjectStore, engine: DuckDBEngine, path: Path) -> Result:
    workspace = WorkspaceId(uuid.uuid4())
    dataset = DatasetId(uuid.uuid4())
    version_id = DatasetVersionId(uuid.uuid4())
    uri = dataset_version_data_uri(workspace, dataset, version_id)

    head = path.open("rb").read(PREVIEW_BYTES)
    dialect = detect(head, is_prefix=path.stat().st_size > len(head))

    started = time.perf_counter()
    info = normalize.normalize_file(path, SourceFormat.CSV, store.writable_path(uri), dialect)
    ingest_s = time.perf_counter() - started

    version = DatasetVersion(
        id=version_id,
        dataset_id=dataset,
        version_no=1,
        content_hash=info.content_hash,
        parquet_uri=str(uri),
        row_count=info.row_count,
        column_count=info.column_count,
        byte_size=info.byte_size,
        ingested_at=T0,
        ingested_by=UserId(uuid.uuid4()),
    )
    handle = DataHandle(
        principal=Principal(
            user_id=UserId(uuid.uuid4()), session_id=SessionId(uuid.uuid4()), memberships={}
        ),
        workspace_id=workspace,
        version=version,
        uri=uri,
        _store=store,
        _grant=data_access._GRANT,
    )

    started = time.perf_counter()
    columns = build_columns(engine.column_statistics(handle))
    infer_s = time.perf_counter() - started

    # Halaman pertama, berulang kali. Halaman *pertama* saja akan mengukur cache
    # sistem berkas yang dingin sekali dan hangat sesudahnya — p95 atas beberapa
    # pengambilan adalah yang sebenarnya dirasakan pengguna yang membuka grid.
    timings = []
    for _ in range(PAGE_SAMPLES):
        started = time.perf_counter()
        engine.page(handle, offset=0, limit=100)
        timings.append((time.perf_counter() - started) * 1000)
    timings.sort()

    return Result(
        name=path.stem,
        character="",
        source_mb=path.stat().st_size / 1024 / 1024,
        rows=info.row_count,
        columns=info.column_count,
        ingest_s=ingest_s,
        infer_s=infer_s,
        first_page_p95_ms=timings[int(len(timings) * 0.95) - 1],
        types={c.name: c.logical_type.value for c in columns},
    )


def main() -> int:
    targets = [
        ("titanic.csv", "bersih"),
        ("messy_sales.csv", "kotor"),
        ("wide_orders.csv", "besar"),
    ]
    missing = [name for name, _ in targets if not (DATASETS / name).is_file()]
    if missing:
        print(f"Dataset belum ada: {', '.join(missing)}")
        if "wide_orders.csv" in missing:
            print("  Bangun dulu:  python eval/fixtures/build_wide_orders.py")
        return 1

    store = FilesystemObjectStore(Path(mkdtemp()))
    engine = DuckDBEngine()

    print("=" * 78)
    print("BUKTI GERBANG 2 — tiga dataset berbeda karakter (§20)")
    print("=" * 78)

    results = []
    for name, character in targets:
        result = _measure(store, engine, DATASETS / name)
        results.append((character, result))
        print(f"\n[{character}] {name} — {result.source_mb:.1f} MB")
        print(f"  {result.rows:,} baris x {result.columns} kolom")
        print(f"  ingest + normalisasi : {result.ingest_s:6.2f} s")
        print(f"  inferensi skema      : {result.infer_s:6.2f} s (satu lintasan penuh, FR-B.3)")
        print(f"  halaman pertama p95  : {result.first_page_p95_ms:6.1f} ms")
        kinds = sorted({t for t in result.types.values()})
        print(f"  tipe yang muncul     : {', '.join(kinds)}")

    print("\n" + "=" * 78)
    print("KRITERIA")
    print("=" * 78)

    failures: list[str] = []

    for character, result in results:
        ok = result.first_page_p95_ms < FIRST_PAGE_BUDGET_S * 1000
        mark = "OK  " if ok else "GAGAL"
        print(
            f"  {mark} NFR-PERF.1 halaman pertama < 1 s [{character}]: "
            f"{result.first_page_p95_ms:.1f} ms"
        )
        if not ok:
            failures.append(f"NFR-PERF.1 pada {result.name}")

    # Diukur sebagai **ingest + inferensi**, bukan ingest saja. NFR-PERF.4
    # hanya menyebut "ingest + normalisasi ke Parquet", dan diambil harfiah
    # angkanya jadi 1,5 detik yang menyenangkan dan tidak jujur: dari sisi
    # pengguna unggahan belum selesai sampai skemanya ada (§10.4 menempatkan
    # inferensi di dalam alur ingest). Mengukur separuh yang cepat adalah cara
    # membuat gerbang lolos tanpa membuktikan apa pun.
    for character, result in results:
        budget = INGEST_BUDGET_S_PER_100MB * max(result.source_mb, 1.0) / 100
        total = result.ingest_s + result.infer_s
        ok = total < budget
        mark = "OK  " if ok else "GAGAL"
        print(
            f"  {mark} NFR-PERF.4 ingest+inferensi [{character}]: "
            f"{total:.2f} s untuk {result.source_mb:.0f} MB "
            f"(anggaran {budget:.1f} s)"
        )
        if not ok:
            failures.append(f"NFR-PERF.4 pada {result.name}")

    # "Tipe terdeteksi masuk akal" tidak bisa diukur otomatis tanpa menjadi
    # tautologis. Yang BISA diperiksa: aturan cakupan 100% masih berlaku pada
    # skala penuh — kolom yang 97% numerik harus tetap teks di 5 juta baris,
    # sama seperti di 5.000 (D-029).
    large = next(r for c, r in results if c == "besar")
    coverage_ok = large.types.get("legacy_code") == "text"
    print(
        f"  {'OK  ' if coverage_ok else 'GAGAL'} D-029 cakupan 100% pada 5 juta baris: "
        f"legacy_code = {large.types.get('legacy_code')}"
    )
    if not coverage_ok:
        failures.append("D-029 pada skala penuh")

    print(
        "  ----  Koreksi -> SchemaContract v2 (FR-C.3): dibuktikan "
        "tests/integration/test_schema_override.py"
    )

    print()
    if failures:
        print(f"GERBANG 2 BELUM TERLAMPAUI — {len(failures)} kriteria gagal:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("SELURUH KRITERIA TERUKUR GERBANG 2 TERPENUHI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
