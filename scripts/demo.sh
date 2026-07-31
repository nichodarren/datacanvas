#!/usr/bin/env sh
#
# Nyalakan prototipe: API + frontend, satu perintah.
#
# Ada karena "jalankan dua server di dua terminal, dengan urutan yang benar,
# dan jangan lupa Postgres" adalah pengetahuan lisan — dan pengetahuan lisan
# adalah hal pertama yang hilang. Skrip ini juga memeriksa prasyaratnya lebih
# dulu, sehingga kegagalan menyebut apa yang kurang alih-alih menumpahkan
# stack trace (P6).
#
# Pemakaian:  sh scripts/demo.sh
# Lalu buka:  http://localhost:3000
#
# POSIX sh, sama seperti scripts/check.sh.

set -eu
cd "$(dirname "$0")/.."

if [ -x ".venv/Scripts/python.exe" ]; then
    PY=".venv/Scripts/python.exe"
elif [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
else
    PY="python"
fi

fail() {
    printf '\033[31m%s\033[0m\n' "$1"
    [ $# -gt 1 ] && printf '  %s\n' "$2"
    exit 1
}

printf '\033[1m>> Prasyarat\033[0m\n'

# Postgres. Tanpa ini API start dan menjawab 500 di setiap rute yang menyentuh
# database — kegagalan yang terlihat seperti bug aplikasi.
if command -v pg_isready >/dev/null 2>&1; then
    PGREADY="pg_isready"
elif [ -x "/d/pgsql/bin/pg_isready" ]; then
    PGREADY="/d/pgsql/bin/pg_isready"
else
    PGREADY=""
fi
if [ -n "$PGREADY" ] && ! "$PGREADY" >/dev/null 2>&1; then
    # Log DI LUAR data directory. Menaruhnya di dalam `-D` memasang ranjau yang
    # meledak hanya setelah crash: fsync pass pra-recovery membuka setiap file
    # di data directory, termasuk log yang sedang dipegang pg_ctl → sharing
    # violation di Windows, dan cluster tidak pernah selesai recovery. Pesan ini
    # sebelumnya menyarankan justru path yang beracun itu.
    fail "Postgres tidak menjawab." "Nyalakan: D:\pgsql\bin\pg_ctl -D D:\pgdata -l D:\pgdata-server.log start"
fi
printf '   postgres OK\n'

[ -d "frontend/node_modules" ] || fail "Dependensi frontend belum terpasang." "Jalankan: cd frontend && npm ci"
printf '   frontend deps OK\n'

"$PY" -c "import app" 2>/dev/null || fail "Paket app tidak bisa di-import." "Jalankan: $PY -m pip install -e ."
printf '   backend importable OK\n'

printf '\n\033[1m>> Menyalakan\033[0m\n'
"$PY" -m app > .demo-api.log 2>&1 &
API_PID=$!
trap 'kill $API_PID 2>/dev/null || true' EXIT INT TERM

# Tunggu API benar-benar melayani, bukan sekadar prosesnya hidup.
i=0
while [ $i -lt 40 ]; do
    if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then break; fi
    sleep 1
    i=$((i + 1))
done
[ $i -lt 40 ] || fail "API tidak menjawab dalam 40 detik." "Lihat .demo-api.log"
printf '   API      http://127.0.0.1:8000\n'

printf '   frontend http://localhost:3000   <- buka ini\n\n'
cd frontend && npm run dev
