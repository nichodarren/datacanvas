# Design Brief — sistem visual DataCanvas

| | |
|---|---|
| **Status** | 🟢 Siap dikerjakan |
| **Ditulis** | 2026-08-01 |
| **Untuk** | Sesi desain UI/UX, dikerjakan di sesi terpisah |
| **Referensi visual** | Artefak perbandingan tiga arah (privat, dibuat 2026-08-01) |

Dokumen ini adalah **masukan** untuk satu sesi kerja, bukan sumber kebenaran.
`docs/DESIGN.md` tetap SSOT dan mengalahkan setiap baris di sini. Keluaran sesi
itu berupa ADR di §18 dan perubahan di §14 — bukan pembaruan file ini.

---

## 1. Kenapa sesi ini ada

Pemilik produk memakai produknya sendiri dan menyimpulkan: **"kurang punya
karakter dan minim dipertimbangkan."**

Diperiksa terhadap §18, itu **harfiah benar**. Setiap keputusan desain yang
pernah project ini catat adalah **pengurangan**:

> D-032 (shell) · FR-C.6 · urutkan kolom · badge versi · null% · sidebar ·
> Run Log · composer · pil privasi

**Tidak ada satu pun keputusan positif tentang rupa.** `system-ui` adalah
typeface yang dipilih dengan cara tidak memilih. Paletnya slate kebiruan yang
bisa jadi milik alat developer mana pun. Ketelitian project ini seluruhnya
tercurah ke **kebenaran** dan ke **apa yang dibuang**; sistem visualnya adalah
sisa, ditambah default.

Sesi ini menutup celah itu. Ia **bukan** sesi menambah fitur.

---

## 2. Yang sudah diputuskan — jangan dibuka ulang

| Keputusan | Diputuskan |
|---|---|
| **Kepadatan: alat kerja** — sebanyak mungkin baris terlihat sekaligus; analis menatap ini berjam-jam dan menggulir itu mahal (NFR-UX.5) | 2026-08-01 |
| **Dwi-tema terang & gelap**, dapat diganti pengguna. Tanah **bukan** keputusan desain — ia milik orang yang menatapnya | 2026-08-01 |
| **Arah: B · Bobot** — lihat §3 | 2026-08-01 |

---

## 3. Arah terpilih — B · Bobot

> **Tidak ada warna aksen sama sekali. Hierarki dibangun bobot dan ketebalan
> garis. Satu-satunya rona di seluruh antarmuka adalah pengecualian.**

Konsekuensinya keras, dan itulah intinya: **kalau ada yang berwarna, ia
benar-benar butuh perhatian.**

### Kenapa ini arah yang benar untuk produk ini

1. **Ia ekspresi visual dari prinsip yang sudah tertulis.** P9 (permukaan kecil),
   P6 (kegagalan jujur di atas tebakan meyakinkan), dan D-032 semuanya sudah
   berkata hal yang sama tentang perilaku. B mengatakannya tentang rupa.
2. **Anggaran warnanya belum terpakai, dan Fase 3 akan membutuhkannya.** Saat
   `stale`, `cached`, dan nilai terkomputasi datang, masing-masing butuh makna
   visual (UX-4, UX-5). Arah yang membelanjakan warnanya untuk dekorasi tidak
   punya sisa. **Ini alasan terkuatnya.**
3. **Paling murah dijaga benar.** Satu rona semantik yang harus lulus AA di dua
   tanah, bukan lima.

### ⚠️ Risiko utamanya, dinyatakan di muka

**Karakter yang lahir dari kekekangan sulit dibedakan dari ketiadaan.** B yang
dikerjakan malas menjadi persis keluhan yang memulai sesi ini — alat generik,
hanya lebih kelabu.

Karena itu §4 ada: kalau warna tidak boleh membawa karakter, sesuatu yang lain
**harus**, dan itu wajib diputuskan secara eksplisit.

---

## 4. Yang masih terbuka — ini pekerjaan sesi desain

### 4.1 Netral tidak boleh abu-abu murni

Abu-abu netral sempurna terbaca **tidak dipilih** — persis masalah yang sedang
diperbaiki. Netral wajib punya bias rona yang disengaja.

**Diputuskan:** ke arah mana, dan seberapa jauh. Hangat (kecokelatan/kertas),
dingin (kebiruan/baja), atau hijau-kelabu. Ingat bahwa slate kebiruan adalah
seragam hampir setiap alat teknis — memilihnya berarti menerima terbaca sebagai
salah satu dari banyak.

### 4.2 Rona pengecualian: berapa banyak, dan untuk apa

**Koreksi yang sudah dipastikan:** `null` **bukan** pengecualian. Kolom `Cabin`
di `titanic` 77% null; mewarnainya membuat grid berteriak tentang data yang
sepenuhnya normal. Kode hari ini sudah benar — null berwarna faint netral, dan
komentarnya menyebut alasannya: *"An empty cell and a null cell are different
facts."* **Pertahankan.**

**Diputuskan:** apakah pengecualian butuh satu rona atau lebih. Kandidat yang
benar-benar menuntut tindakan hari ini:

| Keadaan | Sudah ada? |
|---|---|
| Kolom di kontrak tapi tidak ada di halaman baris (`unavailable`) | ✅ `.missing` |
| Peringatan dialect saat unggah | ✅ `.banner` |
| Kegagalan — unggah, muat, koreksi tipe | ✅ `.banner.error` |
| `stale`, `cached` (UX-4, UX-5) | ❌ Fase 3 |

Disiplin B menyarankan sesedikit mungkin. Tapi *peringatan* dan *kegagalan*
menuntut respons berbeda, dan NFR-UX.3 melarang warna menjadi satu-satunya
pembeda — jadi apa pun jawabannya, **setiap keadaan wajib punya kata, bukan cuma
rona**.

### 4.3 Apa yang menandai "bisa diklik" tanpa warna aksen

Ini lubang terbesar di B. Hari ini `--accent` menandai tautan, tipe kolom yang
dapat diubah, dan tombol primer. Tanpa rona aksen, sesuatu harus menggantikannya
— bobot, garis bawah, pembalikan, atau kotak. **Wajib diputuskan sebelum kode
disentuh**, karena ia menyentuh setiap layar.

### 4.4 Skala spasi dan tipografi

Belum pernah ada. Yang ada angka ajaib inline: `marginTop: 18`, `gap: 4`,
`fontSize: 12`, tersebar di JSX. **Diputuskan:** skalanya, lalu token
menggantikan setiap angka itu.

### 4.5 Typeface

Belum dipilih, dan **sengaja tidak diprototipekan** — CSP artefak memblokir CDN
font. Keputusan nyata dengan ongkos nyata: self-hosting menambah byte ke setiap
muat halaman. Pertanyaannya: apakah `system-ui` tetap cukup kalau segala hal lain
sudah dipilih dengan sadar?

### 4.6 Q-4 dan Q-5 (§14.4) ditagih di sini

| | |
|---|---|
| **Q-4** | `📌` dipakai sebagai ikon di tombol pin. Emoji berubah bentuk antar platform dan dibacakan screen reader sebagai nama Unicode-nya. **Butuh pengganti**, dan itu keputusan visual — apakah produk ini punya ikonografi sama sekali? |
| **Q-5** | Tombol ± 30px terhadap ambang sentuh 44×44px. NFR-UX.4 menjanjikan *"tidak rusak di tablet"* dan itu **belum pernah diukur di tablet**. Bertegangan langsung dengan kepadatan — sebutkan pertukarannya, jangan diamkan |

---

## 5. Batas yang tidak boleh dilanggar

1. **`docs/DESIGN.md` mengalahkan brief ini dan setiap skill.** Temuan skill
   adalah masukan, bukan vonis (D-035).
2. **NFR-UX.3 wajib lulus di kedua tanah.** `tests/test_design_tokens.py` hari
   ini hanya menguji satu — **memperluasnya ke dua adalah bagian dari pekerjaan
   ini, bukan tindak lanjut.**
3. **NFR-UX.4** — bekerja penuh di ≥ 1280px, tidak rusak di tablet.
4. **W-1…W-6 dan Q-1…Q-5 (§14.4)** berlaku.
5. **Setiap invariant yang disentuh harus punya test.**
6. **Menambah permukaan butuh ADR yang menggugat D-032 dengan bukti** — bukan
   diselundupkan sebagai "poles". Lihat §6.

---

## 6. Aturan keputusan sesi ini

Dua sesi sebelumnya berhasil karena punya aturan tertulis. Sesi ini punya dua.

> **① Setiap pilihan visual harus bisa menyebut apa yang ia kodekan.**
> Kalau sebuah warna, bobot, atau garis tidak menyatakan sesuatu yang benar
> tentang isinya, ia dekorasi — dan dekorasi persis yang membuat "generik"
> terasa generik. Aturan ini diturunkan dari B sendiri, dan bisa diuji saat
> review.

> **② Karakter datang dari sistem, bukan dari permukaan baru.**
> Netral, ritme spasi, bobot garis, tipografi. Menambah region, panel, atau
> tujuan navigasi **bukan** pekerjaan sesi ini — kalau bukti menuntutnya, itu
> ADR tersendiri yang menggugat D-032 secara terbuka.

⚠️ **Kenapa ② perlu ditulis:** pemicu sesi ini adalah *perasaan* mentah, dan obat
paling naluriah untuk perasaan itu adalah menambah. Jalur defaultnya menuju
pembatalan dua sesi pengurangan — dan ia akan **terasa seperti kemajuan sepanjang
prosesnya**.

---

## 7. Urutan kerja

Berurutan, karena tiap langkah memberi makan berikutnya.

| # | Langkah | Keluaran |
|---|---|---|
| 1 | **Kumpulkan bukti mekanis lebih dulu.** Jalankan `/web-design-guidelines frontend/src` | Daftar temuan `file:line`. Perbaiki yang mekanis **sebelum** membahas selera, supaya keduanya tidak tercampur |
| 2 | **Putuskan token** — netral + biasnya, rona pengecualian, skala spasi, skala tipografi | Satu blok `:root` per tanah, tiap token bernama sesuai **maknanya**, bukan rupanya |
| 3 | **Uji rencana itu** dengan pertanyaan skill `frontend-design`: *"apakah ini yang akan kuhasilkan untuk brief serupa mana pun?"* Kalau ya, ulangi | Rencana yang direvisi, dengan catatan apa yang diubah dan kenapa |
| 4 | **Perluas `test_design_tokens.py` ke dua tanah** — sebelum menulis CSS, supaya palet yang gagal AA tidak pernah sempat masuk | Test merah, lalu hijau |
| 5 | **Terapkan ke empat layar**: beranda · versi + grid · login · pengaturan akun | Angka ajaib inline diganti token |
| 6 | **Tulis ADR-nya.** Keputusan positif pertama tentang rupa yang pernah dimiliki project ini | D-036 dst. di §18, §14 diperbarui, changelog §0.6 |

---

## 8. Definisi selesai

- [ ] Nol angka ajaib spasi/ukuran tersisa di JSX
- [ ] `test_design_tokens.py` menguji **kedua** tanah; semua token lulus AA
- [ ] Toggle tema bekerja, dan pilihannya bertahan antar-kunjungan
- [ ] Empat layar memakai sistem yang sama
- [ ] Q-4 selesai — tidak ada emoji sebagai ikon
- [ ] Q-5 diukur, dan pertukarannya terhadap kepadatan dinyatakan tertulis
- [ ] ADR ditulis: apa yang dipilih, apa yang ditolak, apa ongkosnya
- [ ] `sh scripts/check.sh` hijau
- [ ] Setiap keputusan bisa menjawab aturan ① — sebutkan apa yang ia kodekan

---

## 9. Yang sengaja **tidak** ada di sesi ini

| | Kenapa |
|---|---|
| Tab Profile (FR-D.5) | INV-5 — kartunya penuh angka yang butuh `computation_id`. Fase 3, di atas executor |
| FR-B.2 + identitas versi (P4) | Satu pekerjaan tersendiri, empat bagian, dijadwalkan sesi terpisah |
| Run Log · sidebar · composer | Masing-masing punya syarat kembali tertulis (Fase 3 / Fase 5) |
| FR-D.6 sort & filter | Filter adalah tugas expression language §11.3; jalur kedua sekarang berarti Fase 3 harus menyatukan atau menghapusnya |
| Kosakata "asal" (arah C) | Ide bagus yang **belum punya pemakai**. Slot "dihitung" baru nyata di Fase 3, dan §20 melarang membangun untuk pemakai yang belum ada. Tercatat di sini supaya tidak hilang |

---

## 10. Cara memulai sesi itu

```
Baca the project notes, lalu docs/design_brief.md.
Cek `git log --oneline -5` dan `git status`.
Laporkan singkat posisi kita, lalu mulai dari langkah 1 di §7 brief.

Aturan main tetap berlaku: baca bagian DESIGN.md yang relevan sebelum menulis
kode; kalau ada yang keliru di sana, katakan sekarang. Untuk pekerjaan besar,
tunjukkan rancangannya dulu. Setiap invariant yang disentuh harus punya test.
Kalau permintaanku melewati batas scope, tolak dan sebutkan bagian dokumennya.
```
