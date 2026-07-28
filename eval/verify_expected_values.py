"""Verifikasi setiap `expected_values` di docs/golden_queries.md terhadap file nyata.

Kenapa skrip ini ada (golden_queries.md §6): nilai harapan awalnya ditulis dari
versi kanonik masing-masing dataset, BUKAN dari file yang benar-benar dibundel.
Varian file untuk dataset yang sama beredar luas. Menguji terhadap angka yang
salah menghasilkan kegagalan yang akan disalahartikan sebagai bug planner — dan
itu membuang berhari-hari.

Aturannya: kalau skrip ini dan dokumen berbeda, **dokumen yang dikoreksi.**

Keluar dengan status non-nol bila ada yang meleset, sehingga bisa dipakai
langsung sebagai gerbang CI.

Jalankan:  python eval/verify_expected_values.py
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import polars as pl

DATA = Path(__file__).resolve().parent / "datasets"

DATASET_FILES = ("titanic.csv", "tips.csv", "hotel_bookings.csv", "messy_sales.csv")


@dataclass(frozen=True)
class Check:
    """Satu nilai harapan: apa kata dokumen vs apa kata file."""

    label: str
    documented: float
    computed: float | None
    tol: float  # toleransi relatif; 0 berarti harus persis

    @property
    def ok(self) -> bool:
        if self.computed is None:
            return False
        if self.tol == 0:
            return self.documented == self.computed
        if self.documented == 0:
            return self.computed == 0
        return abs(self.computed - self.documented) / abs(self.documented) <= self.tol


checks: list[Check] = []


def check(label: str, documented: float, computed: float | None, tol: float = 0.005) -> None:
    checks.append(Check(label, documented, computed, tol))


def num(value: object) -> float:
    """Sempitkan hasil agregasi polars (union lebar) menjadi float."""
    if not isinstance(value, int | float):
        raise TypeError(f"nilai agregasi bukan numerik: {value!r}")
    return float(value)


def rnd(value: object, digits: int) -> float:
    return round(num(value), digits)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def pct(n: int, total: int) -> float:
    return round(100 * n / total, 2)


print("=" * 78)
print("SIDIK JARI FILE")
print("=" * 78)
for name in DATASET_FILES:
    p = DATA / name
    if p.exists():
        print(f"  {name:<22} {p.stat().st_size:>10,} B   sha256:{sha256(p)[:16]}…")
    else:
        print(f"  {name:<22} TIDAK ADA")

# ---------------------------------------------------------------- TITANIC ----
t = pl.read_csv(DATA / "titanic.csv", null_values=["", "NA", "N/A"])
print("\nKolom titanic:", t.columns)

check("titanic · jumlah baris", 891, t.height, 0)
check("titanic · jumlah kolom", 12, t.width, 0)

age_null = t["Age"].null_count()
check("titanic · Age null (n)", 177, age_null, 0)
check("titanic · Age null (%)", 19.87, pct(age_null, t.height))
check("titanic · Cabin null (%)", 77.10, pct(t["Cabin"].null_count(), t.height))

check("titanic · Age mean", 29.70, rnd(t["Age"].mean(), 2))
check("titanic · Age median", 28.0, rnd(t["Age"].median(), 2))
check("titanic · Age std", 14.53, rnd(t["Age"].std(), 2))

fare = t.group_by("Pclass").agg(pl.col("Fare").mean().alias("m")).sort("Pclass")
fmap = {int(num(r["Pclass"])): rnd(r["m"], 2) for r in fare.to_dicts()}
check("titanic · mean Fare Pclass=1", 84.15, fmap[1])
check("titanic · mean Fare Pclass=2", 20.66, fmap[2])
check("titanic · mean Fare Pclass=3", 13.68, fmap[3])

check("titanic · Age < 18 (n)", 113, t.filter(pl.col("Age") < 18).height, 0)

surv = int(num(t["Survived"].sum()))
check("titanic · Survived total", 342, surv, 0)
check("titanic · Survived (%)", 38.38, pct(surv, t.height))
check("titanic · duplikat baris-penuh", 0, t.height - t.unique().height, 0)

ct = t.group_by(["Pclass", "Survived"]).len().sort(["Pclass", "Survived"])
cmap = {(int(num(r["Pclass"])), int(num(r["Survived"]))): int(num(r["len"])) for r in ct.to_dicts()}
check("titanic · crosstab 1st selamat", 136, cmap[(1, 1)], 0)
check("titanic · crosstab 1st tidak", 80, cmap[(1, 0)], 0)
check("titanic · crosstab 2nd selamat", 87, cmap[(2, 1)], 0)
check("titanic · crosstab 2nd tidak", 97, cmap[(2, 0)], 0)
check("titanic · crosstab 3rd selamat", 119, cmap[(3, 1)], 0)
check("titanic · crosstab 3rd tidak", 372, cmap[(3, 0)], 0)

# ------------------------------------------------------------------- TIPS ----
tp = pl.read_csv(DATA / "tips.csv")
print("Kolom tips:", tp.columns)

check("tips · jumlah baris", 244, tp.height, 0)
check("tips · jumlah kolom", 7, tp.width, 0)
check("tips · total_bill mean", 19.79, rnd(tp["total_bill"].mean(), 2))
check("tips · total_bill null", 0, tp["total_bill"].null_count(), 0)

day = tp.group_by("day").agg(pl.col("tip").mean().alias("m"))
dmap = {str(r["day"]): rnd(r["m"], 3) for r in day.to_dicts()}
for d, doc in (("Thur", 2.771), ("Fri", 2.735), ("Sat", 2.993), ("Sun", 3.255)):
    check(f"tips · mean tip {d}", doc, dmap.get(d))

tp2 = tp.with_columns((pl.col("tip") / pl.col("total_bill")).alias("tip_rate"))
sm = tp2.group_by("smoker").agg(pl.col("tip_rate").mean().alias("m"))
smap = {str(r["smoker"]): rnd(r["m"], 3) for r in sm.to_dicts()}
check("tips · tip_rate perokok", 0.163, smap.get("Yes"))
check("tips · tip_rate bukan perokok", 0.159, smap.get("No"))
check("tips · corr total_bill~tip", 0.676, rnd(tp.select(pl.corr("total_bill", "tip")).item(), 3))

# --------------------------------------------------------- HOTEL BOOKINGS ----
hb = pl.read_csv(
    DATA / "hotel_bookings.csv",
    null_values=["", "NA", "NULL", "Undefined"],
    infer_schema_length=10000,
)
print("Kolom hotel_bookings:", len(hb.columns))

check("hotel · jumlah baris", 119_390, hb.height, 0)
check("hotel · jumlah kolom", 32, hb.width, 0)

canc = int(num(hb["is_canceled"].sum()))
check("hotel · dibatalkan (n)", 44_224, canc, 0)
check("hotel · dibatalkan (%)", 37.04, pct(canc, hb.height))
check("hotel · tidak dibatalkan (n)", 75_166, hb.height - canc, 0)

for col, doc_pct in (("company", 94.31), ("agent", 13.69), ("country", 0.41)):
    if col in hb.columns:
        check(f"hotel · null% {col}", doc_pct, pct(hb[col].null_count(), hb.height))

check("hotel · adr mean", 101.83, rnd(hb["adr"].mean(), 2))
check("hotel · lead_time mean", 104.01, rnd(hb["lead_time"].mean(), 2))

byhotel = hb.group_by("hotel").agg(pl.len().alias("n"), pl.col("is_canceled").sum().alias("c"))
hmap = {str(r["hotel"]): (int(num(r["n"])), int(num(r["c"]))) for r in byhotel.to_dicts()}
for key, doc_rate in (("City Hotel", 41.7), ("Resort Hotel", 27.8)):
    if key in hmap:
        n_rows, n_canc = hmap[key]
        check(f"hotel · tingkat batal {key}", doc_rate, round(100 * n_canc / n_rows, 1), 0.01)

# ------------------------------------------------- TIER C BARU (pasca D-020) ---
tp3 = tp.with_columns((pl.col("tip") / pl.col("total_bill")).alias("tip_rate"))
rate_by_day = tp3.group_by("day").agg(pl.col("tip_rate").mean().alias("m"))
rmap = {str(r["day"]): rnd(r["m"], 4) for r in rate_by_day.to_dicts()}
for d, doc in (("Fri", 0.1699), ("Sun", 0.1669), ("Thur", 0.1613), ("Sat", 0.1532)):
    check(f"C1 · tips tip_rate {d}", doc, rmap.get(d))

minors = t.filter(pl.col("Age") < 18)
check("C3 · titanic <18 total", 113, minors.height, 0)
by_class = minors.group_by("Pclass").agg(pl.len().alias("n"), pl.col("Survived").sum().alias("s"))
mmap = {int(num(r["Pclass"])): (int(num(r["n"])), int(num(r["s"]))) for r in by_class.to_dicts()}
for pc, doc_n, doc_rate in ((1, 12, 91.7), (2, 23, 91.3), (3, 78, 37.2)):
    n_rows, n_surv = mmap[pc]
    check(f"C3 · <18 Pclass={pc} baris", doc_n, n_rows, 0)
    check(f"C3 · <18 Pclass={pc} selamat %", doc_rate, round(100 * n_surv / n_rows, 1), 0.01)

# ------------------------------------------- MESSY_SALES: TIER C5 & TIER H -----
# infer_schema_length=None wajib: `legacy_code` 97% numerik, nilai alfanumerik
# pertama muncul jauh di bawah. Ini PQ-9 muncul di alam liar — lihat FR-B.3.
ms = pl.read_csv(DATA / "messy_sales.csv", infer_schema_length=None)

region_raw = ms.group_by("region").agg(pl.len().alias("n"))
check("C5 · messy region distinct mentah", 7, region_raw.height, 0)
rawmap = {str(r["region"]): int(num(r["n"])) for r in region_raw.to_dicts()}
for name, doc_n in (("Surabaya", 1400), ("Medan", 1170), ("Jakarta", 1100), ("Bandung", 1000)):
    check(f"C5 · region '{name}'", doc_n, rawmap.get(name), 0)

ms_norm = ms.with_columns(pl.col("region").str.strip_chars().str.to_lowercase().alias("rn"))
check("H1 · region distinct setelah normalisasi", 4, ms_norm["rn"].n_unique(), 0)
check(
    "H1 · 'jakarta' setelah normalisasi", 1370, ms_norm.filter(pl.col("rn") == "jakarta").height, 0
)
check("H1 · 'medan' setelah normalisasi", 1230, ms_norm.filter(pl.col("rn") == "medan").height, 0)

check("H2 · amount == 9999", 340, ms.filter(pl.col("amount") == 9999.0).height, 0)
check("H2 · mean amount mentah", 2_352_812.07, rnd(ms["amount"].mean(), 2))

ms_clean = ms.with_columns(
    pl.when(pl.col("amount") == 9999.0).then(None).otherwise(pl.col("amount")).alias("amt")
)
check("H2 · mean amount setelah null marker", 2_523_746.93, rnd(ms_clean["amt"].mean(), 2))

p1 = num(ms_clean["amt"].quantile(0.01))
p99 = num(ms_clean["amt"].quantile(0.99))
check("H3 · p1 setelah dibersihkan", 102_806.08, round(p1, 2))
check("H3 · p99 setelah dibersihkan", 4_954_715.07, round(p99, 2))
check("H3 · baris di bawah p1", 47, ms_clean.filter(pl.col("amt") < p1).height, 0)
check("H3 · baris di atas p99", 47, ms_clean.filter(pl.col("amt") > p99).height, 0)
check("H3 · p1 MENTAH (tercemar penanda null)", 9999.0, rnd(ms["amount"].quantile(0.01), 2), 0)

check("H4 · notes non-null", 1900, ms.height - ms["notes"].null_count(), 0)

# ----------------------------------------------------------------- LAPORAN ---
print("\n" + "=" * 78)
print("PERBANDINGAN: DOKUMEN  vs  FILE NYATA")
print("=" * 78)
print(f"  {'':<4}{'Item':<36}{'Dokumen':>12}{'File':>12}")
print("-" * 78)

for c in checks:
    print(f"  {'OK ' if c.ok else 'BEDA':<4}{c.label:<36}{c.documented!s:>12}{c.computed!s:>12}")

print("-" * 78)

mismatch = [c for c in checks if not c.ok]
if mismatch:
    print(f"\n{len(mismatch)} NILAI PERLU DIKOREKSI DI docs/golden_queries.md:\n")
    for c in mismatch:
        print(f"  - {c.label}: {c.documented}  ->  {c.computed}")
    print("\nKoreksi DOKUMENnya, bukan filenya.")
    raise SystemExit(1)

print(f"\nSEMUA {len(checks)} NILAI HARAPAN COCOK — golden_queries.md valid sebagai kontrak.")
