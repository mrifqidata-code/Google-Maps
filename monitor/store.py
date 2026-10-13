"""Baca/tulis file konfigurasi dan data JSON yang dipakai dashboard."""

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "centers.json"
DATA_DIR = ROOT / "docs" / "data"

# Tanggal riwayat dicatat dalam WIB supaya satu hari = satu titik di grafik.
WIB = timezone(timedelta(hours=7), "WIB")

DEFAULT_CONFIG = {
    "search": {
        # "ll" = titik tengah peta + zoom, format "@lat,lng,zoomz". Tiap query = 1 kuota SerpApi per halaman.
        "queries": [
            {"q": "Sparks Swim", "ll": "@-6.25,106.8,10z"},
            {"q": "Sparks Swim Indonesia", "ll": "@-2.5,118,5z"},
        ],
        "name_filter": "Sparks Swim",
        "hl": "id",
        "gl": "id",
    },
    "quota": {
        # Kuota bulanan paket SerpApi (paket gratis: 250). Kalau akun bisa dibaca, angka dari akun yang dipakai.
        "monthly_searches": 250,
        # Disisihkan untuk discover/add supaya fetch harian tidak menghabiskan semuanya.
        "reserved_searches": 20,
    },
    "centers": [],
}


def load_json(path, default):
    path = Path(path)
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def normalize(text):
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def name_matches(name, name_filter):
    return normalize(name_filter) in normalize(name)


def find_center(config, place):
    ids = {place.get("place_id"), place.get("data_id")} - {None, ""}
    for center in config["centers"]:
        if ids & ({center.get("place_id"), center.get("data_id")} - {None, ""}):
            return center
    return None


def permanently_closed(place):
    return bool(re.search(r"permanen", place.get("status") or "", re.IGNORECASE))


def upsert_center(config, place, source, today):
    """Tambahkan cabang baru ke config. Return True kalau cabang belum ada sebelumnya."""
    existing = find_center(config, place)
    if existing:
        # Lengkapi data ID yang belum tercatat tanpa mengubah kunci riwayat (place_id).
        if place.get("data_id") and not existing.get("data_id"):
            existing["data_id"] = place["data_id"]
        return False
    config["centers"].append(
        {
            "place_id": place["place_id"],
            "data_id": place.get("data_id", ""),
            "name": place.get("name", ""),
            "address": place.get("address", ""),
            "maps_url": place.get("maps_url", ""),
            # Cabang yang sudah tutup permanen tidak ikut dimonitor kecuali diaktifkan manual.
            "enabled": not permanently_closed(place),
            "source": source,
            "added_at": today,
        }
    )
    return True


def review_key(review):
    if review.get("review_id"):
        return review["review_id"]
    if review.get("link"):
        return review["link"]
    author = (review.get("user") or {}).get("link", "")
    return f"{author}|{review.get('iso_date', '')}"


def merge_reviews(reviews, place_id, fetched, now_iso):
    """Gabungkan review hasil fetch ke daftar tersimpan. Return jumlah review baru."""
    by_key = {review["id"]: review for review in reviews}
    added = 0
    for item in fetched:
        key = review_key(item)
        user = item.get("user") or {}
        snippet = item.get("extracted_snippet") or {}
        response = item.get("response") or {}
        response_snippet = response.get("extracted_snippet") or {}
        record = {
            "id": key,
            "place_id": place_id,
            "rating": item.get("rating"),
            # "translated" mengikuti bahasa hl=id; "snippet" bisa campuran teks asli & terjemahan.
            "text": snippet.get("translated") or item.get("snippet") or snippet.get("original") or "",
            "original_text": snippet.get("original", ""),
            "author": user.get("name", ""),
            "author_uri": user.get("link", ""),
            "author_photo": user.get("thumbnail", ""),
            "publish_time": item.get("iso_date", ""),
            "edited_time": item.get("iso_date_of_last_edit", ""),
            "relative_time": item.get("date", ""),
            "maps_uri": item.get("link", ""),
            "response_text": response_snippet.get("original") or response.get("snippet") or "",
            "response_time": response.get("iso_date", ""),
            "last_seen": now_iso,
        }
        if key in by_key:
            record["first_seen"] = by_key[key].get("first_seen", now_iso)
            by_key[key].update(record)
        else:
            record["first_seen"] = now_iso
            by_key[key] = record
            reviews.append(record)
            added += 1
    reviews.sort(key=lambda review: review.get("publish_time", ""), reverse=True)
    return added


def record_history(history, place_id, date, rating, count):
    """Simpan satu titik per hari per cabang; fetch ulang di hari yang sama menimpa titik itu."""
    points = history.setdefault(place_id, [])
    point = {"date": date, "rating": rating, "count": count}
    if points and points[-1]["date"] == date:
        points[-1] = point
    else:
        points.append(point)
        points.sort(key=lambda p: p["date"])


def now_utc():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def wib_date(moment):
    return moment.astimezone(WIB).date().isoformat()
