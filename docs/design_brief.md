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
