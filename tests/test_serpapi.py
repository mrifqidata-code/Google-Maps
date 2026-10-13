import io
import json
import unittest
import urllib.error
import urllib.parse
from unittest import mock

from monitor import serpapi
from monitor.serpapi import SerpApiClient, SerpApiError, is_data_id, maps_url, normalize_place


class FakeHttpResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def respond(payload):
    return FakeHttpResponse(json.dumps(payload).encode("utf-8"))


class HelpersTest(unittest.TestCase):
    def test_is_data_id(self):
        self.assertTrue(is_data_id("0x2e69f1:0x5a2b"))
        self.assertFalse(is_data_id("ChIJN1t_tDeuEmsRUsoyG83frY4"))

    def test_maps_url(self):
        self.assertEqual(maps_url("ChIJabc"), "https://www.google.com/maps/place/?q=place_id:ChIJabc")
        self.assertIn("!1s0x1:0x2", maps_url("0x1:0x2"))

    def test_normalize_place(self):
        place = normalize_place({"title": "Sparks Swim", "place_id": "ChIJa", "data_id": "0x1:0x2", "rating": 4.8, "reviews": 120})
        self.assertEqual(place["name"], "Sparks Swim")
        self.assertEqual(place["count"], 120)
        self.assertEqual(place["data_id"], "0x1:0x2")


class ClientTest(unittest.TestCase):
    def setUp(self):
        self.client = SerpApiClient("secret", retries=1)

    def test_reviews_uses_newest_first_and_place_id(self):
        payload = {
            "place_info": {"title": "Sparks Swim", "rating": 4.7, "reviews": 88},
            "reviews": [{"review_id": "r1"}],
            "serpapi_pagination": {"next_page_token": "tok"},
        }
        with mock.patch.object(serpapi.urllib.request, "urlopen", return_value=respond(payload)) as urlopen:
            result = self.client.reviews("ChIJabc")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(urlopen.call_args[0][0]).query)
        self.assertEqual(query["engine"], ["google_maps_reviews"])
        self.assertEqual(query["sort_by"], ["newestFirst"])
        self.assertEqual(query["place_id"], ["ChIJabc"])
        self.assertNotIn("num", query)  # num tidak boleh dipakai di halaman pertama
        self.assertEqual(result["next_page_token"], "tok")
        self.assertEqual(result["place_info"]["reviews"], 88)

    def test_reviews_next_page_uses_data_id_and_num(self):
        with mock.patch.object(serpapi.urllib.request, "urlopen", return_value=respond({"reviews": []})) as urlopen:
            self.client.reviews("0x1:0x2", next_page_token="tok")
        query = urllib.parse.parse_qs(urllib.parse.urlparse(urlopen.call_args[0][0]).query)
        self.assertEqual(query["data_id"], ["0x1:0x2"])
        self.assertEqual(query["next_page_token"], ["tok"])
        self.assertEqual(query["num"], ["20"])

    def test_maps_search_handles_single_place_result(self):
        payload = {"place_results": {"title": "Sparks Swim Bintaro", "place_id": "ChIJb", "data_id": "0x3:0x4"}}
        with mock.patch.object(serpapi.urllib.request, "urlopen", return_value=respond(payload)):
            places = self.client.maps_search("Sparks Swim Bintaro")
        self.assertEqual([p["place_id"] for p in places], ["ChIJb"])

    def test_empty_result_message_is_not_an_error(self):
        payload = {"error": "Google hasn't returned any results for this query."}
        with mock.patch.object(serpapi.urllib.request, "urlopen", return_value=respond(payload)):
            self.assertEqual(self.client.maps_search("xyz"), [])

    def test_error_field_raises(self):
        with mock.patch.object(serpapi.urllib.request, "urlopen", return_value=respond({"error": "Invalid API key."})):
            with self.assertRaises(SerpApiError):
                self.client.account()

    def test_http_error_message(self):
        error = urllib.error.HTTPError("u", 401, "Unauthorized", {}, io.BytesIO(b'{"error": "Invalid API key."}'))
        with mock.patch.object(serpapi.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(SerpApiError) as caught:
                self.client.account()
        self.assertEqual(caught.exception.status, 401)
        self.assertIn("Invalid API key", str(caught.exception))

    def test_missing_key(self):
        with self.assertRaises(ValueError):
            SerpApiClient("")


if __name__ == "__main__":
    unittest.main()
