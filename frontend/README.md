# Frontend — belum diinisialisasi

Sengaja kosong sampai **Fase 2** (§20 DESIGN.md), ketika Preview Grid menjadi
deliverable pertama yang benar-benar butuh UI.

Alasannya bukan kemalasan: menginisialisasi Next.js sekarang berarti mengunci
versi framework berbulan-bulan sebelum dipakai, lalu menghabiskan waktu
memigrasikannya sebelum satu komponen pun ditulis. Toolchain frontend bergerak
cepat — inisialisasi saat dibutuhkan, bukan saat direncanakan.

## Saat Fase 2 dimulai

Keputusan yang sudah diambil dan tidak perlu didiskusikan ulang (§10.3):

| | Pilihan | Alasan |
|---|---|---|
| Framework | Next.js + React + TypeScript | Sudah dikuasai, ekosistem matang (P8) |
| Grid | TanStack Table + virtualizer | Headless, ringan, kontrol penuh atas header (FR-D.4) |
| Chart | Vega-Lite | Spec deklaratif = data, bukan kode → bisa di-fingerprint (D-016) |
| Type check | TypeScript strict | NFR-MAINT.4 |

**Sebelum menulis kode:** baca §14 (UX design) dan invariant UX-1…UX-7. Tata letak
utamanya sudah dirancang di §14.2 — copilot adalah bar bawah, bukan panel samping,
dan Run Log selalu terlihat. Keduanya keputusan sadar, bukan preferensi.
