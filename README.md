# Monitoring Review Google Maps · Sparks Swim

Memantau rating dan ulasan Google Maps semua cabang Sparks Swim secara otomatis, lalu menampilkannya di
dashboard web (GitHub Pages).

- **Sumber data:** Google Places API (New), memakai API key dari Google Cloud.
- **Jadwal:** GitHub Actions mengambil data setiap hari pukul 06.17 WIB, dan mencari cabang baru setiap Senin.
- **Dashboard:** `https://mrifqidata-code.github.io/Google-Maps/` (aktif setelah setup di bawah).

Dashboard menampilkan:

- ringkasan: rata-rata rating tertimbang, total ulasan, ulasan baru, ulasan bintang 1–3, cabang yang gagal diambil;
- tren rating / jumlah ulasan per hari (cabang terpilih dibandingkan cabang lain);
- tabel per cabang: rating, perubahan rating, ulasan baru dalam periode, status buka/tutup;
- daftar ulasan yang tercatat, bisa difilter per cabang, periode, dan bintang.

## Setup (sekali saja)

1. **Buat API key Google Maps**
   1. Buka [Google Cloud Console](https://console.cloud.google.com/), buat atau pilih project, dan aktifkan billing.
   2. Aktifkan **Places API (New)** di *APIs & Services → Library*.
   3. Buat API key di *APIs & Services → Credentials*. Batasi key itu (*API restrictions*) hanya untuk
      **Places API (New)**.
2. **Simpan API key di GitHub:** *Settings → Secrets and variables → Actions → New repository secret*,
   nama `GOOGLE_MAPS_API_KEY`, isi dengan API key tadi.
3. **Aktifkan GitHub Pages:** *Settings → Pages → Build and deployment → Source:* pilih **GitHub Actions**.
4. **Pastikan kode ada di default branch** (`main`). Jadwal otomatis GitHub Actions hanya berjalan di default branch.
5. **Cari semua cabang:** tab *Actions → Kelola cabang → Run workflow*, pilih aksi `discover`.
   Log-nya menampilkan cabang yang ditemukan (`BARU`) dan tempat yang diabaikan karena namanya tidak mengandung
   "Sparks Swim". Setelah selesai, workflow ini otomatis menjalankan *Monitor review* untuk mengambil data pertama.
6. Buka dashboard di URL GitHub Pages di atas.

## Mengelola daftar cabang

Daftar cabang ada di [`config/centers.json`](config/centers.json):

```json
{
  "place_id": "ChIJ...",
  "name": "Sparks Swim Bintaro",
  "label": "Bintaro",
  "address": "...",
  "maps_url": "https://maps.google.com/?cid=...",
  "enabled": true,
  "source": "discover",
  "added_at": "2026-10-13"
}
```

- **Tambah cabang dari link Google Maps:** *Actions → Kelola cabang → Run workflow*, pilih aksi `add`, lalu tempel
  satu atau beberapa link (pisahkan dengan spasi). Link pendek `maps.app.goo.gl/...`, link
  `google.com/maps/place/...`, dan place ID semuanya didukung.
- **Hasil pencarian salah** (bukan cabang Sparks Swim): ubah `"enabled": true` menjadi `false`. Cabang itu tidak
  akan ditambahkan ulang oleh pencarian berikutnya.
- **Ganti nama tampilan:** tambahkan `"label": "Nama pendek"`.
- **Ubah kata kunci pencarian:** edit `search.queries` (bisa lebih dari satu) dan `search.name_filter`.

## Cara kerja

```
GitHub Actions (harian)
  └─ python3 -m monitor fetch
       ├─ Place Details (New) per cabang → rating, jumlah ulasan, maks. 5 ulasan
       └─ tulis docs/data/{summary,history,reviews}.json → commit ke repo
  └─ deploy folder docs/ ke GitHub Pages
```

| File | Isi |
|---|---|
| `docs/data/summary.json` | kondisi terbaru tiap cabang (rating, jumlah ulasan, status, error) |
| `docs/data/history.json` | satu titik per hari per cabang: rating dan jumlah ulasan |
| `docs/data/reviews.json` | semua ulasan yang pernah tercatat, tanpa duplikat |

## Batasan yang perlu diketahui

- **Maksimal 5 ulasan per cabang per pengambilan.** Places API tidak memberikan seluruh ulasan, dan urutannya
  ditentukan Google (bukan selalu yang terbaru). Karena itu "ulasan baru" di dashboard dihitung dari **selisih
  total ulasan** di Google (selalu akurat), sedangkan daftar ulasan berisi ulasan yang *sempat tercatat* saja.
  Untuk mendapatkan semua ulasan dan bisa membalasnya, perlu akses pengelola Google Business Profile tiap cabang
  (Business Profile API).
- **Ketentuan Google Maps Platform** membatasi penyimpanan (caching) konten Places API. Yang secara eksplisit boleh
  disimpan tanpa batas hanya place ID. Menyimpan riwayat rating dan ulasan seperti di proyek ini berada di luar
  izin tersebut, jadi pertimbangkan risikonya dan baca
  [Service Specific Terms](https://cloud.google.com/maps-platform/terms/maps-service-terms) sebelum dipakai jangka
  panjang.
- **Repo dan dashboard bersifat publik** (termasuk nama pengulas, sama seperti yang tampil di Google Maps).
- **Biaya:** setiap cabang = 1 panggilan Place Details per hari (SKU *Place Details Enterprise + Atmosphere*,
  karena meminta ulasan), ditambah beberapa panggilan Text Search per minggu. Google memberikan kuota gratis
  bulanan per SKU. Cek angkanya di [halaman harga](https://developers.google.com/maps/billing-and-pricing/pricing)
  dan pasang *budget alert* di Google Cloud.

## Menjalankan secara lokal

Tidak butuh dependency selain Python 3.9+.

```bash
export GOOGLE_MAPS_API_KEY=...
python3 -m monitor discover --dry-run   # lihat hasil pencarian tanpa mengubah config
python3 -m monitor discover             # simpan cabang yang cocok ke config/centers.json
python3 -m monitor add https://maps.app.goo.gl/xxxx
python3 -m monitor fetch                # ambil data ke docs/data/

python3 -m http.server -d docs 8000     # buka http://localhost:8000
python3 -m unittest discover -s tests -t .
```
