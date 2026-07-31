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

### 4.7 ⚠️ Navigasi & arsitektur informasi — **dikerjakan lebih dulu**

Ditambahkan 2026-08-01 atas permintaan pemilik produk, yang memakai produknya
dan menyimpulkan navigasinya *"masih nol dan berantakan"*.

**Ini bukan poles, dan tidak boleh dikerjakan seolah begitu.** Ia menggugat dua
keputusan tertulis, dan keluarannya adalah ADR — bukan penyesuaian CSS.

**Kenapa ia lebih dulu:** skala spasi dan hierarki tidak bisa dipilih untuk shell
yang region-nya sedang akan berubah. Kalau navigasi menambah rail atau
breadcrumb, setiap keputusan ritme bergantung padanya. Terbalik urutannya berarti
menata dua kali.

#### Yang digugat, dan celah nyata di masing-masing

**(a) §14.5 menolak galeri project** (2026-07-29):

> *"Meniru Google Flow — galeri project sebagai layar pertama... FR-A.4
> mendefinisikan Project sebagai **pengelompok** — map, bukan karya... Menirunya
> harfiah berarti mendaratkan pengguna baru di galeri berisi satu kartu yang
> harus diklik sebelum apa pun nyata terjadi."*

⚠️ **Penolakan itu mencampur dua situasi.** Ia benar untuk pengguna **baru**
dengan satu project auto-buat, dan keliru untuk pengguna **kembali** dengan
banyak. Dokumennya tidak pernah memisahkan keduanya, dan hari ini beranda selalu
membuka satu project — yang terakhir dipakai, dari `localStorage`.

**Jangan langsung ganti ke galeri.** Pertanyaan sebenarnya: *bagaimana layar
pertama melayani nol, satu, dan banyak project tanpa menghukum salah satunya?*

**(b) D-032 mencabut sidebar**, dengan syarat kembali tertulis: *"Fase 3, saat
`Library` & `Steps` ada dan tujuannya lebih dari dua."* Argumen pencabutannya
adalah **ongkos ruang** — 190px di layar 1280px untuk satu tautan duplikat dan
satu tautan rusak. Argumen itu masih berlaku terhadap **sidebar**; ia tidak
berlaku terhadap **breadcrumb**, yang biayanya satu baris.

#### Yang benar-benar hilang hari ini — periksa dulu, jangan percaya daftar ini

| Gejala | Perlu diverifikasi |
|---|---|
| Halaman versi tidak punya jalan kembali selain tautan brand | Tombol *back* browser **berfungsi** (routing Next). Yang hilang **afordansi di dalam aplikasi**, bukan kemampuannya. Nyatakan bedanya |
| Tidak ada "kamu sedang di mana" | Halaman versi kini menyebut nama dataset (D-034 era). Apakah itu sudah cukup, atau butuh jejak `Project → Dataset → Versi`? |
| Project hanya ada di dropdown header | Berpindah project butuh dua klik dan mengingat namanya |
| Beranda selalu membuka project terakhir | Ada di `page.tsx`, dengan komentar yang membelanya. Baca alasannya sebelum membaliknya |

#### Kerangka yang harus dipakai, supaya ini bukan hasil karangan

Jelajahi dulu, jangan langsung membangun:

- **Nielsen #3 — user control and freedom.** Jalan keluar yang jelas dari setiap
  keadaan. Ini heuristik yang paling langsung mengenai keluhannya.
- **Nielsen #1 — visibility of system status**, dan **#6 — recognition over
  recall**. "Project apa yang sedang kubuka" seharusnya terbaca, bukan diingat.
- **Rosenfeld & Morville**, *Information Architecture* — sistem organisasi,
  navigasi, dan pelabelan sebagai tiga hal berbeda. Keluhan "berantakan" biasanya
  soal **pelabelan dan orientasi**, bukan soal kurang tautan.
- **Breadcrumb**: murah, hampir tidak pernah merugikan, dan menjawab "di mana
  aku" tanpa mengambil lebar seperti rail.
- **Hub-and-spoke vs flat** untuk aplikasi bertujuan sedikit — dan hitung
  **berapa tujuan sebenarnya** yang dipunya aplikasi ini hari ini, karena D-032
  dicabut atas hitungan "dua".

#### Batas yang tetap berlaku

Run Log dan composer **tetap di luar** (Fase 3 dan Fase 5) — keduanya menunggu
isi, bukan menunggu navigasi. Yang dibuka di sini hanya **orientasi dan
perpindahan antar-hal yang sudah ada**.

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
> Netral, ritme spasi, bobot garis, tipografi. Menambah region atau panel demi
> *rupa* bukan pekerjaan sesi ini.
>
> **Satu pengecualian, dan hanya satu: navigasi (§4.7).** Di sana permukaan baru
> memang boleh diusulkan — tapi lewat ADR yang menggugat D-032 dan §14.5 secara
> terbuka, dengan bukti, bukan diselundupkan sebagai poles. Bedanya bukan
> formalitas: satu jalur menuntut alasan tertulis, yang lain tidak.

⚠️ **Kenapa ② perlu ditulis:** pemicu sesi ini adalah *perasaan* mentah, dan obat
paling naluriah untuk perasaan itu adalah menambah. Jalur defaultnya menuju
pembatalan dua sesi pengurangan — dan ia akan **terasa seperti kemajuan sepanjang
prosesnya**. Pengecualian navigasi tidak melonggarkan ini; ia justru menandai
satu-satunya pintu yang terbuka, sehingga sisanya tetap tertutup.

---

## 7. Urutan kerja

Berurutan, karena tiap langkah memberi makan berikutnya.

| # | Langkah | Keluaran |
|---|---|---|
| 1 | **Kumpulkan bukti mekanis lebih dulu.** Jalankan `/web-design-guidelines frontend/src` | Daftar temuan `file:line`. Perbaiki yang mekanis **sebelum** membahas selera, supaya keduanya tidak tercampur |
| 2 | **Arsitektur informasi (§4.7).** Hitung tujuan sebenarnya, jelajahi kerangkanya, rancang orientasi & perpindahan. **Jangan menulis kode dulu** | Rancangan + ADR draf yang menggugat D-032 dan §14.5 dengan bukti |
| **⏸** | **🔴 TITIK LAPOR 1 — BERHENTI.** Tulis §12 (Laporan A), lalu tunggu. Jangan lanjut ke langkah 3 sebelum pemilik produk menjawab | §12 |
| 3 | Bangun navigasi yang disetujui | Kode + test |
| 4 | **Putuskan token** — netral + biasnya, rona pengecualian, penanda "bisa diklik", skala spasi, skala tipografi | Satu blok `:root` per tanah, tiap token bernama sesuai **maknanya**, bukan rupanya |
| 5 | **Uji rencana itu** dengan pertanyaan skill `frontend-design`: *"apakah ini yang akan kuhasilkan untuk brief serupa mana pun?"* Kalau ya, ulangi | Rencana yang direvisi, dengan catatan apa yang diubah dan kenapa |
| 6 | **Perluas `test_design_tokens.py` ke dua tanah** — sebelum menulis CSS, supaya palet yang gagal AA tidak pernah sempat masuk | Test merah, lalu hijau |
| 7 | **Terapkan ke empat layar**: beranda · versi + grid · login · pengaturan akun | Angka ajaib inline diganti token |
| 8 | **Tulis ADR-nya.** Keputusan positif pertama tentang rupa yang pernah dimiliki project ini | D-036 dst. di §18, §14 diperbarui, changelog §0.6 |
| **⏹** | **🔴 TITIK LAPOR 2.** Tulis §13 (Laporan B) | §13 |

⚠️ **Titik lapor 1 adalah berhenti sungguhan, bukan formalitas.** Navigasi
menentukan bentuk shell, dan sistem visual dibangun di atas bentuk itu. Melewatinya
berarti menata dua kali kalau rancangannya ditolak — dan pemilik produk baru bisa
menilai setelah melihatnya, bukan sebelum.

---

## 8. Definisi selesai

- [ ] **§12 dan §13 ditulis dan di-commit** — tanpa ini sesi dianggap belum selesai
- [ ] **Titik lapor 1 dihormati** — navigasi tidak dibangun sebelum rancangannya disetujui
- [ ] Orientasi terjawab di setiap layar: *project apa, dataset apa, versi apa*
- [ ] Ada jalan keluar dari setiap layar tanpa mengandalkan tombol back browser
- [ ] Layar pertama masuk akal untuk nol, satu, **dan** banyak project
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
| Run Log · composer | Syarat kembali tertulis (Fase 3 / Fase 5). Keduanya menunggu **isi**, bukan menunggu navigasi — jadi §4.7 tidak menyentuhnya. ⚠️ **Sidebar dikeluarkan dari baris ini** dan kini dapat diusulkan lewat §4.7, karena argumen pencabutannya adalah ongkos ruang, dan itu argumen tentang *bentuk* navigasi — bukan tentang apakah orientasi dibutuhkan |
| FR-D.6 sort & filter | Filter adalah tugas expression language §11.3; jalur kedua sekarang berarti Fase 3 harus menyatukan atau menghapusnya |
| Kosakata "asal" (arah C) | Ide bagus yang **belum punya pemakai**. Slot "dihitung" baru nyata di Fase 3, dan §20 melarang membangun untuk pemakai yang belum ada. Tercatat di sini supaya tidak hilang |

---

## 10. WAJIB — laporkan hasilnya ke bawah dokumen ini

Sesi desain **wajib menambahkan** bagian di paling bawah file ini, di dua titik
yang ditandai di §7. Ini bukan dokumentasi; ini **serah terima yang harus bisa
diperiksa** oleh sesi lain yang tidak melihat pekerjaannya.

### Aturannya

1. **Tambahkan di bawah, jangan sunting apa pun di atas §12.** Brief adalah
   masukan; kalau ia berubah sambil dikerjakan, tidak ada lagi yang bisa
   dijadikan pembanding.
2. **Commit laporannya**, seperti perubahan lain.
3. Setelah diverifikasi, isi §12 dst. **dikosongkan** dan brief ditulis ulang
   untuk siklus berikutnya. Git menyimpan semuanya — tidak ada yang hilang.

### Yang membuat laporan bisa diperiksa

⚠️ **Laporan yang menyenangkan tidak berguna.** Kalau isinya hanya "selesai,
semua hijau", ia tidak bisa di-cross-check dan sesi ini tidak akan tahu apa yang
perlu ditindaklanjuti. Wajib memuat:

| Bagian | Isi |
|---|---|
| **Keputusan** | Nilai sebenarnya, bukan sifatnya. `--ink-faint: #8290a6`, bukan "netral yang lebih terang". Skala spasi sebagai daftar angka |
| **Apa yang dikodekan** | Untuk tiap keputusan, jawaban aturan ① — apa yang ia nyatakan tentang isinya. Yang tak bisa menjawab adalah dekorasi, dan harus dinyatakan begitu |
| **Yang TIDAK dikerjakan** | Beserta alasannya. Daftar kosong di sini hampir pasti berarti ada yang tidak dilaporkan |
| **⚠️ Di mana brief ini keliru** | **Bagian terpenting.** Kalau brief menyuruh sesuatu yang ternyata salah, keliru, atau mustahil — katakan, jangan diakali diam-diam. Termasuk kalau arah B ternyata tidak bekerja |
| **Bukti terukur** | Rasio kontras yang benar-benar diukur di **kedua** tanah. Hitungan test sebelum & sesudah. Jumlah angka ajaib yang tersisa |
| **Yang disentuh** | Commit + berkas. Cukup untuk ditelusuri tanpa menebak |
| **Terbuka / butuh keputusan** | Apa yang menunggu jawaban pemilik produk |

### Kerangka

```markdown
## 12. Laporan A — arsitektur informasi (titik lapor 1)

**Tanggal · commit terakhir · status:** …

### Tujuan yang dihitung
(berapa tujuan sebenarnya yang dipunya aplikasi ini, dan daftarnya)

### Rancangan yang diusulkan
(orientasi, perpindahan, layar pertama untuk nol/satu/banyak project)

### Terhadap D-032 dan §14.5
(apa yang digugat, bukti apa, dan apa yang TETAP berlaku)

### Alternatif yang ditolak
(minimal dua, dengan alasannya)

### ⚠️ Di mana brief ini keliru
### Terbuka / butuh keputusan
```

```markdown
## 13. Laporan B — sistem visual (titik lapor 2)

**Tanggal · commit · status:** …

### Token yang diputuskan
(nilai sebenarnya, kedua tanah)

### Apa yang dikodekan tiap keputusan
### Bukti terukur
(kontras kedua tanah, test sebelum/sesudah, sisa angka ajaib)

### Definisi selesai §8 — poin per poin
### Yang tidak dikerjakan, dan kenapa
### ⚠️ Di mana brief ini keliru
### Terbuka / butuh keputusan
```

---

## 11. Cara memulai sesi itu

```
Baca the project notes, lalu docs/design_brief.md seluruhnya.
Cek `git log --oneline -5` dan `git status`.
Laporkan singkat posisi kita, lalu mulai dari langkah 1 di §7 brief.

Dua hal yang paling mudah terlewat, jadi kusebut di sini juga:

1. §7 punya TITIK LAPOR 1 setelah rancangan navigasi. Berhenti sungguhan di
   sana — tulis §12, commit, dan tunggu jawabanku sebelum menulis kode
   navigasi apa pun.
2. §10 mewajibkan laporan ditambahkan ke BAWAH brief, bukan disunting ke
   dalamnya. Bagian "di mana brief ini keliru" bukan basa-basi — kalau brief
   menyuruh sesuatu yang salah, katakan; jangan diakali diam-diam.

Aturan main tetap berlaku: baca bagian DESIGN.md yang relevan sebelum menulis
kode; kalau ada yang keliru di sana, katakan sekarang. Untuk pekerjaan besar,
tunjukkan rancangannya dulu. Setiap invariant yang disentuh harus punya test.
Kalau permintaanku melewati batas scope, tolak dan sebutkan bagian dokumennya.
```

---

## 12. Laporan A — arsitektur informasi (titik lapor 1)

**Tanggal:** 2026-08-01 · **Commit terakhir:** `4839d50` · **Status:** 🔴 menunggu
keputusan pemilik produk. Nol baris kode navigasi ditulis.

Langkah 1 (§7) sudah selesai dan ter-commit terpisah. Bagian ini hanya langkah 2:
**rancangan**, bukan implementasi.

### 12.0 Yang sudah dikerjakan di langkah 1

`/web-design-guidelines frontend/src` dijalankan lewat skill ter-vendor. Temuan
mekanis diperbaiki di `4839d50`; yang bergantung pada palet atau pada bentuk
shell **sengaja ditunda** ke langkah 4/7 dan disebut namanya di commit.

| Terukur | Sebelum | Sesudah |
|---|---|---|
| Test frontend | 20 | **34** |
| Test backend | 484 lulus · 2 skip | tak berubah |
| Prop `style={{…}}` inline | 47 | 41 |
| Angka numerik literal di dalamnya | 43 | **43** (ditunda ke langkah 7) |

**Dua temuan yang bukan checklist**, keduanya sudah divonis oleh komentar di repo
ini sendiri sebelum skill mana pun membacanya:

1. **`ProjectPicker` adalah popup keempat.** Ia memakai `role="menu"` +
   `role="menuitem"` tanpa satu pun perilaku yang dijanjikan peran itu, dan tidak
   bisa ditutup dari papan ketik sama sekali. `AccountMenu.tsx:13-35` menulis tiga
   paragraf tentang kenapa itu lebih buruk daripada diam; `useDisclosure` dibangun
   supaya popup baru mendapat kontraknya *by construction*. Keduanya ditulis
   2026-07-31, keduanya menghitung **tiga** popup. Yang keempat hidup di header,
   bukan di grid.
2. **`End session` melanggar UX-7.** Sesi 2026-07-31 memperbaiki *sign out
   everywhere* dan menuliskan pelanggarannya; tombol per-baris tiga puluh baris di
   atasnya tetap mencabut sesi jarak jauh dalam satu klik. Komentar yang mencatat
   aturannya berada **tepat di bawah** tombol yang melanggarnya.

### 12.1 Tujuan yang dihitung

Rute yang benar-benar ada hari ini — dihitung dari `frontend/src/app/`, bukan dari
ingatan:

| Rute | Jenis | Terjangkau dari |
|---|---|---|
| `/` | **tujuan kerja** — daftar dataset satu project | brand, di setiap layar |
| `/versions/[versionId]` | **tujuan kerja** — grid satu versi | kartu dataset di `/` |
| `/settings/account` | tujuan akun | menu akun, di setiap layar |
| `/login` | tak terautentikasi | redirect |
| *404* | kesalahan | URL salah — **tidak ada `not-found.tsx`** |

**Tujuan kerja: dua.** Itu angka yang sama yang dipakai D-032 untuk mencabut
sidebar, dan **angka itu masih benar.** `/settings/account` adalah permukaan akun
yang menurut konvensi memang tidak masuk navigasi utama, dan ia sudah terjangkau
dari mana saja.

> ⚠️ **Karena itu aku menolak mengusulkan sidebar kembali**, meski §6 brief
> membuka pintunya. Aritmetika D-032 tidak berubah, dan syarat kembalinya
> (`Library` & `Steps`, Fase 3) belum terpenuhi. Mengusulkannya sekarang berarti
> membatalkan sesi pengurangan dengan alasan yang tidak dipunya.

### 12.2 Yang benar-benar rusak — diverifikasi, bukan disalin dari §4.7

**(a) Konteks project hilang di halaman versi, dan bisa berubah diam-diam.**
`ProjectPicker` hanya dirender di `/` (`page.tsx:155-162`). Di
`/versions/[id]`, `Shell` dipanggil tanpa `headerExtras` — jadi tak ada apa pun di
layar yang menyebut project. Lebih jauh: tautan brand menuju `/`, dan `/` membuka
project dari `localStorage` (`page.tsx:84-86`), yang **tidak harus** project
pemilik dataset yang baru saja dilihat.

> Buka versi milik project A dari bookmark saat `localStorage` berisi project B,
> lalu tekan brand: aplikasi mendarat di project B tanpa satu pun tanda bahwa
> konteksnya berpindah. Ini **kesalahan orientasi, bukan sekadar afordansi yang
> hilang** — dan §4.7 tidak menyebutnya.

**(b) Halaman versi tidak bisa menyebut project-nya walau kita mau.**
`DatasetVersionResponse` (`backend/app/api/schemas.py:130-152`) membawa
`dataset_id` dan `dataset_name`, **tidak** membawa project. Jadi (a) tidak bisa
diperbaiki di frontend saja. Ini menjawab pertanyaan §4.7 — *"apakah nama dataset
sudah cukup?"* — dengan **tidak**, dan alasannya bisa diperiksa.

**(c) 404 adalah bawaan Next.** Tidak ada `app/not-found.tsx`. Layar itu berlatar
terang, tanpa shell, tanpa satu pun tautan keluar. §14.5 mewajibkan *"selalu
sediakan jalan maju"* sejak 2026-07-31; aturan itu **belum pernah diuji terhadap
404.** Kelas cacat yang sama persis dengan layar 500 yang melahirkan aturannya.
§4.7 juga tidak menyebutnya.

**(d) Yang §4.7 sebut, dan ternyata benar:** tombol *back* browser memang bekerja;
yang hilang afordansi di dalam aplikasi (Nielsen #3 meminta jalan keluar yang
**terlihat**, bukan yang tersedia).

### 12.3 Rancangan yang diusulkan

> **Jejak itu masuk ke baris header yang sudah ada, bukan ke baris baru.**

`Shell` sudah punya slot `headerExtras` di antara brand dan spacer — slot yang
hari ini hanya dipakai `/`. Jejaknya masuk ke situ, di setiap layar.

```
/                    DataCanvas   Sales ▾                       someone@… ▾
/versions/{id}       DataCanvas   Sales ▾  ›  penjualan_q3      someone@… ▾
/settings/account    DataCanvas   Account                       someone@… ▾
```

| Elemen | Bentuk | Apa yang ia kodekan (aturan ①) |
|---|---|---|
| `Sales` | **tautan** ke `/` bila kita tidak di sana; teks biasa bila kita di sana | *project ini memuat apa yang sedang kamu lihat* |
| `▾` | pemicu picker, selalu di samping nama | *ada project lain, dan ini caranya pindah* |
| `›` | pemisah, `aria-hidden` | *yang kanan berada di dalam yang kiri* |
| `penjualan_q3` | teks biasa, bukan tautan | *di sinilah kamu* |
| `Account` | teks biasa, tanpa project | *ini bukan layar milik project mana pun* |

**Kenapa nama dan caret dipisah, bukan satu tombol.** Kalau seluruh chip adalah
picker, jalan keluar utama dari halaman versi berharga **dua klik** (buka, pilih
yang sedang aktif). Jalan keluar tidak boleh lebih mahal daripada perpindahan yang
jarang. Dipisah: keluar satu klik, ganti project dua. Ongkosnya satu tab stop di
header — bukan di daftar 60 kolom, jadi aritmetika yang mencabut tombol urut dan
gagang resize tidak berlaku di sini.

**Segmen ketiga sengaja belum ada.** Jejak penuhnya `Project › Dataset › Versi`,
tapi hari ini satu Dataset selalu punya tepat satu versi terjangkau — tidak ada
rute mendaftar versi — sehingga *Dataset* dan *Versi* adalah satu hal. Segmen
ketiga datang bersama **FR-B.2 + P4**, yang sudah dijadwalkan sebagai satu
pekerjaan tersendiri. Menambahkannya sekarang berarti merender hierarki yang belum
bisa dijelajahi.

**Yang ikut diperbaiki karena ia soal orientasi, bukan poles:**

| | |
|---|---|
| `app/not-found.tsx` | Memakai `Shell`, kalimat manusia, satu jalan maju. §14.5 sudah mewajibkannya sejak 2026-07-31 |
| Skip link | Ditunda dari langkah 1 ke sini karena ia afordansi navigasi. Satu anchor, terlihat hanya saat difokus |

**Perubahan backend yang dituntut rancangan ini — satu, dan tanpa migrasi:**

```
DatasetVersionResponse += project_id: uuid.UUID
                       += project_name: str
```

Dataset→Project sudah FK; ini menampilkan identitas objek yang sudah ada, bukan
fitur baru. **Presedennya kuat dan baru berumur sehari:** `dataset_name`
ditambahkan ke respons yang sama, atas alasan yang sama — *halamannya tidak
menyebut miliknya siapa*.

### 12.4 Layar pertama untuk nol · satu · banyak project

| Keadaan | Rancangan | Alasan |
|---|---|---|
| **Nol** | — | **Keadaan ini tidak bisa terjadi.** Lihat §12.6 |
| **Satu** | Persis seperti hari ini | Picker tetap dirender: menyembunyikannya membuat *"aku di project mana"* tak terjawab, dan ia tetap punya isi (`+ New project`) — jadi ia bukan kontrol yang tidak melakukan apa pun |
| **Banyak** | Persis seperti hari ini, **plus** namanya kini terbaca di halaman versi | Pindah project = 2 klik dengan nilai sekarang terlihat. Itu *recognition*, bukan *recall* (Nielsen #6) |

**Galeri project ditolak, dan alasan §14.5 dikoreksi.** §14.5 menolaknya karena
mendaratkan pengguna **baru** di galeri berisi satu kartu. Brief benar bahwa
alasan itu tidak menyentuh pengguna **kembali** yang punya banyak. Alasan yang
benar untuk keduanya adalah ongkos klik: galeri menambah **satu klik wajib** ke
kasus yang paling sering (buka aplikasi, lanjutkan di tempat terakhir) demi
mempercepat kasus yang jarang (ganti project) yang hari ini sudah dua klik. Itu
rugi bersih, dan ia berlaku untuk pengguna baru **dan** lama.

⚠️ **Batas kejujuran klaim ini:** ia berlaku selama seseorang punya segelintir
project. Tidak ada satu pun bukti tentang apa yang terjadi pada 30 project —
picker menjadi daftar gulir tanpa pencarian. **Titik peninjauan: Gerbang 4.**

### 12.5 Terhadap D-032 dan §14.5

| Keputusan | Digugat? | Hasil |
|---|---|---|
| **D-032 — sidebar dicabut** | ❌ Tidak | Argumennya **ongkos lebar** (190px di layar 1280px). Jejak ini memakai **nol lebar tambahan** — ia mengisi slot `headerExtras` yang sudah ada — dan nol tinggi tambahan. D-032 tidak tersentuh, syarat kembalinya tidak berubah |
| **D-032 — Run Log & composer** | ❌ Tidak | Keduanya menunggu **isi**. Di luar §4.7, sesuai §9 brief |
| **§14.5 — galeri project ditolak** | ⚠️ Sebagian | Keputusannya **dipertahankan**; **alasannya diperbaiki** dan diperluas ke pengguna kembali. Ini perubahan alasan, bukan perubahan keputusan → §0.3 aturan 2 |
| **§14.5 — jalan maju di setiap kegagalan** | ❌ Tidak | Ditegakkan ke tempat yang belum pernah diuji terhadapnya (404) |
| **§14.2 — versi di header (P4)** | ❌ Tidak | Segmen ketiga sengaja tidak dibuat. P4 tetap ditunda ke Fase 3 |

**Jadi ADR-nya kecil, dan itu hasil yang benar.** Draf **D-036** hanya memutuskan
tiga hal: jejak masuk ke header, `project_name` masuk ke respons versi, dan 404
mendapat halamannya. Tidak ada region baru, tidak ada permukaan baru, tidak ada
keputusan yang dibatalkan.

### 12.6 ⚠️ Di mana brief ini keliru

**1. "Nol project" adalah keadaan yang tidak bisa dicapai.** §8 mensyaratkan
*"Layar pertama masuk akal untuk nol, satu, dan banyak project"*. Diperiksa: §15.2
membuat project otomatis saat registrasi, `RegisterResponse` memang membawanya,
dan **tidak ada rute menghapus project**. Jadi nol tidak pernah terjadi. Kodenya
toh menanganinya (`found[0] ?? null` → picker menampilkan *"No project"* dan tetap
menawarkan `+ New project`). **Merancang untuk keadaan ini akan menjadi pekerjaan
tanpa pemakai — persis yang §20 larang.**

**2. Tabel "gejala" di §4.7 melewatkan dua hal terburuknya.** Ia mencatat
afordansi yang hilang, dan tidak mencatat (a) bahwa brand bisa memindahkan
pengguna ke project yang **berbeda** tanpa suara, maupun (b) bahwa 404 masih
bawaan Next dan melanggar §14.5. Keduanya lebih berat daripada tiga dari empat
baris yang ada di tabel itu. Brief benar menyuruh *"periksa dulu, jangan percaya
daftar ini"* — dan daftar itu memang perlu diperiksa.

**3. §6 membuka pintu sidebar; buktinya menutupnya kembali.** Bukan kekeliruan,
tapi perlu dinyatakan supaya tidak terbaca sebagai pekerjaan yang dilewatkan:
pintu itu **sengaja tidak dipakai**.

**4. §7 langkah 1 tidak sepenuhnya bisa dijalankan seperti tertulis.** Ia menyuruh
*"perbaiki yang mekanis sebelum membahas selera"*, tapi sebagian temuan mekanis
**nilainya adalah selera**: `theme-color` butuh palet, `📌` butuh keputusan
ikonografi, skip link adalah navigasi. Ketiganya ditunda dengan alasan tertulis,
bukan dikerjakan dua kali. Urutan §7 tetap benar; hanya kalimatnya yang terlalu
rapi.

**5. Penomoran §4 membingungkan saat dirujuk** — §4.7 disisipkan di atas §4.6.
Sepele, dan hanya masalah kalau ada yang menyebut "bagian terakhir §4".

### 12.7 Alternatif yang ditolak

| Alternatif | Kenapa ditolak |
|---|---|
| **Galeri project sebagai layar pertama** | Satu klik wajib ditambahkan ke kasus tersering demi mempercepat yang jarang. §12.4 |
| **Sidebar kiri kembali** | Tujuan kerja masih dua. Aritmetika D-032 utuh. §12.1 |
| **Baris kedua khusus breadcrumb** | ± 32px tinggi di setiap layar untuk informasi yang muat di slot header yang sudah kosong — dan sebuah **region baru**, yang ditutup aturan ② |
| **Brand jadi tombol *back*** | Kontrol yang kadang pulang dan kadang mundur tidak bisa diprediksi, dan menyembunyikan tujuannya. Nielsen #3 meminta jalan keluar yang jelas, bukan yang pintar |
| **Satu chip picker merangkap jalan keluar** | Jalan keluar jadi dua klik. §12.3 |

### 12.8 Yang TIDAK dikerjakan di langkah 2, dan kenapa

| | |
|---|---|
| Semua kode navigasi | **Titik lapor 1.** Itu inti bagian ini |
| Segmen versi di jejak | Menunggu FR-B.2 + P4, satu pekerjaan tersendiri (§9 brief) |
| Pencarian di picker project | Tidak ada bukti ia dibutuhkan. Gerbang 4 |
| Duplikasi `h1` project vs jejak di `/` | Nyata tapi ringan; ia soal ritme badan halaman → langkah 7 |
| `beforeunload` saat unggah | Masih menunggu jawabanmu dari langkah 1 |

### 12.9 Terbuka / butuh keputusan

| # | Pertanyaan | Rekomendasiku |
|---|---|---|
| 1 | Setujui **`project_id` + `project_name`** di `DatasetVersionResponse`? Backend, nol migrasi | **Ya.** Tanpanya §12.2(a) tidak bisa diperbaiki sama sekali |
| 2 | Nama + caret **dipisah** (keluar 1 klik) atau satu chip picker (keluar 2 klik)? | **Dipisah** |
| 3 | `app/not-found.tsx` masuk sesi ini? | **Ya** — ia penegakan §14.5 yang sudah ada, bukan permukaan baru |
| 4 | `beforeunload` saat unggah 28 detik? *(dari langkah 1)* | Netral. Ia menambah perilaku, jadi ini panggilanmu |

Jawab keempatnya — atau cukup **"lanjut"** untuk menerima seluruh rekomendasi —
dan aku bangun navigasinya (langkah 3), lalu masuk ke token (langkah 4).
