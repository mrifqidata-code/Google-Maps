import unittest

from monitor.links import LinkError, direct_place_id, expand_url, parse_maps_url, resolve


class FakeClient:
    def __init__(self):
        self.calls = []

    def place_details(self, place_id):
        self.calls.append(("details", place_id))
        return {"id": place_id, "displayName": {"text": "Sparks Swim"}}

    def search_text(self, query, max_pages=3, location_bias=None):
        self.calls.append(("search", query, location_bias))
        return [{"id": "ChIJfound", "displayName": {"text": query}}]


class FakeResponse:
    def __init__(self, url):
        self.url = url

    def geturl(self):
        return self.url

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class DirectPlaceIdTest(unittest.TestCase):
    def test_raw_place_id(self):
        self.assertEqual(direct_place_id("ChIJN1t_tDeuEmsRUsoyG83frY4"), "ChIJN1t_tDeuEmsRUsoyG83frY4")

    def test_prefixed_place_id(self):
        self.assertEqual(direct_place_id("place_id:abc"), "abc")

    def test_query_place_id_param(self):
        url = "https://www.google.com/maps/search/?api=1&query=Sparks&query_place_id=ChIJxyz"
        self.assertEqual(direct_place_id(url), "ChIJxyz")

    def test_q_place_id_param(self):
        self.assertEqual(direct_place_id("https://maps.google.com/?q=place_id:ChIJq"), "ChIJq")

    def test_plain_text_is_not_place_id(self):
        self.assertIsNone(direct_place_id("Sparks Swim Bintaro"))
        self.assertIsNone(direct_place_id("https://maps.app.goo.gl/AbCdEf"))


class ParseMapsUrlTest(unittest.TestCase):
    def test_place_url_prefers_data_coordinates(self):
        url = (
            "https://www.google.com/maps/place/Sparks+Swim+Bintaro/"
            "@-6.2700000,106.7400000,17z/data=!3m1!4b1!4m6!3m5!1s0x0:0x1!8m2!3d-6.2712345!4d106.7456789"
        )
        name, coords = parse_maps_url(url)
        self.assertEqual(name, "Sparks Swim Bintaro")
        self.assertEqual(coords, (-6.2712345, 106.7456789))

    def test_place_url_with_viewport_only(self):
        name, coords = parse_maps_url("https://www.google.com/maps/place/Sparks%20Swim/@-6.2,106.8,15z")
        self.assertEqual(name, "Sparks Swim")
        self.assertEqual(coords, (-6.2, 106.8))

    def test_query_param(self):
        name, coords = parse_maps_url("https://maps.google.com/maps?q=Sparks+Swim+Kemang")
        self.assertEqual(name, "Sparks Swim Kemang")
        self.assertIsNone(coords)


class ExpandUrlTest(unittest.TestCase):
    def test_long_url_is_not_fetched(self):
        def opener(*args, **kwargs):
            raise AssertionError("should not fetch")

        url = "https://www.google.com/maps/place/X"
        self.assertEqual(expand_url(url, opener=opener), url)

    def test_short_url_follows_redirect(self):
        final = "https://www.google.com/maps/place/Sparks+Swim/@-6.2,106.8,15z"
        self.assertEqual(expand_url("https://maps.app.goo.gl/abc", opener=lambda *a, **k: FakeResponse(final)), final)

    def test_consent_page_uses_continue_target(self):
        consent = "https://consent.google.com/m?continue=https://www.google.com/maps/place/Sparks%2BSwim&gl=ID"
        result = expand_url("https://maps.app.goo.gl/abc", opener=lambda *a, **k: FakeResponse(consent))
        self.assertEqual(result, "https://www.google.com/maps/place/Sparks+Swim")


class ResolveTest(unittest.TestCase):
    def test_place_id_uses_details(self):
        client = FakeClient()
        place = resolve("ChIJN1t_tDeuEmsRUsoyG83frY4", client)
        self.assertEqual(place["id"], "ChIJN1t_tDeuEmsRUsoyG83frY4")
        self.assertEqual(client.calls[0][0], "details")

    def test_url_searches_with_location_bias(self):
        client = FakeClient()
        url = "https://www.google.com/maps/place/Sparks+Swim+BSD/@-6.3,106.65,17z/data=!3d-6.301!4d106.652"
        place = resolve(url, client)
        self.assertEqual(place["id"], "ChIJfound")
        kind, query, bias = client.calls[0]
        self.assertEqual((kind, query), ("search", "Sparks Swim BSD"))
        self.assertEqual(bias["circle"]["center"], {"latitude": -6.301, "longitude": 106.652})

    def test_rejects_free_text(self):
        with self.assertRaises(LinkError):
            resolve("Sparks Swim", FakeClient())


if __name__ == "__main__":
    unittest.main()
