import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from monitor import store
from monitor.cli import main
from monitor.serpapi import SerpApiError


def place(place_id, name, data_id="", status=""):
    return {
        "place_id": place_id,
        "data_id": data_id,
        "name": name,
        "address": f"Alamat {name}",
        "maps_url": f"https://www.google.com/maps/place/?q=place_id:{place_id}",
        "rating": 4.5,
        "count": 10,
        "status": status,
    }


def review(review_id, rating=5, text="Bagus", iso_date="2026-10-10T03:00:00Z", response=None):
    item = {
        "review_id": review_id,
        "link": f"https://www.google.com/maps/reviews/{review_id}",
        "rating": rating,
        "date": "seminggu lalu",
        "iso_date": iso_date,
        "snippet": text,
        "extracted_snippet": {"original": text, "translated": text},
        "user": {"name": f"Penulis {review_id}", "link": f"https://www.google.com/maps/contrib/{review_id}"},
    }
    if response:
        item["response"] = {"iso_date": "2026-10-11T00:00:00Z", "snippet": response, "extracted_snippet": {"original": response}}
    return item


class FakeClient:
    def __init__(self, search_pages=None, places=None, account=None, failing=(), account_error=None):
        self.search_pages = search_pages or {}
        self.places = places or {}
        self.account_info = account or {"searches_per_month": 250, "total_searches_left": 200, "this_month_usage": 50}
        self.failing = set(failing)
        self.account_error = account_error
        self.search_calls = []
        self.review_calls = []

    def maps_search(self, query, ll=None, start=0):
        self.search_calls.append((query, ll, start))
        return self.search_pages.get(start, [])

    def account(self):
        if self.account_error:
            raise self.account_error
        return self.account_info

    def reviews(self, place_id, next_page_token=None):
        self.review_calls.append((place_id, next_page_token))
        if place_id in self.failing:
            raise SerpApiError(404, "Not found")
        entry = self.places[place_id]
        index = int(next_page_token or 0)
        pages = entry.get("pages", [[]])
        return {
            "place_info": entry["info"],
            "reviews": pages[index] if index < len(pages) else [],
            "next_page_token": str(index + 1) if index + 1 < len(pages) else None,
        }


def info(name, rating=4.7, count=120):
    return {"title": name, "address": f"Alamat {name}", "rating": rating, "reviews": count}


class CliTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config_path = Path(self.tmp.name) / "centers.json"
        self.data_dir = Path(self.tmp.name) / "data"
        store.save_json(self.config_path, store.DEFAULT_CONFIG)

    def run_cli(self, client, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(
                ["--config", str(self.config_path), "--data-dir", str(self.data_dir), *argv],
                client_factory=lambda search: client,
            )
        return code, output.getvalue()

    def config(self):
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def data(self, name):
        return json.loads((self.data_dir / name).read_text(encoding="utf-8"))

    def add_centers(self, *places):
        config = self.config()
        for p in places:
            store.upsert_center(config, p, "manual", "2026-10-01")
        store.save_json(self.config_path, config)


class DiscoverTest(CliTestCase):
    def test_adds_only_matching_names(self):
        client = FakeClient(
            search_pages={
                0: [
                    place("p1", "Sparks Swim Bintaro"),
                    place("p2", "SPARKS SWIM - Kelapa Gading"),
                    place("p3", "Spark Gym Bintaro"),
                    place("p4", "Sparks Swim Lama", status="Tutup permanen"),
                ]
            }
        )
        code, output = self.run_cli(client, "discover")
        self.assertEqual(code, 0)
        centers = {c["place_id"]: c for c in self.config()["centers"]}
        self.assertEqual(set(centers), {"p1", "p2", "p4"})
        self.assertTrue(centers["p1"]["enabled"])
        self.assertFalse(centers["p4"]["enabled"])
        self.assertIn("Spark Gym Bintaro", output)
        # Satu panggilan per query di config default.
        self.assertEqual(len(client.search_calls), len(store.DEFAULT_CONFIG["search"]["queries"]))

    def test_paginates_only_when_page_is_full_of_matches(self):
        full_page = [place(f"a{i}", f"Sparks Swim {i}") for i in range(20)]
        client = FakeClient(search_pages={0: full_page, 20: [place("b1", "Sparks Swim Extra")]})
        self.run_cli(client, "discover")
        self.assertIn(("Sparks Swim", "@-6.25,106.8,10z", 20), client.search_calls)
        self.assertEqual(len(self.config()["centers"]), 21)

    def test_keeps_manual_edits_on_rerun(self):
        client = FakeClient(search_pages={0: [place("p1", "Sparks Swim Bintaro")]})
        self.run_cli(client, "discover")
        config = self.config()
        config["centers"][0]["enabled"] = False
        store.save_json(self.config_path, config)
        self.run_cli(client, "discover")
        self.assertEqual(len(self.config()["centers"]), 1)
        self.assertFalse(self.config()["centers"][0]["enabled"])

    def test_center_added_by_data_id_is_not_duplicated(self):
        self.add_centers(place("0xa:0xb", "Sparks Swim BSD", data_id="0xa:0xb"))
        self.run_cli(FakeClient(search_pages={0: [place("ChIJbsd", "Sparks Swim BSD", data_id="0xa:0xb")]}), "discover")
        self.assertEqual([c["place_id"] for c in self.config()["centers"]], ["0xa:0xb"])

    def test_dry_run_does_not_write(self):
        self.run_cli(FakeClient(search_pages={0: [place("p1", "Sparks Swim Bintaro")]}), "discover", "--dry-run")
        self.assertEqual(self.config()["centers"], [])


class AddTest(CliTestCase):
    def test_adds_ids_without_using_quota(self):
        client = FakeClient()
        code, _ = self.run_cli(client, "add", f"{'A' * 27}, 0x1a:0x2b")
        self.assertEqual(code, 0)
        centers = self.config()["centers"]
        self.assertEqual([c["place_id"] for c in centers], ["A" * 27, "0x1a:0x2b"])
        self.assertEqual(centers[1]["data_id"], "0x1a:0x2b")
        self.assertEqual(client.search_calls, [])

    def test_all_invalid_inputs_fail(self):
        code, output = self.run_cli(FakeClient(), "add", "bukan-link")
        self.assertEqual(code, 1)
        self.assertIn("::warning::", output)


class FetchTest(CliTestCase):
    def test_records_summary_history_reviews_and_owner_reply(self):
        self.add_centers(place("p1", "Sparks Swim Bintaro"))
        client = FakeClient(
            places={
                "p1": {
                    "info": info("Sparks Swim Bintaro", 4.7, 120),
                    "pages": [[
                        review("r2", 2, "Kolamnya kurang bersih", "2026-10-12T03:00:00Z", response="Terima kasih, akan kami perbaiki"),
                        review("r1", 5, "Pelatihnya sabar", "2026-10-10T03:00:00Z"),
                    ]],
                }
            }
        )
        code, _ = self.run_cli(client, "fetch")
        self.assertEqual(code, 0)

        row = self.data("summary.json")["centers"][0]
        self.assertEqual((row["rating"], row["user_rating_count"], row["error"]), (4.7, 120, None))
        self.assertEqual(self.data("history.json")["p1"][0]["count"], 120)
        reviews = self.data("reviews.json")
        self.assertEqual([r["text"] for r in reviews], ["Kolamnya kurang bersih", "Pelatihnya sabar"])
        self.assertEqual(reviews[0]["response_text"], "Terima kasih, akan kami perbaiki")
        self.assertEqual(reviews[1]["response_text"], "")

        # Fetch kedua di hari yang sama tidak menduplikasi ulasan maupun titik riwayat.
        client.places["p1"]["info"] = info("Sparks Swim Bintaro", 4.7, 121)
        self.run_cli(client, "fetch")
        self.assertEqual(len(self.data("reviews.json")), 2)
        history = self.data("history.json")["p1"]
        self.assertEqual([p["count"] for p in history], [121])

    def test_rotates_centers_within_daily_budget(self):
        ids = [f"p{i:02d}" for i in range(10)]
        self.add_centers(*[place(pid, f"Sparks Swim {pid}") for pid in ids])
        client = FakeClient(places={pid: {"info": info(pid)} for pid in ids})

        code, output = self.run_cli(client, "fetch")
        self.assertEqual(code, 0)
        # (250 - 20 cadangan) // 31 hari = 7 request per hari.
        first_batch = [call[0] for call in client.review_calls]
        self.assertEqual(len(first_batch), 7)
        self.assertIn("3 cabang menunggu giliran", output)
        summary = {row["place_id"]: row for row in self.data("summary.json")["centers"]}
        self.assertEqual(len(summary), 10)
        waiting = set(ids) - set(first_batch)
        self.assertTrue(all(summary[pid]["last_fetched"] is None for pid in waiting))

        client.review_calls.clear()
        self.run_cli(client, "fetch")
        second_batch = [call[0] for call in client.review_calls]
        self.assertEqual(set(second_batch[:3]), waiting)

    def test_budget_never_exceeds_searches_left(self):
        ids = ["p1", "p2", "p3"]
        self.add_centers(*[place(pid, f"Sparks Swim {pid}") for pid in ids])
        client = FakeClient(places={pid: {"info": info(pid)} for pid in ids}, account={"searches_per_month": 250, "total_searches_left": 2})
        self.run_cli(client, "fetch")
        self.assertEqual(len(client.review_calls), 2)

    def test_exhausted_quota_skips_fetch(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        client = FakeClient(places={"p1": {"info": info("A")}}, account={"searches_per_month": 250, "total_searches_left": 0})
        code, output = self.run_cli(client, "fetch")
        self.assertEqual(code, 0)
        self.assertEqual(client.review_calls, [])
        self.assertIn("sudah habis", output)

    def test_invalid_key_stops_immediately(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        client = FakeClient(account_error=SerpApiError(401, "Invalid API key."))
        code, output = self.run_cli(client, "fetch")
        self.assertEqual(code, 1)
        self.assertIn("::error::", output)
        self.assertEqual(client.review_calls, [])

    def test_follows_pages_until_known_review(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        client = FakeClient(places={"p1": {"info": info("A"), "pages": [[review("old1"), review("old2")]]}})
        self.run_cli(client, "fetch")  # fetch pertama: hanya halaman 1

        client.places["p1"]["pages"] = [
            [review(f"new{i}") for i in range(8)],
            [review("new8"), review("old1")],
            [review("older")],
        ]
        client.review_calls.clear()
        self.run_cli(client, "fetch")
        self.assertEqual(client.review_calls, [("p1", None), ("p1", "1")])
        self.assertEqual(len(self.data("reviews.json")), 11)

    def test_first_fetch_reads_only_first_page(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        client = FakeClient(places={"p1": {"info": info("A"), "pages": [[review("a")], [review("b")]]}})
        self.run_cli(client, "fetch")
        self.assertEqual(client.review_calls, [("p1", None)])

    def test_data_id_is_used_when_known(self):
        self.add_centers(place("0xa:0xb", "Sparks Swim A", data_id="0xa:0xb"))
        client = FakeClient(places={"0xa:0xb": {"info": info("Sparks Swim A")}})
        self.run_cli(client, "fetch")
        self.assertEqual(client.review_calls, [("0xa:0xb", None)])

    def test_partial_failure_keeps_previous_numbers(self):
        self.add_centers(place("p1", "Sparks Swim A"), place("p2", "Sparks Swim B"))
        places = {pid: {"info": info(pid, 4.5, 10)} for pid in ("p1", "p2")}
        self.run_cli(FakeClient(places=places), "fetch")

        code, output = self.run_cli(FakeClient(places=places, failing={"p2"}), "fetch")
        self.assertEqual(code, 0)
        self.assertIn("::warning::", output)
        rows = {row["place_id"]: row for row in self.data("summary.json")["centers"]}
        self.assertIsNone(rows["p1"]["error"])
        self.assertEqual(rows["p2"]["rating"], 4.5)
        self.assertIn("404", rows["p2"]["error"])

    def test_all_failures_exit_non_zero(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        code, _ = self.run_cli(FakeClient(failing={"p1"}), "fetch")
        self.assertEqual(code, 1)

    def test_disabled_centers_are_skipped(self):
        self.add_centers(place("p1", "Sparks Swim A"))
        config = self.config()
        config["centers"][0]["enabled"] = False
        store.save_json(self.config_path, config)
        code, _ = self.run_cli(FakeClient(failing={"p1"}), "fetch")
        self.assertEqual(code, 0)
        self.assertEqual(self.data("summary.json")["centers"], [])


if __name__ == "__main__":
    unittest.main()
