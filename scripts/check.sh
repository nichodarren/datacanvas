#!/usr/bin/env sh
#
# Semua pemeriksaan yang dijalankan CI, dalam satu skrip yang bisa dijalankan
# runner mana pun — Git Bash di Windows, shell Linux, container, atau CI host
# selain GitHub.
#
# Kenapa ada: `.github/workflows/ci.yml` menuliskan langkah-langkah ini dalam
# YAML spesifik GitHub Actions, dan **belum pernah dieksekusi sekali pun**
# (R-16). Selama itu masih benar, satu-satunya cara menjalankan rangkaian
# lengkapnya adalah mengetik ulang perintahnya dari ingatan. Skrip ini
# menghapus langkah itu, sekaligus membuat pindah CI host nanti menjadi
# perubahan satu baris alih-alih penulisan ulang.
#
# Pemakaian:
#   sh scripts/check.sh
#
# POSIX sh, bukan bash: satu-satunya jaminan yang ada di setiap runner.

set -eu

cd "$(dirname "$0")/.."

# Hormati venv kalau ada, supaya tidak perlu mengaktifkannya lebih dulu.
if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"      # Windows
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"              # Linux / macOS
else
    PY="python"
fi

step() {
    printf '\n\033[1m>> %s\033[0m\n' "$1"
}

step "Lint & format"
"$PY" -m ruff check .
"$PY" -m ruff format --check .

step "Type check (mypy strict)"
"$PY" -m mypy backend eval tests

step "Type check lintas platform"
# mypy memeriksa kode dari sudut pandang platform tempat ia berjalan. Kode yang
# lulus di Windows karena `asyncio.ProactorEventLoop` ada di sana akan gagal di
# Linux, di mana simbol itu tidak ada — dan sebaliknya. Persis itu yang terjadi:
# run CI pertama project ini menemukannya, sementara seluruh pemeriksaan lokal
# hijau. Menjalankan sudut pandang yang berlawanan di sini memindahkan temuannya
# ke laptop, tempat memperbaikinya makan detik, bukan menunggu antrean runner.
if [ "$(uname -s 2>/dev/null || echo unknown)" = "Linux" ]; then
    OTHER_PLATFORM="win32"
else
    OTHER_PLATFORM="linux"
fi
printf '   --platform %s\n' "$OTHER_PLATFORM"
"$PY" -m mypy --platform "$OTHER_PLATFORM" backend eval tests

step "Tests"
# DATACANVAS_REQUIRE_DB mengubah "database tidak ada" dari skip menjadi gagal.
# Tanpa itu seluruh test isolasi tenant penopang Gerbang 1 bisa melewatkan
# dirinya sendiri sementara build tetap hijau. Diset hanya bila pemanggil
# sudah menyediakan database — di laptop tanpa Postgres, skip memang benar.
if [ -n "${DATABASE_URL:-}${TEST_DATABASE_URL:-}" ]; then
    DATACANVAS_REQUIRE_DB=1 "$PY" -m pytest --cov --cov-report=term-missing
else
    printf '   (tanpa DATABASE_URL — test integrasi akan ter-skip)\n'
    "$PY" -m pytest --cov --cov-report=term-missing
fi

step "Fixture reproducible bit-per-bit"
# Kalau generator dan CSV ter-commit tidak sinkron, nilai harapan golden query
# mungkin sudah tidak valid — dan itu harus gagal, bukan lolos diam-diam.
before=$(sha256sum eval/datasets/messy_sales.csv | cut -d' ' -f1)
"$PY" eval/fixtures/build_messy_sales.py >/dev/null
after=$(sha256sum eval/datasets/messy_sales.csv | cut -d' ' -f1)
if [ "$before" != "$after" ]; then
    printf '\033[31mmessy_sales.csv tidak reproducible.\033[0m\n'
    printf '  sebelum: %s\n  sesudah: %s\n' "$before" "$after"
    exit 1
fi
printf '   %s\n' "$after"

step "Frontend (kalau dependensinya sudah terpasang)"
# Frontend punya toolchain sendiri. Dilewati kalau `npm ci` belum pernah jalan,
# karena memaksa checkout backend-saja untuk memasang Node adalah pajak yang
# tidak berhubungan. CI memasangnya, jadi di sana langkah ini selalu jalan.
if [ -d "frontend/node_modules" ]; then
    (cd frontend && npx tsc --noEmit)
    (cd frontend && npx next build --no-lint >/dev/null)
    printf '   typecheck + build OK\n'
else
    printf '   (frontend/node_modules belum ada — lewati; jalankan npm ci di frontend/)\n'
fi

step "Nilai harapan golden query"
"$PY" eval/verify_expected_values.py

printf '\n\033[32mSemua pemeriksaan lulus.\033[0m\n'
