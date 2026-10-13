"""Perintah: discover (cari cabang), add (tambah dari link), fetch (ambil rating & ulasan)."""

import argparse
import os
import re
from pathlib import Path

from monitor import store
from monitor.links import LinkError, resolve
from monitor.serpapi import SerpApiClient, SerpApiError

# Satu cabang paling banyak memakai sekian request per fetch saat mengejar ulasan yang tertinggal.
MAX_PAGES_PER_CENTER = 3


def default_client_factory(search):
    return SerpApiClient(
        os.environ.get("SERPAPI_API_KEY", ""),
        hl=search.get("hl", "id"),
        gl=search.get("gl", "id"),
    )


def warn(message):
    # Format "::warning::" muncul sebagai anotasi kuning di ringkasan GitHub Actions.
    print(f"::warning::{message}")


def load_config(path):
    config = store.load_json(path, None) or {}
    for key in ("search", "quota"):
        merged = dict(store.DEFAULT_CONFIG[key])
        merged.update(config.get(key) or {})
        config[key] = merged
    config.setdefault("centers", [])
    return config


def cmd_discover(args, client_factory):
    config = load_config(args.config)
    search = config["search"]
    client = client_factory(search)
    today = store.wib_date(store.now_utc())

    found = {}
    for query in search["queries"]:
        if isinstance(query, str):
            query = {"q": query}
        start = 0
        while True:
            page = client.maps_search(query["q"], ll=query.get("ll"), start=start)
            for place in page:
                found.setdefault(place["place_id"], place)
            # Halaman berikutnya hanya kalau halaman ini penuh dan hasil terakhirnya masih relevan.
            if len(page) < 20 or not store.name_matches(page[-1]["name"], search["name_filter"]) or start >= 40:
                break
            start += 20

    matched, ignored = [], []
    for place in found.values():
        (matched if store.name_matches(place["name"], search["name_filter"]) else ignored).append(place)

    added = [place for place in matched if store.upsert_center(config, place, "discover", today)]

    print(f"Ditemukan {len(found)} tempat, {len(matched)} cocok dengan '{search['name_filter']}'.")
    for place in matched:
        mark = "BARU" if place in added else "ada "
        print(f"  [{mark}] {place['name']} | {place['address']} | {place['status']}")
    if ignored:
        print("Tidak cocok dengan filter nama (diabaikan):")
        for place in ignored:
            print(f"  - {place['name']} | {place['address']}")

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
        except (LinkError, SerpApiError, OSError) as error:
            failures += 1
            warn(f"Gagal memproses {value}: {error}")
            continue
        name = place["name"] or "(nama terisi saat fetch pertama)"
        if place["name"] and not store.name_matches(place["name"], search["name_filter"]):
            warn(f"'{place['name']}' tidak mengandung '{search['name_filter']}', tetap ditambahkan karena diminta manual.")
        if store.upsert_center(config, place, "link", today):
            print(f"Ditambahkan: {name} ({place['place_id']})")
        else:
            print(f"Sudah ada: {name} ({place['place_id']})")

    store.save_json(args.config, config)
    return 1 if values and failures == len(values) else 0


def daily_budget(quota, client):
    """Berapa request SerpApi yang boleh dipakai fetch hari ini."""
    monthly = quota["monthly_searches"]
    left = None
    try:
        account = client.account()
        monthly = account.get("searches_per_month") or monthly
        left = account.get("total_searches_left", account.get("plan_searches_left"))
        print(f"Kuota SerpApi: {left} tersisa dari {monthly}/bulan (terpakai bulan ini: {account.get('this_month_usage')}).")
    except SerpApiError as error:
        if error.status in (401, 403):
            raise
        warn(f"Tidak bisa membaca info akun SerpApi ({error}); memakai angka kuota dari config.")
    budget = max(1, (monthly - quota["reserved_searches"]) // 31)
    if left is not None:
        budget = min(budget, max(0, left))
        if budget == 0:
            warn("Kuota SerpApi bulan ini sudah habis; data akan diperbarui lagi setelah kuota direset.")
    return budget


def fetch_center(client, center, reviews, budget_left, now_iso):
    """Ambil ulasan terbaru satu cabang. Return (place_info, jumlah ulasan baru, request terpakai)."""
    place_id = center["place_id"]
    known = {review["id"] for review in reviews if review["place_id"] == place_id}
    token, place_info, added, used = None, {}, 0, 0
    while True:
        try:
            page = client.reviews(center.get("data_id") or place_id, next_page_token=token)
        except SerpApiError as error:
            if not used:
                raise
            # Halaman pertama sudah berhasil; simpan yang sudah didapat dan lanjutkan di giliran berikutnya.
            warn(f"{center['name']}: halaman ulasan berikutnya gagal diambil ({error}).")
            return place_info, added, used + 1
        used += 1
        place_info = place_info or page["place_info"]
        keys = [store.review_key(item) for item in page["reviews"]]
        added += store.merge_reviews(reviews, place_id, page["reviews"], now_iso)
        token = page["next_page_token"]
        # Lanjut ke halaman berikutnya hanya kalau semua ulasan di halaman ini belum pernah tercatat,
        # artinya mungkin masih ada ulasan baru yang tertinggal. Fetch pertama cukup halaman pertama.
        caught_up = not keys or any(key in known for key in keys)
        if caught_up or not known or not token:
            return place_info, added, used
        if used >= MAX_PAGES_PER_CENTER or used >= budget_left:
            warn(f"{center['name']}: masih ada ulasan baru yang belum terambil; dilanjutkan di giliran berikutnya.")
            return place_info, added, used


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

    rows = {}
    attempted, failures, new_reviews, used = 0, 0, 0, 0
    if enabled:
        client = client_factory(config["search"])
        budget = daily_budget(config["quota"], client)
        # Giliran: cabang yang paling lama tidak dicek (atau belum pernah) didahulukan.
        queue = sorted(enabled, key=lambda c: previous.get(c["place_id"], {}).get("last_fetched") or "")
        for center in queue:
            if used >= budget:
                break
            place_id = center["place_id"]
            label = center.get("label") or center["name"] or place_id
            attempted += 1
            try:
                info, added, spent = fetch_center(client, center, reviews, budget - used, now_iso)
            except SerpApiError as error:
                used += 1
                failures += 1
                warn(f"Gagal mengambil data {label}: {error}")
                row = dict(previous.get(place_id, {}))
                row["error"] = str(error)
                rows[place_id] = row
                continue
            used += spent
            new_reviews += added

            center["name"] = info.get("title") or center["name"]
            center["address"] = info.get("address") or center.get("address", "")
            rating = info.get("rating")
            count = info.get("reviews")
            if count is not None:
                store.record_history(history, place_id, today, rating, count)
            rows[place_id] = {
                "rating": rating,
                "user_rating_count": count,
                "last_fetched": now_iso,
                "error": None,
            }
            print(f"{label}: rating {rating}, {count} ulasan, {added} ulasan baru tercatat ({spent} request)")

    # Cabang yang belum dapat giliran hari ini tetap tampil dengan angka terakhirnya.
    summary_rows = []
    for center in enabled:
        place_id = center["place_id"]
        row = {"rating": None, "user_rating_count": None, "last_fetched": None, "error": None}
        row.update(previous.get(place_id, {}))
        row.update(rows.get(place_id, {}))
        row.update(
            {
                "place_id": place_id,
                "name": center.get("label") or center["name"] or place_id,
                "address": center.get("address", ""),
                "maps_url": center.get("maps_url", ""),
            }
        )
        summary_rows.append(row)

    store.save_json(args.config, config)
    store.save_json(summary_path, {"updated_at": now_iso, "date": today, "centers": summary_rows})
    store.save_json(history_path, history)
    store.save_json(reviews_path, reviews)
    waiting = len(enabled) - attempted
    print(
        f"Selesai: {attempted - failures}/{attempted} cabang berhasil dicek, {new_reviews} ulasan baru, "
        f"{used} request terpakai, {waiting} cabang menunggu giliran berikutnya."
    )

    # Semua gagal biasanya berarti API key/kuota bermasalah, jadi workflow dibuat merah.
    return 1 if attempted and failures == attempted else 0


def build_parser():
    parser = argparse.ArgumentParser(prog="python -m monitor", description=__doc__)
    parser.add_argument("--config", default=str(store.CONFIG_PATH), help="file daftar cabang")
    parser.add_argument("--data-dir", default=str(store.DATA_DIR), help="folder data dashboard")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="cari semua cabang lewat Google Maps search")
    discover.add_argument("--dry-run", action="store_true", help="tampilkan hasil tanpa mengubah config")
    discover.set_defaults(func=cmd_discover)

    add = sub.add_parser("add", help="tambah cabang dari link Google Maps, place ID, atau data ID")
    add.add_argument("links", nargs="+")
    add.set_defaults(func=cmd_add)

    fetch = sub.add_parser("fetch", help="ambil rating, jumlah ulasan, dan ulasan terbaru (bergiliran sesuai kuota)")
    fetch.set_defaults(func=cmd_fetch)
    return parser


def main(argv=None, client_factory=default_client_factory):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args, client_factory)
    except (SerpApiError, ValueError) as error:
        print(f"::error::{error}")
        return 1
