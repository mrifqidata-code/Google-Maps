# Monitoring Review Google Maps · Sparks Swim

Memantau rating dan ulasan Google Maps semua cabang Sparks Swim secara otomatis, lalu menampilkannya di
dashboard web (GitHub Pages).

- **Sumber data:** [SerpApi](https://serpapi.com), yang mengambil ulasan publik Google Maps. Paket gratisnya
  (250 request/bulan) tidak butuh kartu kredit.
- **Jadwal:** GitHub Actions berjalan setiap hari pukul 06.17 WIB. Cabang dicek bergiliran supaya kuota gratis cukup
  sebulan penuh. Cabang baru dicari otomatis setiap Senin.
- **Dashboard:** `https://mrifqidata-code.github.io/Google-Maps/` (aktif setelah setup di bawah).

Dashboard menampilkan:

- ringkasan: rata-rata rating tertimbang, total ulasan, ulasan baru, ulasan bintang 1–3 dan berapa yang **belum
  dibalas** pemilik;
- tren rating / jumlah ulasan per hari (cabang terpilih dibandingkan cabang lain);
- tabel per cabang: rating, perubahan rating, ulasan baru, ulasan buruk yang belum dibalas, kapan terakhir dicek;
- daftar ulasan terbaru beserta balasan pemilik, bisa difilter per cabang, periode, bintang, atau "belum dibalas".

## Setup (sekali saja)

1. **Daftar SerpApi** di <https://serpapi.com/users/sign_up> (cukup email; verifikasi email/nomor HP sesuai
   petunjuk di sana). Setelah masuk, salin **Private API Key** dari halaman *Dashboard / Api Key*.
2. **Simpan API key di GitHub:** *Settings → Secrets and variables → Actions → New repository secret*,
   nama `SERPAPI_API_KEY`, isi dengan API key tadi. Jangan tulis key ini di file mana pun di repo.
3. **Aktifkan GitHub Pages:** *Settings → Pages → Build and deployment → Source:* pilih **GitHub Actions**.
4. **Pastikan kode ada di default branch.** Jadwal otomatis GitHub Actions hanya berjalan di default branch.
5. **Cari semua cabang:** tab *Actions → Kelola cabang → Run workflow*, pilih aksi `discover`.
   Log-nya menampilkan cabang yang ditemukan (`BARU`) dan tempat yang diabaikan karena namanya tidak mengandung
   "Sparks Swim". Setelah selesai, workflow ini otomatis menjalankan *Monitor review* untuk mengambil data pertama.
6. Buka dashboard di URL GitHub Pages di atas.

## Kuota SerpApi

Setiap pengecekan satu cabang = 1 request (rating, total ulasan, dan 8 ulasan terbaru sekaligus).

- Kuota harian = (kuota bulanan − cadangan) ÷ 31. Dengan paket gratis: (250 − 20) ÷ 31 = **7 cabang per hari**.
- Cabang yang paling lama belum dicek didahulukan. Dengan 8–16 cabang, tiap cabang dicek kira-kira tiap 1–2,5 hari,
  dan dashboard tetap diperbarui setiap hari.
- Kalau sejak pengecekan terakhir ada lebih dari 8 ulasan baru, halaman berikutnya ikut diambil (maks. 3 request per
  cabang) supaya tidak ada ulasan yang terlewat.
- Sebelum mulai, script membaca sisa kuota dari akun SerpApi (gratis, tidak mengurangi kuota) dan tidak akan
  melewatinya. Kalau paket di-upgrade, kuota harian otomatis ikut naik.
- Cadangan 20 request dipakai untuk mencari cabang baru (sekitar 2 request per minggu) dan menambah cabang dari link
  yang tidak memuat ID tempat.

Angkanya bisa diubah di bagian `quota` pada [`config/centers.json`](config/centers.json).

## Mengelola daftar cabang

Daftar cabang ada di [`config/centers.json`](config/centers.json):

```json
{
  "place_id": "ChIJ...",
  "data_id": "0x2e69f...:0x...",
  "name": "Sparks Swim Bintaro",
  "label": "Bintaro",
  "address": "...",
  "maps_url": "https://www.google.com/maps/place/?q=place_id:ChIJ...",
  "enabled": true,
  "source": "discover",
  "added_at": "2026-10-13"
}
```

- **Tambah cabang dari link Google Maps:** *Actions → Kelola cabang → Run workflow*, pilih aksi `add`, lalu tempel
  satu atau beberapa link (pisahkan dengan spasi). Link `maps.app.goo.gl/...` dan `google.com/maps/place/...` biasanya
  sudah memuat ID tempat, jadi tidak memakai kuota.
- **Hasil pencarian salah** (bukan cabang Sparks Swim): ubah `"enabled": true` menjadi `false`. Cabang itu tidak
  akan ditambahkan ulang oleh pencarian berikutnya.
- **Ganti nama tampilan:** tambahkan `"label": "Nama pendek"`.
- **Ubah area pencarian:** edit `search.queries`. `ll` adalah titik tengah peta dan zoom (`@lat,lng,zoomz`).
  Defaultnya Jabodetabek (`@-6.25,106.8,10z`) dan seluruh Indonesia (`@-2.5,118,5z`).

## Cara kerja

```
GitHub Actions (harian)
  └─ python3 -m monitor fetch
       ├─ cek sisa kuota (Account API, gratis)
       ├─ untuk cabang yang dapat giliran: Google Maps Reviews (urut terbaru)
       │     → rating, total ulasan, ulasan baru + balasan pemilik
       └─ tulis docs/data/{summary,history,reviews}.json → commit ke repo
  └─ deploy folder docs/ ke GitHub Pages
```

| File | Isi |
|---|---|
| `docs/data/summary.json` | kondisi terbaru tiap cabang (rating, jumlah ulasan, kapan dicek, error) |
| `docs/data/history.json` | satu titik per pengecekan per hari: rating dan jumlah ulasan |
| `docs/data/reviews.json` | semua ulasan yang pernah tercatat (tanpa duplikat), termasuk balasan pemilik |

## Batasan yang perlu diketahui

- **SerpApi bukan API resmi Google.** SerpApi mengambil data dari halaman publik Google Maps. Datanya sama dengan yang
  dilihat pengunjung, tapi cara ini berada di luar API resmi Google, jadi pertimbangkan risikonya untuk pemakaian
  jangka panjang. Cara resmi yang lengkap adalah lewat akses pengelola Google Business Profile tiap cabang.
- **Ulasan muncul dengan jeda** 1–2 hari karena cabang dicek bergiliran. Untuk pengecekan harian semua cabang
  diperlukan paket berbayar (mulai sekitar $25/bulan untuk 1.000 request).
- **Ulasan lama tidak diambil.** Pengecekan pertama tiap cabang hanya mengambil 8 ulasan terbaru; setelah itu
  semua ulasan baru tercatat.
- **Repo dan dashboard bersifat publik** (termasuk nama pengulas, sama seperti yang tampil di Google Maps).

## Menjalankan secara lokal

Tidak butuh dependency selain Python 3.9+.

```bash
export SERPAPI_API_KEY=...
python3 -m monitor discover --dry-run   # lihat hasil pencarian tanpa mengubah config
python3 -m monitor discover             # simpan cabang yang cocok ke config/centers.json
python3 -m monitor add https://maps.app.goo.gl/xxxx
python3 -m monitor fetch                # ambil data ke docs/data/

python3 -m http.server -d docs 8000     # buka http://localhost:8000
python3 -m unittest discover -s tests -t .
```
