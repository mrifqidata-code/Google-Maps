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
        "queries": ["Sparks Swim"],
        "name_filter": "Sparks Swim",
        "language_code": "id",
        "region_code": "ID",
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


def display_name(place):
    return (place.get("displayName") or {}).get("text") or place.get("id", "")


def upsert_center(config, place, source, today):
    """Tambahkan cabang baru ke config. Return True kalau cabang belum ada sebelumnya."""
    for center in config["centers"]:
        if center["place_id"] == place["id"]:
            return False
    config["centers"].append(
        {
            "place_id": place["id"],
            "name": display_name(place),
            "address": place.get("formattedAddress", ""),
            "maps_url": place.get("googleMapsUri", ""),
            # Cabang yang sudah tutup permanen tidak ikut dimonitor kecuali diaktifkan manual.
            "enabled": place.get("businessStatus") != "CLOSED_PERMANENTLY",
            "source": source,
            "added_at": today,
        }
    )
    return True


def review_key(review):
    if review.get("name"):
        return review["name"]
    author = (review.get("authorAttribution") or {}).get("uri", "")
    return f"{author}|{review.get('publishTime', '')}"


def merge_reviews(reviews, place_id, fetched, now_iso):
    """Gabungkan review hasil fetch ke daftar tersimpan. Return jumlah review baru."""
    by_key = {review["id"]: review for review in reviews}
    added = 0
    for item in fetched:
        key = review_key(item)
        author = item.get("authorAttribution") or {}
        text = item.get("text") or {}
        original = item.get("originalText") or {}
        record = {
            "id": key,
            "place_id": place_id,
            "rating": item.get("rating"),
            "text": text.get("text", ""),
            "original_text": original.get("text", ""),
            "language": original.get("languageCode") or text.get("languageCode", ""),
            "author": author.get("displayName", ""),
            "author_uri": author.get("uri", ""),
            "author_photo": author.get("photoUri", ""),
            "publish_time": item.get("publishTime", ""),
            "relative_time": item.get("relativePublishTimeDescription", ""),
            "maps_uri": item.get("googleMapsUri", ""),
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


def rename_place(place_id, new_id, config, history, reviews):
    """Google kadang mengganti place ID. Pindahkan semua data ke ID baru."""
    for center in config["centers"]:
        if center["place_id"] == place_id:
            center["place_id"] = new_id
    if place_id in history:
        history.setdefault(new_id, [])
        history[new_id] = sorted(history.pop(place_id) + history[new_id], key=lambda p: p["date"])
    for review in reviews:
        if review["place_id"] == place_id:
            review["place_id"] = new_id


def now_utc():
    return datetime.now(timezone.utc)


def iso(moment):
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def wib_date(moment):
    return moment.astimezone(WIB).date().isoformat()
