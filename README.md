# DataCanvas

**Deterministic AI-Assisted Data Analysis Platform**

> Analisis data eksploratif yang hasilnya bisa dipertanggungjawabkan — setiap angka punya asal-usul,
> setiap langkah bisa diulang, dan AI mempercepat pekerjaan tanpa pernah menjadi sumber ketidakpastian.

---

## Status

🟡 **Fase 0 — desain & kontrak.** Belum ada kode produk.
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

## Perintah

```powershell
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

**🚦 Gerbang 0 terlampaui.** Berikutnya: Fase 1.

## Berikutnya

**Fase 1 — fondasi & identitas** (§20): model domain + skema Postgres, auth & sesi,
Workspace/Project/Membership, lapisan otorisasi + test INV-7, object store, audit log.

**Gerbang 1:** dua pengguna di workspace berbeda tidak bisa saling melihat apa pun —
dibuktikan test otomatis, bukan pemeriksaan manual.

## Hubungan dengan versi lama

`../_legacy_datacanvas_backup/` adalah **referensi baca-saja**. Lihat §2.4 (pelajaran yang
diambil) dan Lampiran D (apa yang diangkut, apa yang ditinggalkan).
