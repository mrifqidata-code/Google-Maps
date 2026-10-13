import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from monitor import store
from monitor.cli import main
from monitor.places import PlacesError


def place(place_id, name, status="OPERATIONAL"):
    return {
        "id": place_id,
        "displayName": {"text": name, "languageCode": "id"},
        "formattedAddress": f"Alamat {name}",
        "googleMapsUri": f"https://maps.google.com/?cid={place_id}",
        "businessStatus": status,
    }


def review(review_id, rating, text, publish_time):
    return {
        "name": f"places/x/reviews/{review_id}",
        "rating": rating,
        "text": {"text": text, "languageCode": "id"},
        "originalText": {"text": text, "languageCode": "id"},
        "authorAttribution": {"displayName": f"Penulis {review_id}", "uri": f"https://maps.google.com/u/{review_id}"},
        "publishTime": publish_time,
        "relativePublishTimeDescription": "seminggu lalu",
    }


class FakeClient:
    def __init__(self, search_results=(), details=None, failing=()):
        self.search_results = list(search_results)
        self.details = details or {}
        self.failing = set(failing)

    def search_text(self, query, max_pages=3, location_bias=None):
        return self.search_results

    def place_details(self, place_id):
        if place_id in self.failing:
            raise PlacesError(404, "Not found")
        return self.details[place_id]


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


class DiscoverTest(CliTestCase):
    def test_adds_only_matching_names(self):
        client = FakeClient(
            [
                place("p1", "Sparks Swim Bintaro"),
                place("p2", "SPARKS SWIM - Kelapa Gading"),
                place("p3", "Spark Gym Bintaro"),
                place("p4", "Sparks Swim Lama", status="CLOSED_PERMANENTLY"),
            ]
        )
        code, output = self.run_cli(client, "discover")
        self.assertEqual(code, 0)
        centers = {c["place_id"]: c for c in self.config()["centers"]}
        self.assertEqual(set(centers), {"p1", "p2", "p4"})
        self.assertTrue(centers["p1"]["enabled"])
        self.assertFalse(centers["p4"]["enabled"])
        self.assertIn("Spark Gym Bintaro", output)

    def test_keeps_manual_edits_on_rerun(self):
        client = FakeClient([place("p1", "Sparks Swim Bintaro")])
        self.run_cli(client, "discover")
        config = self.config()
        config["centers"][0]["enabled"] = False
        store.save_json(self.config_path, config)
        self.run_cli(client, "discover")
        self.assertEqual(len(self.config()["centers"]), 1)
        self.assertFalse(self.config()["centers"][0]["enabled"])

    def test_dry_run_does_not_write(self):
        self.run_cli(FakeClient([place("p1", "Sparks Swim Bintaro")]), "discover", "--dry-run")
        self.assertEqual(self.config()["centers"], [])


class AddTest(CliTestCase):
    def test_adds_place_ids_split_by_spaces_and_commas(self):
        client = FakeClient(details={pid: place(pid, f"Sparks Swim {pid}") for pid in ("A" * 27, "B" * 27)})
        code, _ = self.run_cli(client, "add", f"{'A' * 27}, {'B' * 27}")
        self.assertEqual(code, 0)
        self.assertEqual([c["source"] for c in self.config()["centers"]], ["link", "link"])

    def test_all_invalid_inputs_fail(self):
        code, output = self.run_cli(FakeClient(), "add", "bukan-link")
        self.assertEqual(code, 1)
        self.assertIn("::warning::", output)


class FetchTest(CliTestCase):
    def add_centers(self, *places):
        config = self.config()
        for p in places:
            store.upsert_center(config, p, "manual", "2026-10-01")
        store.save_json(self.config_path, config)

    def test_records_summary_history_and_reviews(self):
        self.add_centers(place("p1", "Sparks Swim Bintaro"))
        details = dict(place("p1", "Sparks Swim Bintaro"), rating=4.7, userRatingCount=120)
        details["reviews"] = [
            review("r1", 5, "Pelatihnya sabar", "2026-10-10T03:00:00Z"),
            review("r2", 2, "Kolamnya kurang bersih", "2026-10-12T03:00:00Z"),
        ]
        code, _ = self.run_cli(FakeClient(details={"p1": details}), "fetch")
        self.assertEqual(code, 0)

        summary = self.data("summary.json")
        self.assertEqual(summary["centers"][0]["rating"], 4.7)
        self.assertEqual(summary["centers"][0]["user_rating_count"], 120)
        self.assertEqual(len(self.data("history.json")["p1"]), 1)
        reviews = self.data("reviews.json")
        self.assertEqual([r["text"] for r in reviews], ["Kolamnya kurang bersih", "Pelatihnya sabar"])

        # Fetch kedua di hari yang sama tidak menduplikasi review maupun titik riwayat.
        details["userRatingCount"] = 121
        self.run_cli(FakeClient(details={"p1": details}), "fetch")
        self.assertEqual(len(self.data("reviews.json")), 2)
        history = self.data("history.json")["p1"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["count"], 121)

    def test_partial_failure_keeps_previous_numbers(self):
        self.add_centers(place("p1", "Sparks Swim A"), place("p2", "Sparks Swim B"))
        ok = {pid: dict(place(pid, f"Sparks Swim {pid}"), rating=4.5, userRatingCount=10) for pid in ("p1", "p2")}
        self.run_cli(FakeClient(details=ok), "fetch")

        code, output = self.run_cli(FakeClient(details=ok, failing={"p2"}), "fetch")
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

    def test_changed_place_id_moves_data(self):
        self.add_centers(place("old", "Sparks Swim A"))
        first = dict(place("old", "Sparks Swim A"), rating=4.0, userRatingCount=5)
        self.run_cli(FakeClient(details={"old": first}), "fetch")
        moved = dict(place("new", "Sparks Swim A"), rating=4.1, userRatingCount=6)
        self.run_cli(FakeClient(details={"old": moved}), "fetch")
        self.assertEqual(self.config()["centers"][0]["place_id"], "new")
        self.assertIn("new", self.data("history.json"))
        self.assertNotIn("old", self.data("history.json"))

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
