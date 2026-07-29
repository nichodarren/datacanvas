# DataCanvas

**Deterministic AI-Assisted Data Analysis Platform**

> Analisis data eksploratif yang hasilnya bisa dipertanggungjawabkan — setiap angka punya asal-usul,
> setiap langkah bisa diulang, dan AI mempercepat pekerjaan tanpa pernah menjadi sumber ketidakpastian.

---

## Status

🟢 **Fase 1 — fondasi & identitas. Gerbang 1 terlampaui.**
Auth, tenancy, otorisasi, object store, dan audit log sudah ada dan ber-test.
Tidak ada keterkaitan dengan layanan eksternal apa pun (GitHub, Vercel, Fly.io, API key) — itu disengaja.

## Mulai dari sini

📄 **[docs/DESIGN.md](docs/DESIGN.md)** — single source of truth. Baca ini sebelum apa pun.
🎯 **[docs/golden_queries.md](docs/golden_queries.md)** — definisi "MVP selesai". 🟢 Verified.

Kalau waktumu terbatas, baca urutan ini:

1. §1 Ringkasan Eksekutif — apa yang dibangun dan kenapa
2. §3 Design Philosophy — prinsip yang mengikat setiap keputusan berikutnya
3. §9 Domain Model — satu-satunya bagian yang benar-benar mahal untuk diubah nanti
4. §11.7 Spesifikasi `profile_column` — entry point utama produk
5. §15 Scope MVP & §16 Fitur yang Ditunda — batas yang dijaga
6. §20 Roadmap

## Struktur

```
docs/
  DESIGN.md              ← master design document (SSOT)
  golden_queries.md      ← kontrak evaluasi = definisi "MVP selesai"
  adr/                   ← ADR yang sudah "lulus" dari §18
backend/app/
  domain/  auth/  authz/  ingest/  schema/  storage/
  registry/  tools/  execution/  ai/  api/  repositories/
frontend/                ← diinisialisasi di Fase 2
eval/
  datasets/              ← dataset uji, di-commit (SHA-256 di golden_queries.md §3)
  fixtures/              ← generator messy_sales — self-verifying
  verify_expected_values.py
tests/
scripts/
```

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"        # atau: uv sync --group dev
pre-commit install             # memasang hook pre-commit DAN commit-msg
```

### Postgres (D-011)

**Kalau ada Docker:** `docker compose up -d` — selesai.

**Kalau tidak ada Docker** (mis. disk C: sempit, tanpa hak admin), pakai binary
portable. Tanpa installer, tanpa service Windows, semuanya di satu folder:

```powershell
# Unduh & ekstrak PostgreSQL 17 dari https://www.enterprisedb.com/download-postgresql-binaries
# → D:\pgsql   (zip berisi folder `pgsql`, jadi ekstrak ke D:\)

D:\pgsql\bin\initdb -D D:\pgdata -U datacanvas -A scram-sha-256 `
    --pwfile=<file berisi password> --encoding=UTF8 --locale=C
D:\pgsql\bin\pg_ctl -D D:\pgdata -l D:\pgdata\server.log start
D:\pgsql\bin\createdb -h localhost -U datacanvas datacanvas
D:\pgsql\bin\createdb -h localhost -U datacanvas datacanvas_test
```

`--locale=C` disengaja: urutan byte, deterministik dan identik di setiap mesin.
Cluster lokal, `docker-compose.yml`, dan CI ketiganya memakainya — kalau berbeda,
bug collation muncul hanya di satu tempat.

Lalu salin `.env.example` → `.env` dan jalankan migrasi:

```powershell
alembic upgrade head
```

Menghapusnya nanti = hentikan server, hapus `D:\pgsql` dan `D:\pgdata`.

## Menjalankan prototipe

Satu perintah menyalakan API dan frontend sekaligus, dan memeriksa prasyaratnya
lebih dulu:

```bash
sh scripts/demo.sh
```

Lalu buka **http://localhost:3000** → *Create an account* → tarik salah satu
file dari `eval/datasets/`. `messy_sales.csv` adalah yang paling menarik: tiga
kolomnya sengaja ambigu, dan grid akan menandainya beserta alasannya.

Sekali saja sebelum itu:

```bash
python -m pip install -e .     # supaya `python -m app` jalan dari akar repo
cd frontend && npm ci
```

### Manual, kalau perlu terpisah

```powershell
python -m app          # http://127.0.0.1:8000
cd frontend; npm run dev   # http://localhost:3000
```

> **Hanya lewat `python -m app`.** `uvicorn app.api.app:create_app --factory` akan
> start, menjawab `/health`, lalu mengembalikan **500 di setiap rute yang menyentuh
> database**. uvicorn mengabaikan event loop policy dan memakai `ProactorEventLoop`
> di Windows — satu-satunya loop yang tidak bisa dipakai psycopg. Aplikasi menolak
> start di loop yang salah dengan pesan yang menjelaskannya, alih-alih melayani 500.

## Perintah

```powershell
sh scripts/check.sh                           # SEMUA pemeriksaan CI sekaligus
ruff check . ; ruff format --check .          # lint & format
mypy backend eval tests                       # type check (strict)
pytest                                        # test
alembic upgrade head                          # migrasi skema
python eval/fixtures/build_messy_sales.py     # bangun ulang fixture kotor
python eval/verify_expected_values.py         # verifikasi kontrak evaluasi
```

Semuanya dijalankan CI pada setiap PR, plus dua pemeriksaan tambahan:
**fixture harus reproducible bit-per-bit** (kalau generator dan CSV ter-commit
tidak sinkron, build gagal), dan **`DATACANVAS_REQUIRE_DB=1`** yang mengubah
"tidak ada database" dari *skip* menjadi *gagal*. Tanpa itu, seluruh test isolasi
tenant yang menopang Gerbang 1 bisa diam-diam melewatkan dirinya sendiri dan
build tetap hijau.

> Tanpa Postgres berjalan, `pytest` tetap lulus — test integrasi ter-skip dan
> alasannya dicetak. Itu nyaman, dan justru itulah kenapa penjaga di atas ada.

⚠️ **CI belum pernah dieksekusi sekali pun** (R-17) — repo belum punya remote, jadi
seluruh bukti berasal dari satu mesin Windows. `scripts/check.sh` menjalankan
rangkaian yang sama di runner mana pun. Konsekuensi lain dari tidak adanya remote:
**tidak ada salinan project di luar laptop ini** (R-16).

## Gerbang 0 — checklist

- [x] Review DESIGN.md; OQ-1…OQ-7, OQ-10, OQ-11 diputuskan
- [x] D-001…D-020 → 🟢 Accepted (§18)
- [x] [`docs/golden_queries.md`](docs/golden_queries.md) — **29 query**, tier A–H · 🟢 Verified
- [x] Fixture `messy_sales` + dataset dibundel + **72/72 nilai harapan terverifikasi**
- [x] Panel penguji terekrut — 8 orang, peran terbagi per tahap (§20 Fase 0)
- [x] Cabut kredensial lama · **deployment Vercel/Fly lama dikonfirmasi lepas & mati** (2026-07-28)
- [x] Repo: struktur, tooling, lint, type check, test, CI, pre-commit
- [x] **Concept review** — sesi 1 selesai; sesi 2–3 dilewati secara sadar (DESIGN.md §20 Fase 0)
      · Hasil: **D-020** (batas scope), **FR-I.7**, **NFR-UX.5**, **R-15**

**🚦 Gerbang 0 terlampaui.**

## Gerbang 1 — checklist

- [x] Model domain murni + skema Postgres + migrasi 0001
- [x] INV-2 & INV-3 ditegakkan **trigger Postgres**, bukan kedisiplinan repository
- [x] Audit log append-only — trigger + grant terbatas (§13.7)
- [x] Auth: argon2id, sesi opaque ter-hash SHA-256, pencabutan per-perangkat, rate limit
- [x] Workspace/Project/Membership + provisioning otomatis saat registrasi
- [x] `data_access.open()` + `DataHandle` — satu-satunya jalan menuju data (INV-7)
- [x] Object store dengan dua penjaga traversal independen
- [x] Audit log + observability (correlation id, redaksi rahasia)
- [x] FR-A.5 — anggota workspace, peran, dan aturan **owner terakhir dilindungi**
- [x] FR-A.6 — reset password (token sekali pakai, cabut semua sesi) · pengiriman menunggu **OQ-14**

**🚦 Gerbang 1 terlampaui.** Dua pengguna di workspace berbeda tidak bisa saling
melihat apa pun — dibuktikan **penyapuan lintas-tenant yang digenerate dari manifest
rute** (§13.3.1), bukan daftar test yang ditulis tangan. Rute tenant-scoped baru
otomatis ikut tersapu.

242 test lulus · coverage 87%.

## Berikutnya

**Fase 2 — data masuk & dipahami** (§20): ingest + pratinjau + normalisasi Parquet,
inferensi skema + SchemaContract berversi, preview grid, editor skema + invalidasi.

**Gerbang 2:** unggah 3 dataset berbeda karakter (bersih / kotor / besar); tipe
terdeteksi masuk akal; koreksi menghasilkan SchemaContract v2; NFR-PERF.1 terpenuhi.

Satu hal dari Fase 1 yang sengaja tergantung: **pengiriman email**. Reset password
lengkap dan ber-test, tapi tidak ada penyedia email yang pernah diputuskan — itu
**OQ-14**, terbuka sampai Gerbang 6, dan §19.1 melarang mengambil ketergantungan
layanan eksternal diam-diam. Sampai itu diputuskan, token ditulis ke log oleh
pengirim versi pengembangan.

## Hubungan dengan versi lama

`../_legacy_datacanvas_backup/` adalah **referensi baca-saja**. Lihat §2.4 (pelajaran yang
diambil) dan Lampiran D (apa yang diangkut, apa yang ditinggalkan).
