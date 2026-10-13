"""Perintah: discover (cari cabang), add (tambah dari link), fetch (ambil rating & review)."""

import argparse
import os
import re
from pathlib import Path

from monitor import store
from monitor.links import LinkError, resolve
from monitor.places import PlacesClient, PlacesError


def default_client_factory(search):
    return PlacesClient(
        os.environ.get("GOOGLE_MAPS_API_KEY", ""),
        language_code=search.get("language_code", "id"),
        region_code=search.get("region_code", "ID"),
    )


def warn(message):
    # Format "::warning::" muncul sebagai anotasi kuning di ringkasan GitHub Actions.
    print(f"::warning::{message}")


def load_config(path):
    config = store.load_json(path, None)
    if config is None:
        config = {"search": dict(store.DEFAULT_CONFIG["search"]), "centers": []}
    config.setdefault("search", dict(store.DEFAULT_CONFIG["search"]))
    config.setdefault("centers", [])
    return config


def cmd_discover(args, client_factory):
    config = load_config(args.config)
    search = config["search"]
    client = client_factory(search)
    today = store.wib_date(store.now_utc())

    found = {}
    for query in search["queries"]:
        for place in client.search_text(query):
            found.setdefault(place["id"], place)

    matched, ignored = [], []
    for place in found.values():
        bucket = matched if store.name_matches(store.display_name(place), search["name_filter"]) else ignored
        bucket.append(place)

    added = [place for place in matched if store.upsert_center(config, place, "discover", today)]

    print(f"Ditemukan {len(found)} tempat, {len(matched)} cocok dengan '{search['name_filter']}'.")
    for place in matched:
        mark = "BARU " if place in added else "ada  "
        status = place.get("businessStatus", "")
        print(f"  [{mark}] {store.display_name(place)} | {place.get('formattedAddress', '')} | {status}")
    if ignored:
        print("Tidak cocok dengan filter nama (diabaikan):")
        for place in ignored:
            print(f"  - {store.display_name(place)} | {place.get('formattedAddress', '')}")

    if args.dry_run:
        print("Dry run: config tidak diubah.")
    else:
        store.save_json(args.config, config)
        print(f"{len(added)} cabang baru ditambahkan ke {args.config}.")
    return 0


def cmd_add(args, client_factory):
    config = load_config(args.config)
    search = config["search"]
    client = client_factory(search)
    today = store.wib_date(store.now_utc())

    # Input workflow GitHub berupa satu baris, jadi link boleh dipisah spasi, koma, atau baris baru.
    values = [value for raw in args.links for value in re.split(r"[\s,]+", raw) if value]
    failures = 0
    for value in values:
        try:
            place = resolve(value, client)
        except (LinkError, PlacesError, OSError) as error:
            failures += 1
            warn(f"Gagal memproses {value}: {error}")
            continue
        name = store.display_name(place)
        if not store.name_matches(name, search["name_filter"]):
            warn(f"'{name}' tidak mengandung '{search['name_filter']}', tetap ditambahkan karena diminta manual.")
        if store.upsert_center(config, place, "link", today):
            print(f"Ditambahkan: {name} ({place['id']})")
        else:
            print(f"Sudah ada: {name} ({place['id']})")

    store.save_json(args.config, config)
    return 1 if values and failures == len(values) else 0


def cmd_fetch(args, client_factory):
    config = load_config(args.config)
    data_dir = Path(args.data_dir)
    summary_path = data_dir / "summary.json"
    history_path = data_dir / "history.json"
    reviews_path = data_dir / "reviews.json"

    previous = {c["place_id"]: c for c in store.load_json(summary_path, {"centers": []})["centers"]}
    history = store.load_json(history_path, {})
    reviews = store.load_json(reviews_path, [])

    now = store.now_utc()
    now_iso = store.iso(now)
    today = store.wib_date(now)

    enabled = [center for center in config["centers"] if center.get("enabled", True)]
    if not enabled:
        warn("Belum ada cabang aktif di config/centers.json. Jalankan workflow 'Kelola cabang' dulu.")

    client = client_factory(config["search"]) if enabled else None
    rows, failures, new_reviews = [], 0, 0
    for center in enabled:
        place_id = center["place_id"]
        label = center.get("label") or center["name"]
        try:
            details = client.place_details(place_id)
        except PlacesError as error:
            failures += 1
            warn(f"Gagal mengambil data {label}: {error}")
            row = dict(previous.get(place_id, {}))
            row.update({"place_id": place_id, "name": label, "error": str(error)})
            row.setdefault("address", center.get("address", ""))
            row.setdefault("maps_url", center.get("maps_url", ""))
            rows.append(row)
            continue

        new_id = details.get("id") or place_id
        if new_id != place_id:
            print(f"Place ID {label} berubah: {place_id} -> {new_id}")
            store.rename_place(place_id, new_id, config, history, reviews)
            place_id = new_id

        center["name"] = store.display_name(details) or center["name"]
        center["address"] = details.get("formattedAddress", center.get("address", ""))
        center["maps_url"] = details.get("googleMapsUri", center.get("maps_url", ""))

        rating = details.get("rating")
        count = details.get("userRatingCount", 0)
        store.record_history(history, place_id, today, rating, count)
        added = store.merge_reviews(reviews, place_id, details.get("reviews", []), now_iso)
        new_reviews += added
        rows.append(
            {
                "place_id": place_id,
                "name": center.get("label") or center["name"],
                "address": center["address"],
                "maps_url": center["maps_url"],
                "business_status": details.get("businessStatus", ""),
                "rating": rating,
                "user_rating_count": count,
                "last_fetched": now_iso,
                "error": None,
            }
        )
        print(f"{label}: rating {rating}, {count} ulasan, {added} review baru tercatat")

    store.save_json(args.config, config)
    store.save_json(summary_path, {"updated_at": now_iso, "date": today, "centers": rows})
    store.save_json(history_path, history)
    store.save_json(reviews_path, reviews)
    print(f"Selesai: {len(enabled) - failures}/{len(enabled)} cabang berhasil, {new_reviews} review baru.")

    # Semua gagal biasanya berarti API key/billing bermasalah, jadi workflow dibuat merah.
    return 1 if enabled and failures == len(enabled) else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m monitor", description=__doc__)
    parser.add_argument("--config", default=str(store.CONFIG_PATH), help="file daftar cabang")
    parser.add_argument("--data-dir", default=str(store.DATA_DIR), help="folder data dashboard")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="cari semua cabang lewat Text Search")
    discover.add_argument("--dry-run", action="store_true", help="tampilkan hasil tanpa mengubah config")
    discover.set_defaults(func=cmd_discover)

    add = sub.add_parser("add", help="tambah cabang dari link Google Maps atau place ID")
    add.add_argument("links", nargs="+")
    add.set_defaults(func=cmd_add)

    fetch = sub.add_parser("fetch", help="ambil rating, jumlah ulasan, dan review terbaru")
    fetch.set_defaults(func=cmd_fetch)
    return parser


def main(argv=None, client_factory=default_client_factory):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, client_factory)
    except (PlacesError, ValueError) as error:
        print(f"::error::{error}")
        return 1
