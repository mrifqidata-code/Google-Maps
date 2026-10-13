import unittest

from monitor.links import LinkError, direct_place_id, expand_url, parse_maps_url, resolve


class FakeClient:
    def __init__(self, results=None):
        self.calls = []
        self.results = results if results is not None else [
            {"place_id": "ChIJfound", "data_id": "0x1:0x2", "name": "Sparks Swim BSD", "address": "", "maps_url": ""}
        ]

    def maps_search(self, query, ll=None, start=0):
        self.calls.append((query, ll))
        return self.results


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

    def test_raw_data_id(self):
        self.assertEqual(direct_place_id("0x2e69f1a2b:0x5a2bc3d"), "0x2e69f1a2b:0x5a2bc3d")

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
    def test_place_url_with_data_id_and_coordinates(self):
        url = (
            "https://www.google.com/maps/place/Sparks+Swim+Bintaro/"
            "@-6.2700000,106.7400000,17z/data=!3m1!4b1!4m6!3m5!1s0x2e69fb:0x9a1c!8m2!3d-6.2712345!4d106.7456789"
        )
        name, coords, data_id = parse_maps_url(url)
        self.assertEqual(name, "Sparks Swim Bintaro")
        self.assertEqual(coords, (-6.2712345, 106.7456789))
        self.assertEqual(data_id, "0x2e69fb:0x9a1c")

    def test_place_url_with_viewport_only(self):
        name, coords, data_id = parse_maps_url("https://www.google.com/maps/place/Sparks%20Swim/@-6.2,106.8,15z")
        self.assertEqual((name, coords, data_id), ("Sparks Swim", (-6.2, 106.8), None))

    def test_query_param(self):
        name, coords, _ = parse_maps_url("https://maps.google.com/maps?q=Sparks+Swim+Kemang")
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
    def test_place_id_needs_no_search(self):
        client = FakeClient()
        place = resolve("ChIJN1t_tDeuEmsRUsoyG83frY4", client)
        self.assertEqual(place["place_id"], "ChIJN1t_tDeuEmsRUsoyG83frY4")
        self.assertEqual(client.calls, [])

    def test_link_with_data_id_needs_no_search(self):
        client = FakeClient()
        url = "https://www.google.com/maps/place/Sparks+Swim+BSD/@-6.3,106.65,17z/data=!4m5!3m4!1s0xabc:0xdef!8m2!3d-6.301!4d106.652"
        place = resolve(url, client)
        self.assertEqual((place["place_id"], place["data_id"], place["name"]), ("0xabc:0xdef", "0xabc:0xdef", "Sparks Swim BSD"))
        self.assertEqual(client.calls, [])

    def test_link_without_ids_searches_near_coordinates(self):
        client = FakeClient()
        place = resolve("https://www.google.com/maps/place/Sparks+Swim+BSD/@-6.3,106.65,17z", client)
        self.assertEqual(place["place_id"], "ChIJfound")
        self.assertEqual(client.calls, [("Sparks Swim BSD", "@-6.3,106.65,17z")])

    def test_search_without_results_fails(self):
        with self.assertRaises(LinkError):
            resolve("https://www.google.com/maps/place/Tidak+Ada", FakeClient(results=[]))

    def test_rejects_free_text(self):
        with self.assertRaises(LinkError):
            resolve("Sparks Swim", FakeClient())


if __name__ == "__main__":
    unittest.main()
