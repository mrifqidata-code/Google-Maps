"""Klien minimal untuk Google Places API (New), hanya pakai standard library."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://places.googleapis.com/v1"

# Field mask menentukan SKU (dan biaya) tiap request. Pencarian sengaja tidak
# meminta rating/reviews supaya tetap di SKU yang lebih murah.
SEARCH_FIELDS = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.googleMapsUri",
        "places.businessStatus",
        "nextPageToken",
    ]
)
DETAIL_FIELDS = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "googleMapsUri",
        "businessStatus",
        "rating",
        "userRatingCount",
        "reviews",
    ]
)

RETRY_STATUSES = {429, 500, 502, 503, 504}


class PlacesError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class PlacesClient:
    def __init__(self, api_key, language_code="id", region_code="ID", timeout=30, retries=3):
        if not api_key:
            raise ValueError("API key Google Maps kosong. Set environment variable GOOGLE_MAPS_API_KEY.")
        self.api_key = api_key
        self.language_code = language_code
        self.region_code = region_code
        self.timeout = timeout
        self.retries = retries

    def _request(self, method, path, field_mask, body=None, params=None):
        url = BASE_URL + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": field_mask,
            "Content-Type": "application/json",
        }
        for attempt in range(self.retries):
            request = urllib.request.Request(url, data=data, method=method, headers=headers)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code in RETRY_STATUSES and attempt < self.retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise PlacesError(error.code, _error_message(error)) from None
            except urllib.error.URLError as error:
                if attempt < self.retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise PlacesError(0, str(error.reason)) from None
        raise AssertionError("unreachable")

    def search_text(self, query, max_pages=3, location_bias=None):
        """Text Search (New). Maksimal 20 hasil per halaman, 60 hasil total."""
        places = []
        page_token = None
        for _ in range(max_pages):
            body = {
                "textQuery": query,
                "languageCode": self.language_code,
                "regionCode": self.region_code,
                "pageSize": 20,
            }
            if location_bias:
                body["locationBias"] = location_bias
            if page_token:
                body["pageToken"] = page_token
            data = self._request("POST", "/places:searchText", SEARCH_FIELDS, body=body)
            places.extend(data.get("places", []))
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return places

    def place_details(self, place_id):
        """Place Details (New): rating, jumlah ulasan, dan maksimal 5 review."""
        return self._request(
            "GET",
            "/places/" + urllib.parse.quote(place_id, safe=""),
            DETAIL_FIELDS,
            params={"languageCode": self.language_code, "regionCode": self.region_code},
        )


def _error_message(error):
    raw = error.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return raw[:300] or error.reason
