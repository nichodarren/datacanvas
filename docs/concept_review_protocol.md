# Protokol Concept Review

| | |
|---|---|
| **Versi** | 0.2.0 |
| **Status** | ✅ **Sesi 1 selesai** (2026-07-28) · ⏭️ **Sesi 2–3 dilewati secara sadar** — lihat DESIGN.md §20 Fase 0 |
| **Peserta** | 3 senior data scientist (§20 Fase 0 — pembagian panel) |
| **Durasi** | 45–60 menit **per orang**, sesi terpisah |
| **Menjawab** | **R-1** (katalog terlalu sempit) dan **OQ-13** (moat) |

> **Dokumen ini masih berlaku.** Meski concept review Fase 0 berhenti di sesi 1, protokolnya dipakai ulang untuk:
> - **Sesi data engineer di Fase 2** — apakah model ingest + Schema Contract bertahan menghadapi cara data benar-benar datang
> - **Uji pengguna Gerbang 4** — dengan penyesuaian: Bagian 1 (elicitation buta) diganti observasi tugas, dan aturan §2 tetap berlaku seluruhnya
>
> **Pelajaran dari sesi 1 yang wajib diterapkan lain kali:** P2 gagal menghasilkan daftar pertanyaan mentah karena responden melompat ke merancang solusi. Versi tajamnya:
>
> *"Saya butuh kalimat pertanyaannya, bukan pendapat. Bayangkan kamu lagi ngobrol sama datanya — kalimat apa yang keluar? Sebanyak-banyaknya, nggak usah rapi."*
>
> Kalau tetap melompat: *"nanti kita bahas itu — sekarang saya masih butuh 10 pertanyaan lagi."*

---

## 1. Yang harus dihasilkan sesi ini

Bukan "masukan" atau "validasi". Tiga keluaran konkret:

| # | Keluaran | Dipakai untuk |
|---|---|---|
| **O-1** | **Daftar pertanyaan analisis nyata**, dicatat kata per kata (target ≥ 25 per orang) | Estimasi M-1 pra-kode; calon golden query; calon tool |
| **O-2** | **Peta keberatan** — kenapa mereka tidak/berhenti memakai tool AI-data yang sudah ada | OQ-13, dan menguji apakah proposisi nilai inti beresonansi |
| **O-3** | **Kandidat vertikal** — analisis yang berulang di industri mereka tapi tidak dilayani tool generik | OQ-13 opsi (c) |

O-1 adalah yang terpenting. Kalau waktu habis, korbankan O-3.

---

## 2. Aturan main — ini yang menentukan datanya berguna atau tidak

**A-1. Cari keberatan, bukan persetujuan.**
Kalau kamu bertanya *"menarik nggak?"*, jawabannya "menarik", dan kamu tidak belajar apa pun. Setiap pertanyaan harus dirancang agar jawaban jujurnya berupa masalah.

**A-2. Sesi terpisah, satu orang satu sesi.**
Tiga atasan dalam satu ruangan menghasilkan satu suara dominan, dua yang mengangguk, dan nol informasi. Selain itu kamu kehilangan tiga sampel independen.

**A-3. JANGAN tunjukkan katalog tool di awal.**
Ini kesalahan paling merusak yang bisa kamu lakukan. Kalau kamu tunjukkan 21 tool lalu bertanya *"apa lagi yang kamu butuhkan?"*, mereka akan menjawab **di dalam kerangka yang kamu berikan**, dan angka M-1-mu akan palsu-tinggi. Elicitation harus buta.

**A-4. Jangan jelaskan arsitekturnya.**
Senior DS akan dengan senang hati membahas Merkle DAG, fingerprint, dan tool registry selama satu jam. Itu percakapan yang menyenangkan dan **tidak menjawab R-1 maupun OQ-13**. Simpan untuk lain kali.

**A-5. Jangan membela produk.**
Saat mereka bilang "ini nggak bisa X", jawabannya bukan penjelasan kenapa X ditunda. Jawabannya: *"menarik — ceritakan kapan terakhir kamu butuh X."* Setiap kalimat pembelaan menutup satu pintu informasi.

**A-6. Catat kata per kata.**
Parafrasemu sendiri sudah tercemar oleh apa yang kamu harapkan. Rekam kalau diizinkan; kalau tidak, tulis mentah dan rapikan setelah sesi.

**A-7. Diam itu alat.**
Setelah mereka menjawab, tunggu 3 detik sebelum bicara. Informasi paling berharga biasanya muncul di kalimat kedua.

---

## 3. Persiapan

**Yang dibawa:**
- Alat catat (dan izin merekam)
- Lembar skor §6 — dicetak atau di layar terpisah
- Katalog 21 tool (§11.4 DESIGN.md) — **disembunyikan sampai Bagian 2**
- Mockup tata letak §14.2 — **juga disembunyikan sampai Bagian 2**

**Yang TIDAK dibawa:** DESIGN.md, diagram arsitektur, slide.

**Cara mengundang** (kalimat ini penting — ia menentukan kerangka seluruh sesi):

> *"Saya lagi bangun tool analisis data dan butuh 45 menit untuk memastikan saya nggak salah arah. Yang paling saya butuhkan bukan pendapat soal idenya, tapi cerita soal kerjaan kamu sehari-hari. Boleh?"*

Jangan bilang "minta feedback" — itu mengundang penilaian sopan.

---

## 4. Struktur sesi

### Bagian 0 · Framing — 3 menit

Baca kurang lebih apa adanya:

> *"Saya lagi di tahap sebelum nulis kode, jadi ini waktu paling murah untuk salah. Saya nggak akan jelasin produknya dulu — saya mau denger cara kamu kerja dulu, baru nanti saya tunjukkan dan kamu bantai. Kalau di tengah jalan kamu mikir 'ini nggak bakal kepake', tolong langsung bilang. Itu justru informasi yang paling saya butuhkan."*

Kalimat terakhir memberi izin eksplisit untuk mengkritik — penting ketika lawan bicaranya atasan.

### Bagian 1 · Elicitation buta — 20 menit ⭐ paling penting

**Belum tunjukkan apa pun.**

**P1.** *"Kalau kamu dapat file data baru hari ini — dari tim lain, belum pernah kamu lihat — 30 menit pertama kamu ngapain aja? Ceritakan urut."*

> Probe: *"terus?"* · *"itu kamu ngeceknya gimana?"* · *"pernah nemu masalah apa di tahap itu?"*

**P2.** *"Coba sebutkan pertanyaan-pertanyaan yang paling sering kamu ajukan ke data. Sebanyak-banyaknya, nggak usah rapi."*

> Target ≥ 15 dari pertanyaan ini saja. Kalau macet, pancing per konteks: *"kalau lagi ngecek kualitas data?"* · *"kalau lagi cari penyebab angka aneh?"* · *"kalau lagi nyiapin bahan presentasi?"*

**P3.** *"Analisis apa yang kamu tulis ulang dari nol terus-terusan tiap ada dataset baru?"*

**P4.** *"Kapan terakhir kamu salah ambil kesimpulan dari data? Kejadiannya gimana?"*

> Pertanyaan ini menguji apakah PP-2/PP-3 (beban verifikasi, inkonsistensi) benar-benar dirasakan, atau cuma asumsi kita.

**P5.** *"Hasil analisis kamu, gimana biasanya berakhir? Notebook, slide, atau apa? Enam bulan kemudian masih bisa dibuka?"*

> Menguji JTBD-5 dan JTBD-6.

### Bagian 2 · Konfrontasi katalog — 15 menit

**Sekarang** tunjukkan katalog 21 tool dan mockup §14.2. Jelaskan singkat — maksimal 3 menit, tanpa arsitektur:

> *"Idenya: semua analisis dilakukan lewat tool yang sudah jadi dan hasilnya selalu sama, bukan lewat AI yang nulis kode. AI cuma milih tool mana yang dipakai. Setiap angka bisa diklik untuk lihat asalnya."*

**P6.** *"Dari yang kamu sebutin tadi, mana yang kelihatannya kejawab, mana yang enggak?"*

> Jangan bantu menjawab. Biarkan mereka yang mengklasifikasi — hasilnya lebih jujur daripada kamu yang menilai sendiri.

**P7.** *"Kalau tool ini nggak bisa ngelakuin sesuatu yang kamu butuh, kamu bakal cari akal di sini, atau langsung buka Jupyter?"*

> ⭐ **Ini pertanyaan paling menentukan untuk R-1.** Kalau jawabannya "langsung Jupyter" tanpa ragu, erosi yang dijelaskan di R-1 akan terjadi.

**P8.** *"Apa yang bikin kamu nggak percaya sama hasil analisis dari AI?"*

> Menguji apakah proposisi nilai inti (determinisme + traceability) memang menyentuh masalah nyata mereka, atau cuma elegan di atas kertas.

**P9.** *"Kalau ini dikasih ke kamu gratis besok, kamu bakal pakai buat apa? Atau nggak sama sekali?"*

### Bagian 3 · Kompetitif & moat — 10 menit

**P10.** *"Pernah coba Julius, ChatGPT Advanced Data Analysis, Hex, atau Copilot buat analisis data? Gimana ceritanya?"*

> Probe kalau berhenti pakai: *"berhentinya kenapa?"* — inilah O-2.

**P11.** *"Di industri kita, ada analisis yang berulang terus tapi nggak ada tool-nya? Yang tiap orang bikin sendiri-sendiri?"*

> Inilah O-3, bahan untuk OQ-13 opsi (c).

**P12.** *"Kalau ada tool kayak gini beneran jadi, apa yang bikin kamu berhenti pakai setelah sebulan?"*

### Bagian 4 · Penutup — 5 menit

**P13.** *"Ada yang menurut kamu saya salah lihat, atau saya lewatkan?"*

Lalu: minta izin menghubungi lagi, dan **jangan** minta mereka jadi penguji Gerbang 4 (mereka sudah melihat produknya — mata mereka tidak lagi segar, dan §20 sudah menetapkan Gerbang 4 untuk 4 analis).

---

## 5. Menangani belokan yang bisa ditebak

| Kalau mereka… | Jawab |
|---|---|
| Bertanya soal arsitektur / stack | *"Nanti saya ceritain terpisah — sekarang saya lagi ngejar soal kegunaannya dulu."* |
| Mulai merancang fitur untukmu | Catat, lalu tarik balik: *"menarik — itu muncul dari kasus apa?"* Kebutuhan di baliknya lebih berharga daripada solusi usulannya |
| Memuji tanpa isi | *"Yang paling bikin kamu ragu bagian mana?"* |
| Bilang "bagus sih, cuma…" | **Berhenti dan gali.** Yang setelah "cuma" adalah isi sesungguhnya |
| Menyarankan pakai LLM untuk semuanya | *"Kalau angkanya salah dan kamu nggak sadar, gimana?"* — ini menguji apakah PP-2 dirasakan |
| Diam / kehabisan bahan | Ganti konteks, bukan ganti topik: *"kalau lagi ngecek data yang baru masuk dari vendor?"* |

---

## 6. Lembar skor — mengubah jawaban jadi angka

Untuk **setiap** pertanyaan analisis yang mereka sebutkan (dari P1–P3), klasifikasikan **setelah sesi**, bukan saat sesi:

| Kode | Arti | Cara mengecek |
|---|---|---|
| **✅ L** | Terjawab **langsung** oleh satu tool | Ada di katalog §11.4 |
| **✅ K** | Terjawab lewat **komposisi** primitif | Bisa disusun `filter`→`derive`→`aggregate`→`plot` (T2) |
| **🟡 P** | Terjawab kalau ada **parameter tambahan** pada tool yang sudah ada | T1 — Mekanisme 5, §11.5 |
| **❌ B** | Butuh **tool baru** | T3 — tidak tertutup mekanisme apa pun |
| **⛔ N** | **Non-goal** yang memang sudah ditolak sadar | Ada di §16 / §6.2 |

**Perhitungan:**

```
M-1 (in-scope) = (L + K + P) / (L + K + P + B)          ← angka keputusan
M-1 (kasar)    = (L + K + P) / (L + K + P + B + N)      ← angka pengawasan
```

Kenapa dua angka: **M-1 in-scope** menjawab *"apakah katalog cukup untuk hal yang memang kita janjikan?"* — itu yang dipakai memutuskan. **M-1 kasar** menjawab *"seberapa sering pengguna menabrak batas yang kita pilih sendiri?"* Kalau selisih keduanya lebar, non-goals kita ternyata menyakitkan bagi pengguna — dan itu sinyal tersendiri, bukan kegagalan.

---

## 7. Apa yang dilakukan dengan hasilnya

| M-1 (in-scope) | Artinya | Tindakan |
|---|---|---|
| **≥ 80%** | Katalog sejalan dengan kebutuhan nyata | Lanjut Fase 1 apa adanya |
| **70–79%** | Cukup, dengan celah yang jelas | Lanjut Fase 1. Semua **🟡 P** masuk backlog parameter Tier 1–2; semua **❌ B** masuk backlog tool berperingkat |
| **60–69%** | Mengkhawatirkan | Lanjut Fase 1, **tapi** tinjau §11.5 dulu. Pertimbangkan menaikkan 2–3 analyzer dari P1 ke P0 |
| **< 60%** | 🚨 Asumsi inti kemungkinan salah | **Jangan mulai Fase 1.** Tinjau §11.5 menyeluruh; buka lagi Mekanisme 4 (escape hatch); pertimbangkan mempersempit ke vertikal (OQ-13c) |

**Selalu dilakukan apa pun angkanya:**
- Setiap pertanyaan **✅ L / ✅ K** yang belum ada di golden queries → kandidat query baru
- Setiap **🟡 P** → kandidat parameter Tier 1–2 pada tool terkait (D-019)
- Setiap **❌ B** → masuk backlog tool, diurutkan berdasarkan berapa orang menyebutnya
- Jawaban P7 dicatat terpisah — itu penilaian langsung terhadap R-1
- Jawaban P10 & P11 masuk berkas OQ-13

---

## 8. Setelah ketiga sesi selesai

1. Gabungkan daftar pertanyaan; hilangkan duplikat; hitung berapa orang menyebut hal serupa
2. Hitung M-1 in-scope dan kasar, per orang **dan** gabungan
3. Catat hasilnya di §20 Fase 0 dan perbarui baris **R-1** di §17 — turunkan kemungkinan **hanya** kalau angkanya mendukung
4. Kalau OQ-13 mendapat sinyal kuat (mis. dua orang menyebut vertikal yang sama), catat di §19 — tapi **jangan putuskan**; tenggatnya tetap setelah Gerbang 5
5. Gerbang 0 terlampaui → Fase 1 dimulai

---

## 9. Jebakan yang paling sering terjadi

| Jebakan | Akibat |
|---|---|
| Menunjukkan katalog sebelum elicitation | M-1 palsu-tinggi. **Kesalahan paling merusak di seluruh protokol** |
| Sesi bersama, bukan terpisah | Satu suara dominan, dua anggukan, nol sampel independen |
| Mencatat parafrase, bukan kata asli | Bias konfirmasi masuk lewat pintu belakang |
| Membela produk saat dikritik | Setiap pembelaan menutup satu pintu informasi |
| Menghitung skor saat sesi berlangsung | Perhatianmu pindah dari mendengar ke menilai |
| Menurunkan R-1 karena sesinya terasa positif | Perasaan bukan bukti. Hanya angka yang boleh menggerakkan risk register |
| Memakai peserta ini juga untuk Gerbang 4 | Mata segar adalah sumber daya tidak terbarukan (§20) |

---

## Changelog

| Versi | Tanggal | Perubahan |
|---|---|---|
| 0.1.0 | 2026-07-28 | Protokol awal. Menyasar R-1 dan OQ-13. |
