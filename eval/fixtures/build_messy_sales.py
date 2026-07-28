"""Bangkitkan fixture `messy_sales` — dataset kotor yang cacatnya sengaja ditanam.

Dua peran (lihat docs/golden_queries.md §4):
  1. Fixture unit test untuk katalog peringatan kualitas PQ-1..PQ-14 (DESIGN.md §11.7.4).
  2. Skenario uji pengguna di Gerbang 4 — data publik yang cukup berantakan untuk
     menyerupai kenyataan, tanpa memakai data kantor (A-11).

Setiap cacat ditanam dengan jumlah yang PASTI, sehingga nilai harapan di
golden_queries.md benar menurut konstruksi dan tidak perlu diverifikasi ulang.

Determinisme: seed tetap + tanggal referensi tetap. Tidak ada `datetime.now()`
di mana pun — fixture tidak boleh berubah maknanya seiring waktu.

Jalankan:  python eval/fixtures/build_messy_sales.py
Keluaran:  eval/datasets/messy_sales.csv
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from pathlib import Path

import polars as pl

SEED = 20260728
N_ROWS = 5_000
OUT = Path(__file__).resolve().parents[1] / "datasets" / "messy_sales.csv"

# Tanggal referensi tetap. `promised_date` yang "di masa depan" memakai tahun 2099
# supaya PQ-11 tetap terpicu berapa pun tanggal test dijalankan.
BASE_DATE = date(2024, 1, 1)
FUTURE_DATE = date(2099, 6, 15)
PLACEHOLDER_DATE = date(1900, 1, 1)

rng = random.Random(SEED)


def _shuffled[T](values: list[T]) -> list[T]:
    """Acak dengan RNG ber-seed agar hasilnya reproducible."""
    out = list(values)
    rng.shuffle(out)
    return out


# --- order_id -- PQ-3: unik, integer, berurutan -> terlihat seperti identifier
order_id = list(range(1, N_ROWS + 1))

# --- order_date -- PQ-8: tanggal valid tapi disimpan sebagai TEKS
order_date = [(BASE_DATE + timedelta(days=rng.randint(0, 364))).isoformat() for _ in range(N_ROWS)]

# --- region -- PQ-5 (varian kapitalisasi) + PQ-10 (spasi di ujung)
# Total varian berspasi = 90 + 60 = 150.
region = _shuffled(
    ["Jakarta"] * 1100
    + ["jakarta"] * 180
    + ["Jakarta "] * 90
    + ["Surabaya"] * 1400
    + ["Medan"] * 1170
    + [" Medan"] * 60
    + ["Bandung"] * 1000
)

# --- customer_name -- PQ-6 bila keliru di-set categorical: 4.800 nilai unik
_names = [f"Customer {i:04d}" for i in range(1, 4801)]
customer_name = _shuffled(_names + [rng.choice(_names) for _ in range(N_ROWS - 4800)])

# --- amount -- PQ-1: 340 baris memakai 9999 sebagai penanda null terselubung
amount = _shuffled(
    [9999.0] * 340 + [round(rng.uniform(50_000, 5_000_000), 2) for _ in range(N_ROWS - 340)]
)

# --- discount_pct -- PQ-2: 4.960 baris bernilai 0.0 (99,2%) -> nyaris konstan
discount_pct = _shuffled([0.0] * 4960 + [round(rng.uniform(0.05, 0.35), 2) for _ in range(40)])

# --- qty -- PQ-4: hanya 5 nilai unik pada 5.000 baris -> terlihat seperti kategori
qty = [rng.randint(1, 5) for _ in range(N_ROWS)]

# --- status -- PQ-7 (satu nilai dominan 95,2%) + PQ-10 (spasi di ujung)
status = _shuffled(
    ["completed"] * 4760 + ["completed "] * 50 + ["pending"] * 130 + ["refunded"] * 60
)

# --- notes -- PQ-14: 3.100 null (62%)
notes = _shuffled(
    [None] * 3100
    + [rng.choice(["urgent", "gift wrap", "call first", "repeat order"]) for _ in range(1900)]
)

# --- signup_date -- PQ-12: 210 baris memakai tanggal placeholder 1900-01-01
signup_date = _shuffled(
    [PLACEHOLDER_DATE.isoformat()] * 210
    + [(BASE_DATE - timedelta(days=rng.randint(1, 1500))).isoformat() for _ in range(N_ROWS - 210)]
)

# --- legacy_code -- PQ-9: 97% murni numerik walau bertipe teks
legacy_code = _shuffled(
    [str(rng.randint(10_000, 99_999)) for _ in range(4850)]
    + [f"LG-{rng.randint(100, 999)}" for _ in range(150)]
)

# --- promised_date -- PQ-11: 95 baris bertanggal di masa depan
promised_date = _shuffled(
    [FUTURE_DATE.isoformat()] * 95
    + [(BASE_DATE + timedelta(days=rng.randint(1, 400))).isoformat() for _ in range(N_ROWS - 95)]
)

df = pl.DataFrame(
    {
        "order_id": order_id,
        "order_date": order_date,
        "region": region,
        "customer_name": customer_name,
        "amount": amount,
        "discount_pct": discount_pct,
        "qty": qty,
        "status": status,
        "notes": notes,
        "signup_date": signup_date,
        "legacy_code": legacy_code,
        "promised_date": promised_date,
    }
)

OUT.parent.mkdir(parents=True, exist_ok=True)
df.write_csv(OUT)

# --- Verifikasi diri: setiap cacat harus benar-benar tertanam -------------------
checks = {
    "PQ-1  amount == 9999": (df.filter(pl.col("amount") == 9999.0).height, 340),
    "PQ-2  discount_pct == 0": (df.filter(pl.col("discount_pct") == 0.0).height, 4960),
    "PQ-3  order_id unik": (df["order_id"].n_unique(), N_ROWS),
    "PQ-4  qty distinct": (df["qty"].n_unique(), 5),
    "PQ-5  varian 'jakarta'": (
        df.filter(pl.col("region").str.strip_chars().str.to_lowercase() == "jakarta").height,
        1370,
    ),
    "PQ-7  status 'completed' mentah": (df.filter(pl.col("status") == "completed").height, 4760),
    "PQ-9  legacy_code numerik": (
        df.filter(pl.col("legacy_code").str.contains(r"^\d+$")).height,
        4850,
    ),
    "PQ-10 region berspasi": (
        df.filter(pl.col("region") != pl.col("region").str.strip_chars()).height,
        150,
    ),
    "PQ-10 status berspasi": (
        df.filter(pl.col("status") != pl.col("status").str.strip_chars()).height,
        50,
    ),
    "PQ-11 promised_date 2099": (
        df.filter(pl.col("promised_date") == FUTURE_DATE.isoformat()).height,
        95,
    ),
    "PQ-12 signup_date 1900": (
        df.filter(pl.col("signup_date") == PLACEHOLDER_DATE.isoformat()).height,
        210,
    ),
    "PQ-14 notes null": (df["notes"].null_count(), 3100),
    "region distinct mentah": (df["region"].n_unique(), 7),
    "customer_name distinct": (df["customer_name"].n_unique(), 4800),
    "status distinct mentah": (df["status"].n_unique(), 4),
}

print(f"messy_sales.csv  {df.height} baris x {df.width} kolom  ->  {OUT}")
print("-" * 58)
ok = True
for label, (actual, expected) in checks.items():
    mark = "OK " if actual == expected else "BEDA"
    if actual != expected:
        ok = False
    print(f"  [{mark}] {label:<34} {actual}  (harap {expected})")
print("-" * 58)
print(
    "SEMUA CACAT TERTANAM SESUAI SPESIFIKASI"
    if ok
    else "!! ADA YANG TIDAK COCOK — perbaiki generator atau spesifikasi"
)
