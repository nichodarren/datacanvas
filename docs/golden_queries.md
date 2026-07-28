# Golden Queries — Kontrak Evaluasi DataCanvas

| | |
|---|---|
| **Versi** | 0.3.0 |
| **Status** | 🟢 **Verified** — 29 query selaras dengan batas scope D-020; seluruh nilai harapan terverifikasi terhadap file yang dibundel (§6) |
| **Tanggal** | 2026-07-28 |

> ### Penyesuaian terhadap D-020 — selesai
>
> Batas scope MVP kini **"analisis yang interpretasinya tidak bergantung konteks domain"** (§11.4 DESIGN.md). Dampaknya pada dokumen ini:
>
> | Tier | Nasib |
> |---|---|
> | **A** (5) · **B** (6) · **D** (3) · **E** (2) · **G** (1) | ✅ Selamat tanpa perubahan |
> | **C** (6) | ♻️ **C1, C2, C3, C5 diganti.** Penggantinya menguji komposisi primitif berantai — yang justru lebih penting untuk Mekanisme 1. C4 & C6 selamat |
> | **F** (2) | ✅ Selamat, dan **F1 makin kuat** — uji-t kini lebih jelas di luar batas |
> | **H** (4) | ➕ **Tier baru — Cleaning.** Menguji pasangan peringatan PQ → tool perbaikan di `messy_sales` |
>
> **Total 25 → 29.** Nilai untuk query yang selamat tidak dihitung ulang; hanya query baru yang diverifikasi.
| **Induk** | [`DESIGN.md`](DESIGN.md) §12.9, §15.1, §20 |

---

## 1. Untuk apa dokumen ini

Ini **bukan** kumpulan test biasa. Ini **definisi "MVP selesai"**.

§15.1 DESIGN.md menyatakan gerbang rilis: *"25 golden query lulus 3 run berturut-turut."* Dokumen ini adalah 25 query itu. Kalau sebuah kemampuan tidak diuji di sini, ia bukan bagian dari janji MVP.

Ditulis **sebelum satu baris kode pun ada** — itu disengaja. Golden query yang ditulis setelah sistem jadi akan menjadi test yang kebetulan lulus. Ditulis sekarang, ia menjadi target.

### Tiga hal yang diuji

| | Apa | Kenapa |
|---|---|---|
| **Kemampuan** | Tier A–E — bisakah sistem menjawab pertanyaan EDA nyata | Coverage katalog (M-1) |
| **Kejujuran** | Tier F — apakah sistem menolak yang memang di luar kemampuannya | P6 · **menjawab = GAGAL** |
| **Determinisme** | Tier G — apakah pertanyaan sama menghasilkan komputasi identik | P1, INV-6 (M-4) |

> **Tier F adalah tier terpenting di dokumen ini.** Ia menguji proposisi nilai inti produk. Sistem yang selalu menjawab sesuatu tidak bisa dipercaya di mana pun — dan setiap kompetitor sudah bisa "selalu menjawab sesuatu".

---

## 2. Aturan gerbang

**Lulus = seluruh 25 query lulus 3 run berturut-turut**, termasuk **setiap varian parafrasenya**. Kurang dari itu berarti belum selesai — bukan "hampir selesai".

### Hard check — menggagalkan query

| # | Kondisi gagal |
|---|---|
| H-1 | Tidak ada tool yang dieksekusi |
| H-2 | Narasi kosong |
| H-3 | Sitasi `[ref: …]` tidak resolve ke Step di turn itu |
| H-4 | **Ada angka di narasi yang tidak terdapat pada komputasi yang dirujuk** (cocokkan numerik dengan toleransi) |
| H-5 | Nilai harapan meleset di luar toleransi |
| H-6 | Chart tidak ter-render pada query Tier D |
| H-7 | **Query Tier F dijawab, bukan ditolak** |
| H-8 | **Query Tier G menghasilkan `computation_id` berbeda antar run** |

> H-4 menutup mode kegagalan paling berbahaya: model mengutip komputasi yang **benar** tapi salah membaca angkanya. Ini terjadi, dan tanpa pemeriksaan numerik ia tidak terdeteksi.

### Soft check — dilaporkan, tidak menggagalkan

Planner memilih jalur tool berbeda tapi tetap valid · tool ekstra dipanggil · error validasi yang berhasil dipulihkan · jumlah langkah lebih banyak dari perkiraan.

### Toleransi numerik

Nilai desimal: `abs(actual - expected) / expected < 0.005` (0,5%). Hitungan bilangan bulat: harus persis.

---

## 3. Dataset

Semua dataset publik atau dibangun sendiri (A-11 — tidak ada data kantor selama pengembangan).

Semuanya sudah **dibundel** di `eval/datasets/` dan **diverifikasi** (§6). Sidik jari dicatat agar setiap perbedaan hasil di masa depan dapat dilacak ke perubahan file, bukan ditebak.

| Key | Bentuk | Ukuran | SHA-256 | Dipakai untuk |
|---|---|---|---|---|
| `titanic` | 891 × 12 | 60.302 B | `4a437fde05fe5264…af5af4bd7` | Campuran tipe, null nyata, kategori kecil |
| `hotel_bookings` | 119.390 × 32 | 16.855.599 B | `7c2ae42a7353905e…c7b1fc06` | Skala, kardinalitas tinggi, null ekstrem |
| `tips` | 244 × 7 | 9.729 B | `e54cc4d2ce1bff65…70e863b0` | Kecil & bersih, grup kecil untuk uji PG-1 |
| `messy_sales` | 5.000 × 12 | 482.834 B | `2b7dd28a9f12ca1e…6d9f917d` | Data kotor terkendali; fixture PQ-1…PQ-14 |

**Sumber:**
`titanic` — mirror kanonik Kaggle `train.csv` (datasciencedojo/datasets) · `hotel_bookings` — Antonio et al. via TidyTuesday 2020-02-11 · `tips` — seaborn-data · `messy_sales` — dibangkitkan `eval/fixtures/build_messy_sales.py` (§4)

> ⚠️ **Kesalahan yang tertangkap saat verifikasi.** Dokumentasi v1 mencatat `tips` sebagai **35 baris**. File seaborn yang sebenarnya berisi **244 baris**. Kalau angka itu dibawa ke sini tanpa diperiksa, seluruh nilai harapan Tier B3/C3/C5/E2 akan salah — dan kegagalannya hampir pasti disalahartikan sebagai bug planner. Ini persis alasan §6 ada.

> **Perubahan dari draft awal:** dataset `students` dari v1 dihapus. Ia sintetis dan tidak terdokumentasi asal-usulnya, sehingga nilai harapannya tidak dapat diverifikasi siapa pun. Digantikan `messy_sales` yang **dispesifikasi sepenuhnya**, sehingga setiap nilai harapan benar menurut konstruksi.

---

## 4. Spesifikasi `messy_sales`

Dataset ini menjalankan dua peran sekaligus: skenario uji pengguna di Gerbang 4 (§20 DESIGN.md), dan fixture unit test untuk katalog peringatan §11.7.4.

**Konstruksi:** 5.000 baris, dibangkitkan dengan seed tetap (`seed=20260728`), disimpan sebagai CSV. Skrip pembangkit ada di `eval/fixtures/build_messy_sales.py` dan hasilnya di-commit — jadi datanya reproducible **dan** stabil. Skrip memverifikasi dirinya sendiri: setiap cacat dihitung ulang setelah dibangkitkan, dan gagal keras bila jumlahnya meleset.

| Kolom | Tipe fisik | Cacat yang sengaja ditanam | PQ yang harus terpicu |
|---|---|---|---|
| `order_id` | integer | Unik, berurutan 1…5000 | **PQ-3** (terlihat seperti identifier) |
| `order_date` | text | Tanggal valid tapi disimpan sebagai teks (`2024-03-01`) | **PQ-8** (>90% parseable jadi date) |
| `region` | text | `Surabaya` 1.400 · `Medan` 1.170 · `Jakarta` 1.100 · `Bandung` 1.000 · `jakarta` 180 · `Jakarta ` 90 · `​ Medan` 60 → **7 nilai distinct mentah, 4 setelah normalisasi** | **PQ-5** (varian kapitalisasi) · **PQ-10** (150 nilai berspasi) |
| `customer_name` | text | 4.800 nilai unik | **PQ-6** bila keliru di-set `categorical` |
| `amount` | decimal | 340 baris bernilai persis `9999` | **PQ-1** (penanda null menyamar) |
| `discount_pct` | decimal | 4.960 baris bernilai `0.0` (99,2%) | **PQ-2** (nyaris konstan) |
| `qty` | integer | Hanya 5 nilai unik: 1,2,3,4,5 | **PQ-4** (terlihat seperti kategori) |
| `status` | text | `completed` 4.760 (95,2%) · `completed ` 50 · `pending` 130 · `refunded` 60 | **PQ-7** (satu nilai dominan) · **PQ-10** (50 nilai berspasi) |
| `notes` | text | 3.100 null (62%) | **PQ-14** (null > 50%) |
| `signup_date` | date | 210 baris bernilai `1900-01-01` | **PQ-12** (tanggal placeholder) |
| `legacy_code` | text | 4.850 murni numerik (97%), 150 alfanumerik `LG-xxx` | **PQ-9** |
| `promised_date` | date | 95 baris bertanggal **2099-06-15** | **PQ-11** (tanggal masa depan) |

> **Kenapa `promised_date` memakai tahun 2099, bukan "hari ini + N".** PQ-11 memeriksa tanggal di masa depan relatif terhadap saat test dijalankan. Kalau fixture memakai tanggal relatif, maknanya berubah seiring waktu dan test akan mulai gagal sendiri suatu hari nanti. Tahun 2099 membuatnya benar selamanya. Prinsip yang sama berlaku di seluruh generator: **tidak ada `datetime.now()` di mana pun.**

**Ambang PQ-7 dan varian spasi sengaja dibuat tidak saling meniadakan.** `completed` mentah = 95,2%, tepat di atas ambang dominasi 95% — sehingga PQ-7 terpicu pada data mentah, **dan** PQ-10 tetap terpicu oleh 50 nilai berspasi. Kalau `completed ` dibuat terlalu banyak, dominasi mentah turun di bawah ambang dan PQ-7 diam. Interaksi seperti ini justru yang ingin diuji.

**Tidak terpicu oleh dataset ini:** PQ-13 (lonjakan impor batch). Diuji terpisah lewat unit test sintetis — menanamnya di sini akan mengganggu distribusi `order_date` yang dipakai query lain.

---

## 5. Skema tiap query

```yaml
id:              A1
intent:          deskripsi singkat maksud pengguna
prompt:          kalimat utama (bahasa Inggris)
paraphrases:     2–3 cara lain menanyakan hal yang sama — SEMUANYA harus lulus
dataset:         key dataset
expected_tools:  jalur tool yang diharapkan (soft check — jalur lain boleh asal valid)
expected_values: nilai yang harus muncul & tersitasi (hard check)
pass:            kriteria lulus dalam satu kalimat
```

**Kenapa parafrase, bukan dua bahasa (OQ-11).** Mode kegagalan nyata di v1 bukan bahasa, melainkan kerapuhan terhadap cara bertanya: pencocokan keyword gagal pada `"how is age spread out?"` karena tidak mengandung `"distribution"`. Menguji tiga cara menanyakan hal yang sama menguji apakah planner memahami **maksud**, bukan mencocokkan **string**.

---

## 6. ✅ Verifikasi nilai — SELESAI

**Status: 72/72 nilai harapan terverifikasi terhadap file yang benar-benar dibundel** (2026-07-28).

```
python eval/verify_expected_values.py
→ SEMUA NILAI HARAPAN COCOK — golden_queries.md boleh naik ke status Verified.
```

Skrip menghitung ulang setiap `expected_values` di dokumen ini langsung dari `eval/datasets/`, lalu membandingkannya dengan yang tertulis. Aturannya tetap berlaku untuk selamanya: **kalau skrip dan dokumen berbeda, dokumen yang dikoreksi — bukan filenya, dan bukan pula ekspektasinya dilonggarkan.**

Toleransi: nilai desimal 0,5% relatif; hitungan bilangan bulat harus persis.

**Jalankan ulang skrip ini setiap kali:** file dataset diganti · SHA-256 di §3 tidak lagi cocok · sebuah nilai harapan diedit manual.

Nilai `messy_sales` tidak diverifikasi di sini — ia benar menurut konstruksi, dan generatornya memverifikasi dirinya sendiri (§4).

---

## Tier A — Profil & Skema (5)

### A1 · Orientasi dataset asing
**Prompt** `"Give me a quick profile of this dataset."`
**Paraphrases** `"What's in this data?"` · `"Summarize this dataset for me."` · `"I just got this file — what am I looking at?"`
**Dataset** `titanic`
**Expected tools** `describe_dataset` → *(opsional)* `missingness_report`
**Expected values** 891 baris · 12 kolom · `Age` null 19,87% · `Cabin` null 77,10%
**Pass** Menyebut bentuk dataset **dan** minimal satu masalah kualitas; setiap angka bersitasi.

### A2 · Menemukan kolom yang nyaris kosong
**Prompt** `"Which columns are mostly empty?"`
**Paraphrases** `"Where is the missing data?"` · `"Show me columns with a lot of nulls."` · `"Which fields are barely populated?"`
**Dataset** `hotel_bookings`
**Expected tools** `missingness_report`
**Expected values** `company` 94,31% · `agent` 13,69% · `country` 0,41% — berurutan dari yang terbesar
**Pass** `company` teridentifikasi sebagai yang terparah; persentase tersitasi.

### A3 · Profil satu kolom numerik
**Prompt** `"Describe the distribution of Age."`
**Paraphrases** `"How is age spread out?"` · `"What does the Age column look like?"` · `"Tell me about the ages in this data."`
**Dataset** `titanic`
**Expected tools** `profile_column(column="Age")`
**Expected values** mean ≈ 29,70 · median 28,0 · std ≈ 14,53 · null 177 (19,87%)
**Pass** Tendensi sentral **dan** sebaran disebut; null tidak diabaikan diam-diam.
> Parafrase `"how is age spread out?"` adalah kasus yang gagal di v1. Ia **wajib** lulus.

### A4 · Mendeteksi tipe yang mencurigakan
**Prompt** `"Are any column data types wrong or suspicious?"`
**Paraphrases** `"Does anything look mistyped here?"` · `"Check if the column types make sense."`
**Dataset** `messy_sales`
**Expected tools** `type_consistency_report` atau `profile_column` per kolom
**Expected values** Minimal 3 dari: `order_date` teks tapi tanggal (PQ-8) · `qty` numerik tapi 5 nilai (PQ-4) · `legacy_code` teks tapi numerik (PQ-9) · `order_id` terlihat identifier (PQ-3)
**Pass** Kolom bermasalah disebut **beserta alasannya**, bukan sekadar daftar.

### A5 · Kardinalitas
**Prompt** `"Which columns have too many distinct values to use as categories?"`
**Paraphrases** `"Show me the high-cardinality columns."` · `"Which fields have the most unique values?"`
**Dataset** `hotel_bookings`
**Expected tools** `cardinality_report`
**Expected values** Kolom seperti `country`, `agent`, `reservation_status_date` berada di peringkat teratas; hitungan distinct tersitasi
**Pass** Peringkat kardinalitas benar; menjelaskan implikasinya untuk pemakaian sebagai dimensi.

---

## Tier B — Analisis Satu Langkah (6)

### B1 · Agregasi dasar
**Prompt** `"What's the average fare by passenger class?"`
**Paraphrases** `"Break down fare by class."` · `"How does ticket price differ across classes?"` · `"Mean fare per Pclass please."`
**Dataset** `titanic`
**Expected tools** `aggregate(group_by=["Pclass"], measures=[mean("Fare")])`
**Expected values** 1st ≈ 84,15 · 2nd ≈ 20,66 · 3rd ≈ 13,68
**Pass** Ketiga nilai muncul dan tersitasi.

### B2 · Deteksi outlier
**Prompt** `"Are there outliers in the ADR column?"`
**Paraphrases** `"Any extreme values in adr?"` · `"Check adr for anomalies."`
**Dataset** `hotel_bookings`
**Expected tools** `outlier_scan(column="adr", method="iqr")`
**Expected values** Jumlah outlier + batas bawah/atas IQR, konsisten dengan aturan IQR deterministik
**Pass** Metode disebut eksplisit ("menurut aturan IQR"), bukan klaim outlier tanpa definisi.

### B3 · Agregasi pada dataset kecil
**Prompt** `"What's the average tip by day of the week?"`
**Paraphrases** `"Which day gets the best tips?"` · `"Average tip per day."`
**Dataset** `tips`
**Expected tools** `aggregate(group_by=["day"], measures=[mean("tip")])`
**Expected values** Thur ≈ 2,771 · Fri ≈ 2,735 · Sat ≈ 2,993 · Sun ≈ 3,255
**Pass** Keempat hari muncul; Minggu teridentifikasi tertinggi.

### B4 · Profil kolom lengkap
**Prompt** `"Give me a full profile of total_bill."`
**Paraphrases** `"Everything about the total_bill column."` · `"Full stats for total_bill."`
**Dataset** `tips`
**Expected tools** `profile_column(column="total_bill")`
**Expected values** mean ≈ 19,79 · 244 nilai · 0 null · kuantil disebut
**Pass** Kelengkapan, tendensi sentral, dan sebaran semuanya hadir.

### B5 · Filter dengan ekspresi
**Prompt** `"How many passengers were under 18?"`
**Paraphrases** `"Count the children on board."` · `"How many people younger than 18?"`
**Dataset** `titanic`
**Expected tools** `filter_rows(expression="[Age] < 18")` → `aggregate(count)`
**Expected values** 113 penumpang
**Pass** Hitungan persis; **dan menyebutkan bahwa 177 baris beumur null tidak terhitung** — kejujuran tentang data hilang.

### B6 · Agregasi biner
**Prompt** `"How many bookings were canceled versus not canceled?"`
**Paraphrases** `"What's the cancellation breakdown?"` · `"Split bookings by cancellation status."`
**Dataset** `hotel_bookings`
**Expected tools** `aggregate(group_by=["is_canceled"])`
**Expected values** Dibatalkan 44.224 (37,04%) · tidak dibatalkan 75.166
**Pass** Kedua hitungan muncul; persentase benar.

---

## Tier C — Eksplorasi Multi-Langkah (6)

> **Perubahan D-020.** Tier ini semula menguji `target_association` dan `segment_compare` — keduanya kini ditunda karena interpretasinya bergantung konteks domain (§11.4 DESIGN.md). Penggantinya menguji hal yang justru lebih penting untuk Mekanisme 1: **komposisi primitif berantai**. Perhatikan C2 — **pertanyaannya tetap sama, hanya toolnya berubah** dari `segment_compare` menjadi `aggregate` deskriptif. Itu menunjukkan batas scope memotong *cara menjawab*, bukan selalu *pertanyaannya*.

### C1 · Derive lalu agregasi
**Prompt** `"What's the average tip percentage by day?"`
**Paraphrases** `"Which day has the best tip rate?"` · `"Tip as a share of the bill, broken down by day."` · `"How generous are people each day, relative to the bill?"`
**Dataset** `tips`
**Expected tools** `derive_column(name="tip_rate", expression="[tip] / [total_bill]")` → `aggregate(group_by=["day"], measures=[mean("tip_rate")])`
**Expected values** Fri ≈ 0,1699 · Sun ≈ 0,1669 · Thur ≈ 0,1613 · Sat ≈ 0,1532
**Pass** Kolom turunan muncul sebagai Step tersendiri yang bisa diperiksa; keempat nilai tersitasi; **narasi mengakui selisihnya kecil** — tidak melebih-lebihkan (P6 dalam bentuk interpretasi).

### C2 · Tingkat kejadian per segmen — deskriptif
**Prompt** `"What's the cancellation rate for each hotel type?"`
**Paraphrases** `"How often does each hotel type get canceled?"` · `"Cancellation rate by hotel."`
**Dataset** `hotel_bookings`
**Expected tools** `aggregate(group_by=["hotel"], measures=[mean("is_canceled")])`
**Expected values** City Hotel ≈ 41,7% · Resort Hotel ≈ 27,8%
**Pass** Kedua tingkat tersitasi; selisihnya dinyatakan sebagai **fakta deskriptif**, bukan sebagai klaim bahwa jenis hotel *menyebabkan* pembatalan (R-9).

### C3 · Filter lalu agregasi bertingkat
**Prompt** `"For passengers under 18, how does the survival rate differ by class?"`
**Paraphrases** `"Survival of children, broken down by class."` · `"Among minors, which class survived most?"`
**Dataset** `titanic`
**Expected tools** `filter_rows(expression="[Age] < 18")` → `aggregate(group_by=["Pclass"], measures=[mean("Survived")])`
**Expected values** 113 penumpang lolos filter · 1st 11/12 = 91,7% · 2nd 21/23 = 91,3% · 3rd 29/78 = 37,2%
**Pass** Ketiga tingkat tersitasi **dan** jumlah baris per kelas disebut — kelas 1 dan 2 hanya belasan/puluhan baris, jadi angkanya tidak boleh disajikan tanpa konteks ukuran sampel.

### C4 · Duplikat
**Prompt** `"Are there any duplicate records?"`
**Paraphrases** `"Check for duplicated rows."` · `"Is any passenger listed twice?"`
**Dataset** `titanic`
**Expected tools** `duplicate_report`
**Expected values** 0 duplikat baris-penuh
**Pass** Nol dilaporkan **sebagai temuan positif**, bukan sebagai kegagalan atau kekosongan.

### C5 · Agregasi di atas data kotor ⭐
**Prompt** `"Which region has the most orders?"`
**Paraphrases** `"Rank regions by order count."` · `"Where do most of our orders come from?"`
**Dataset** `messy_sales`
**Expected tools** `aggregate(group_by=["region"], measures=[count()])`
**Expected values** **7 grup** dikembalikan: `Surabaya` 1400 · `Medan` 1170 · `Jakarta` 1100 · `Bandung` 1000 · `jakarta` 180 · `Jakarta ` 90 · `` ` Medan` `` 60
**Pass** Ketujuh grup dikembalikan apa adanya (tool tidak boleh diam-diam menormalkan — itu melanggar determinisme), **DAN** sistem menandai bahwa `region` punya varian kapitalisasi/spasi (**PQ-5**, **PQ-10**) dengan saran memakai `normalize_text`.

> **Kenapa query ini penting.** Jawaban mentahnya **menyesatkan**: `Medan` (1170) terlihat peringkat dua, padahal setelah dinormalkan `jakarta` (1370) yang peringkat dua — lihat H1. Query ini menguji apakah profiling dan analisis benar-benar tersambung, bukan sekadar dua fitur yang kebetulan ada di produk yang sama.

### C6 · Tabulasi silang
**Prompt** `"Break down survival by passenger class."`
**Paraphrases** `"Cross-tab Pclass against Survived."` · `"Did class affect who survived?"`
**Dataset** `titanic`
**Expected tools** `crosstab(a="Pclass", b="Survived")`
**Expected values** 1st 136 selamat / 80 tidak · 2nd 87 / 97 · 3rd 119 / 372
**Pass** Keenam sel benar; tingkat keselamatan per kelas dinyatakan.

---

## Tier D — Visualisasi (3)

### D1 · Scatter dengan encoding warna
**Prompt** `"Plot fare versus age, colored by survival."`
**Paraphrases** `"Scatter plot of age and fare, split by who survived."` · `"Show fare against age with survival as color."`
**Dataset** `titanic`
**Expected tools** `plot(mark="point", encoding={x:"Age", y:"Fare", color:"Survived"})`
**Expected values** —
**Pass** Chart ter-render · encoding sesuai permintaan · ada komentar visual singkat.

### D2 · Histogram dengan binning eksplisit
**Prompt** `"Plot the distribution of lead time."`
**Paraphrases** `"Histogram of lead_time."` · `"How is lead time distributed?"`
**Dataset** `hotel_bookings`
**Expected tools** `bin_column(column="lead_time")` → `plot(mark="bar")`
**Expected values** —
**Pass** Chart ter-render · **strategi binning terlihat di argumen Step** (INV-6) · narasi menyebut ekor panjang.

### D3 · Agregasi lalu visualisasi
**Prompt** `"Show a bar chart of average tip by day."`
**Paraphrases** `"Chart the mean tip for each day."` · `"Visualize tips across days."`
**Dataset** `tips`
**Expected tools** `aggregate(group_by=["day"], measures=[mean("tip")])` → `plot(mark="bar")`
**Expected values** Nilai batang cocok dengan B3
**Pass** Chart ter-render dengan empat batang; nilainya konsisten dengan agregasi.

---

## Tier E — Transformasi (2)

### E1 · Derive lalu agregasi
**Prompt** `"Create a family_size column from SibSp plus Parch, then compare survival across family sizes."`
**Paraphrases** `"Add family size and see how it relates to survival."` · `"Combine SibSp and Parch, then check survival by that."`
**Dataset** `titanic`
**Expected tools** `derive_column(name="family_size", expression="[SibSp] + [Parch]")` → `aggregate(group_by=["family_size"], measures=[mean("Survived")])`
**Expected values** `family_size` = 0 mendominasi (537 penumpang); keluarga kecil menunjukkan tingkat selamat lebih tinggi daripada penumpang sendirian
**Pass** Kolom turunan muncul sebagai Step tersendiri yang bisa diperiksa; agregasi memakainya.

### E2 · Expression language multi-langkah
**Prompt** `"For weekend parties larger than 4 people, what's the average tip rate?"`
**Paraphrases** `"Tip percentage for big weekend groups."` · `"How do large Saturday and Sunday tables tip?"`
**Dataset** `tips`
**Expected tools** `filter_rows(expression="[size] > 4 and [day] in ['Sat','Sun']")` → `derive_column(expression="[tip] / [total_bill]")` → `aggregate(mean)`
**Expected values** Hitungan baris hasil filter dilaporkan bersama rata-ratanya
**Pass** Ekspresi filter terlihat di Step · **jumlah baris disebut** (grup kecil → jangan menarik kesimpulan berlebihan).
> Query ini adalah uji utama expression language (§11.3 DESIGN.md). Kalau E2 gagal, Mekanisme 1 strategi long tail (§11.5) tidak bekerja.

---

## Tier H — Cleaning (4) 🧹

Tier baru (D-020). Semuanya di `messy_sales`, dan semuanya menguji **pasangan peringatan → tool perbaikan** (§11.4 Lapis 2b). Kriteria lulus di seluruh tier ini menuntut satu hal yang sama: **hasil pembersihan muncul sebagai Step baru dengan tabel turunan — data asli tidak pernah berubah** (INV-2).

### H1 · Normalisasi teks
**Prompt** `"The region values look inconsistent — clean them up."`
**Paraphrases** `"Fix the capitalization and spacing in region."` · `"Merge the duplicate region spellings."`
**Expected tools** `normalize_text(column="region", case="lower", trim=true)`
**Expected values** 7 nilai distinct → **4** (`bandung`, `jakarta`, `medan`, `surabaya`) · `jakarta` menjadi **1370** baris · `medan` menjadi **1230**
**Pass** Distinct turun ke 4 · **peringkat berubah**: `jakarta` naik dari peringkat 3 (1100) ke peringkat 2 (1370), melewati `medan` · tabel turunan menjadi Step baru, tabel asal utuh.

### H2 · Penanda null yang menyamar
**Prompt** `"The amount column has 9999 values that look like placeholders — treat them as missing."`
**Paraphrases** `"Mark 9999 in amount as null."` · `"Those 9999 amounts aren't real, exclude them."`
**Expected tools** `set_null_markers(column="amount", values=[9999])`
**Expected values** **340** baris menjadi null · rata-rata `amount` bergeser dari **2.352.812,07** menjadi **2.523.746,93**
**Pass** Jumlah null tepat 340 · **pergeseran rata-rata dilaporkan** — inilah bukti nyata bahwa penanda null yang tidak ditangani merusak setiap statistik di bawahnya (± 7% pada kasus ini).

### H3 · Urutan pembersihan itu penting ⭐
**Prompt** `"Cap amount at the 1st and 99th percentile."`
**Paraphrases** `"Winsorize the amount column."` · `"Trim the extreme values in amount."`
**Expected tools** `set_null_markers(column="amount", values=[9999])` → `clip_values(column="amount", method="percentile", lower=0.01, upper=0.99)`
**Expected values** Setelah penanda null ditangani: p1 = **102.806,08** · p99 = **4.954.715,07** · 47 baris di bawah p1 · 47 baris di atas p99
**Pass** — **salah satu** dari dua ini:
1. Penanda null ditangani lebih dulu, lalu batasnya benar; **atau**
2. Dijalankan langsung dan sistem **memperingatkan** bahwa p1 = **9999,00** — yaitu nilai penanda itu sendiri, bukan batas yang bermakna

**Gagal bila** sistem mengembalikan p1 = 9999 tanpa peringatan apa pun.

> **Ini query paling tajam di seluruh dokumen.** 340 baris (6,8%) bernilai persis 9999 membuat persentil ke-1 jatuh tepat di penanda null. Winsorization yang dijalankan naif menghasilkan batas bawah yang **secara teknis benar dan secara analitis omong kosong** — persis jenis kegagalan senyap yang produk ini ada untuk mencegahnya (§11.5 Mekanisme 5, D-019).

### H4 · Menangani nilai hilang
**Prompt** `"Drop the rows where notes is empty."`
**Paraphrases** `"Keep only rows that have notes."` · `"Remove records without notes."`
**Expected tools** `handle_missing(column="notes", strategy="drop_rows")`
**Expected values** 5.000 → **1.900** baris (3.100 dibuang)
**Pass** Jumlah baris tepat · **jumlah yang dibuang dinyatakan eksplisit** · strategi terlihat di argumen Step · tabel asal utuh.

---

## Tier F — Kegagalan Jujur (2) ⚠️

> **Menjawab query di tier ini adalah KEGAGALAN (H-7).** Tier ini menguji apakah sistem tahu batasnya sendiri — proposisi nilai inti produk (P6, §11.5 Mekanisme 2).

### F1 · Uji hipotesis formal — sengaja tidak ada di MVP
**Prompt** `"Run a t-test comparing fares between survivors and non-survivors."`
**Paraphrases** `"Is the fare difference statistically significant?"` · `"Give me the p-value for fare by survival."`
**Dataset** `titanic`
**Expected behavior** Penolakan eksplisit + alternatif terdekat + pencatatan permintaan
**Pass** Semua terpenuhi:
1. Menyatakan jelas bahwa uji hipotesis belum tersedia
2. Menawarkan `segment_compare` sebagai yang terdekat (memberi ukuran efek)
3. **Tidak menghasilkan p-value dari mana pun**
4. Permintaan tercatat di log kegagalan (NFR-OBS.2 → M-1)

### F2 · Peramalan / clustering — di luar scope
**Prompt** `"Forecast next month's bookings."`
**Paraphrases** `"Predict future demand from this data."` · `"Cluster the bookings into customer segments."`
**Dataset** `hotel_bookings`
**Expected behavior** Penolakan eksplisit; menyebut ini di luar batas EDA yang didukung
**Pass** Tidak ada angka ramalan · tidak ada label cluster · alternatif ditawarkan (mis. tren historis lewat `aggregate` per bulan) · permintaan tercatat.

---

## Tier G — Determinisme (1)

### G1 · Pertanyaan sama, komputasi identik
**Prosedur**
1. Jalankan B1 (`"What's the average fare by passenger class?"`) pada `titanic`
2. Catat `computation_id` dari Step agregasinya
3. Mulai Analysis **baru** pada DatasetVersion & SchemaContract yang sama
4. Jalankan prompt yang **sama persis**

**Pass** — semua harus terpenuhi:
- `computation_id` **identik** dengan run pertama
- Step kedua ditandai `cached = true`
- Nilai numerik identik hingga digit terakhir

**Uji negatif dalam query yang sama** — determinisme harus *pecah dengan benar*:
| Aksi | Harapan |
|---|---|
| Ubah `Pclass` menjadi `categorical` (SchemaContract baru) | `computation_id` **berbeda**; hasil lama **tidak** dikembalikan |
| Naikkan versi tool `aggregate` | `computation_id` **berbeda** |

> Setengah kedua dari G1 sama pentingnya dengan setengah pertama. Cache yang tidak pernah miss sama berbahayanya dengan cache yang selalu miss — dan itulah bug paling serius di v1 (§2.4, D-004).

---

## 7. Menjalankan harness

```powershell
# terminal 1
uvicorn app.main:app --port 8000

# terminal 2 — gerbang rilis
python eval/run_golden.py --runs 3
```

Keluaran per query: lulus/gagal · tool yang dipakai · langkah yang dijalankan · jumlah sitasi · latensi · provider aktif · cache hit/miss.
Verdict akhir: **GREEN** hanya bila 25/25 lulus di ketiga run, seluruh parafrase termasuk.

Harness juga melaporkan metrik yang masuk §6.3 DESIGN.md: **M-3** (tool-call correctness), **M-4** (determinism), **M-6** (citation resolve rate).

---

## 8. Aturan pemeliharaan

1. **Menambah query berarti menambah janji.** Setiap query baru memperluas definisi MVP — perlakukan seperti perubahan scope (§0.3 DESIGN.md).
2. **Jangan pernah melonggarkan `expected_values` agar test lulus.** Kalau sistem menghasilkan angka berbeda, sistemnya yang salah — kecuali verifikasi §6 membuktikan ekspektasinyalah yang keliru.
3. **Tier F tidak boleh menyusut.** Kalau sebuah kemampuan ditambahkan ke katalog nanti, pindahkan query-nya dari F ke tier lain — **jangan hapus**. Tier F yang kosong berarti kita berhenti menguji kejujuran.
4. **Parafrase yang gagal di produksi ditambahkan ke sini.** Log kegagalan (NFR-OBS.2) adalah sumber parafrase baru yang paling berharga: itu cara nyata orang bertanya.
5. Setiap perubahan dicatat di changelog dokumen ini.

---

## Changelog

| Versi | Tanggal | Perubahan |
|---|---|---|
| 0.3.0 | 2026-07-28 | **Diselaraskan dengan D-020 → 🟢 Verified.** C1/C2/C3/C5 diganti (dari `target_association`/`segment_compare`/`correlate` menjadi komposisi primitif berantai). **Tier H — Cleaning (4 query)** ditambahkan di `messy_sales`, menguji pasangan peringatan PQ → tool perbaikan. Total 25 → **29 query**; nilai terverifikasi 44 → **72**. Ditemukan saat verifikasi: `messy_sales` butuh `infer_schema_length=None` karena `legacy_code` 97% numerik — PQ-9 muncul di alam liar, dicatat sebagai requirement ingest (FR-B.3). |
| 0.2.1 | 2026-07-28 | Status turun ke 🟡 Draft akibat perubahan scope D-020. |
| 0.1.0 | 2026-07-28 | Draft awal. 25 query, tier A–G. Dataset `students` dihapus, digantikan spesifikasi `messy_sales`. Nilai harapan belum diverifikasi. |
| 0.2.0 | 2026-07-28 | **Status → 🟢 Verified.** Dataset dibundel ke `eval/datasets/` + SHA-256 dicatat. `messy_sales` dibangkitkan & memverifikasi diri (15/15 cacat tertanam). `eval/verify_expected_values.py` dijalankan: **44/44 nilai cocok**. Spesifikasi §4 disesuaikan agar PQ-7 dan PQ-10 tidak saling meniadakan, dan `promised_date` dipindah ke 2099 agar fixture tidak berubah makna seiring waktu. Tercatat: dokumentasi v1 keliru menyebut `tips` 35 baris (sebenarnya 244). |
