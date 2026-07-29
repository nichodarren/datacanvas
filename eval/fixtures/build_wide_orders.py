"""Bangkitkan `wide_orders` — dataset **besar** untuk Gerbang 2 (§20).

Gerbang 2 menuntut tiga dataset berbeda karakter: bersih, kotor, dan **besar**.
Dua yang pertama sudah ada (`titanic`, `messy_sales`). Yang ketiga tidak, dan
tanpanya NFR-PERF.1 — halaman pertama preview grid < 1 detik untuk dataset
sampai 5 juta baris — tidak pernah benar-benar diuji, hanya diasumsikan.

**Kenapa digenerate, bukan diunduh.** Reproducibility menuntut semua orang
menguji terhadap byte yang sama persis (golden_queries.md §3). Dataset publik
yang diunduh melanggar itu kecuali di-mirror, dan menambah ketergantungan
jaringan pada CI. Generator ber-seed memberi byte identik di mesin mana pun,
tanpa jaringan sama sekali.

**Kenapa file-nya tidak di-commit.** Ia ± 250 MB. Skripnya yang masuk repo;
SHA-256 hasilnya menjadi kontrak di `golden_queries.md` §3, dan siapa pun bisa
membangunnya ulang dalam hitungan detik.

Karakternya sengaja **bersih tapi besar** — bukan kotor. `messy_sales` sudah
menguji kekotoran pada 5.000 baris; menggabungkan keduanya akan membuat
kegagalan performa dan kegagalan inferensi tidak bisa dibedakan.

Determinisme: seed tetap, tanggal referensi tetap, tanpa `datetime.now()`.

Jalankan:  python eval/fixtures/build_wide_orders.py
Keluaran:  eval/datasets/wide_orders.csv   (tidak di-commit; lihat .gitignore)
"""

from __future__ import annotations

import argparse
import hashlib
import random
from datetime import date, timedelta
from pathlib import Path

import polars as pl

SEED = 20260729
#: Tepat di batas NFR-SCALE.1. Gerbang 2 harus diuji di batasnya, bukan di
#: bawahnya — batas yang tak pernah disentuh adalah batas yang tak diketahui.
N_ROWS = 5_000_000
OUT = Path(__file__).resolve().parents[1] / "datasets" / "wide_orders.csv"

BASE_DATE = date(2022, 1, 1)

REGIONS = ("Jakarta", "Surabaya", "Bandung", "Medan", "Semarang", "Makassar")
CHANNELS = ("web", "mobile", "store", "partner")
STATUSES = ("completed", "pending", "refunded", "cancelled")


def build(n_rows: int, *, seed: int = SEED) -> pl.DataFrame:
    """Dua belas kolom yang mencakup setiap tipe logis yang bisa diinferensi.

    Ini bukan hiasan: dataset besar yang seluruhnya numerik akan menguji
    performa dan **tidak menguji apa pun tentang inferensi pada skala**. Setiap
    aturan D-029 harus punya minimal satu kolom di sini.

    **RNG-nya dibuat di dalam fungsi, bukan di level modul.** Sebuah RNG modul
    maju setiap kali dipakai, sehingga pemanggilan kedua dalam satu proses
    menghasilkan data berbeda — reproducible sebagai skrip, tidak reproducible
    sebagai fungsi. Perbedaan itu tidak terlihat sampai ada yang mencoba
    mengujinya, dan test reproducibility yang memanggil `build` dua kali adalah
    hal pertama yang wajar dilakukan.
    """
    rng = random.Random(seed)
    return pl.DataFrame(
        {
            # integer, unik → PQ-3 (terlihat identifier)
            "order_id": [str(i + 1) for i in range(n_rows)],
            # date
            "order_date": [
                (BASE_DATE + timedelta(days=rng.randrange(1_000))).isoformat()
                for _ in range(n_rows)
            ],
            # datetime — memaksa aturan date/datetime tetap terpisah pada skala
            "created_at": [
                f"{(BASE_DATE + timedelta(days=rng.randrange(1_000))).isoformat()}"
                f" {rng.randrange(24):02d}:{rng.randrange(60):02d}:00"
                for _ in range(n_rows)
            ],
            # categorical, kardinalitas rendah
            "region": [rng.choice(REGIONS) for _ in range(n_rows)],
            "channel": [rng.choice(CHANNELS) for _ in range(n_rows)],
            "status": [rng.choice(STATUSES) for _ in range(n_rows)],
            # text, kardinalitas tinggi → harus TIDAK jadi categorical
            "customer_ref": [f"CUST-{rng.randrange(400_000):06d}" for _ in range(n_rows)],
            # decimal
            "amount": [f"{rng.randrange(1_000, 50_000_000) / 100:.2f}" for _ in range(n_rows)],
            # integer, kardinalitas rendah → PQ-4 (terlihat kategori)
            "qty": [str(rng.randrange(1, 9)) for _ in range(n_rows)],
            # boolean kata
            "is_gift": ["yes" if rng.random() < 0.08 else "no" for _ in range(n_rows)],
            # 97% numerik + sisanya alfanumerik — bentuk `legacy_code`, pada skala.
            # Inilah yang membuktikan aturan cakupan 100% (D-029) berjalan atas
            # 5 juta baris dan bukan hanya atas 5.000.
            "legacy_code": [
                f"LG-{rng.randrange(1_000):03d}"
                if rng.random() < 0.03
                else str(rng.randrange(10_000_000))
                for _ in range(n_rows)
            ],
            # kolom mayoritas kosong → PQ-14
            "note": [
                "" if rng.random() < 0.7 else rng.choice(("ok", "check", "late"))
                for _ in range(n_rows)
            ],
        }
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--rows",
        type=int,
        default=N_ROWS,
        help="jumlah baris (default: batas NFR-SCALE.1). Perkecil untuk uji cepat.",
    )
    rows = parser.parse_args().rows

    OUT.parent.mkdir(parents=True, exist_ok=True)
    frame = build(rows)
    frame.write_csv(OUT)

    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"{OUT.name}: {frame.height:,} baris x {frame.width} kolom, {size_mb:.1f} MB")
    if rows == N_ROWS:
        # Hash hanya bermakna sebagai kontrak untuk jumlah baris penuh.
        print(f"sha256: {_sha256(OUT)}")
    else:
        print("(jumlah baris bukan default — hash tidak dicetak, ia bukan kontraknya)")


if __name__ == "__main__":
    main()
