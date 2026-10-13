"""Klien minimal untuk SerpApi (Google Maps + Google Maps Reviews), hanya pakai standard library."""

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

BASE_URL = "https://serpapi.com"
RETRY_STATUSES = {429, 500, 502, 503, 504}
DATA_ID_RE = re.compile(r"^0x[0-9a-fA-F]+:0x[0-9a-fA-F]+$")
# SerpApi mengembalikan pesan ini (bukan error sungguhan) kalau hasilnya memang kosong.
EMPTY_RESULT_MARKERS = ("hasn't returned any results", "no results")


class SerpApiError(Exception):
    def __init__(self, status, message):
        super().__init__(f"HTTP {status}: {message}" if status else message)
        self.status = status
        self.message = message


def is_data_id(value):
    return bool(DATA_ID_RE.match(value or ""))


def maps_url(place_id, data_id=None):
    if place_id and not is_data_id(place_id):
        return "https://www.google.com/maps/place/?q=place_id:" + urllib.parse.quote(place_id)
    if data_id or is_data_id(place_id):
        return "https://www.google.com/maps/place/data=!4m2!3m1!1s" + (data_id or place_id)
    return ""


def normalize_place(item):
    """Samakan bentuk hasil local_results/place_results jadi dict sederhana."""
    data_id = item.get("data_id") or ""
    place_id = item.get("place_id") or data_id
    return {
        "place_id": place_id,
        "data_id": data_id,
        "name": item.get("title", ""),
        "address": item.get("address", ""),
        "maps_url": maps_url(place_id, data_id),
        "rating": item.get("rating"),
        "count": item.get("reviews"),
        "status": item.get("open_state") or "",
    }


class SerpApiClient:
    def __init__(self, api_key, hl="id", gl="id", timeout=60, retries=3):
        if not api_key:
            raise ValueError("API key SerpApi kosong. Set environment variable SERPAPI_API_KEY.")
        self.api_key = api_key
        self.hl = hl
        self.gl = gl
        self.timeout = timeout
        self.retries = retries

    def _get(self, path, params):
        query = {key: value for key, value in params.items() if value not in (None, "")}
        query["api_key"] = self.api_key
        url = f"{BASE_URL}{path}?{urllib.parse.urlencode(query)}"
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(url, timeout=self.timeout) as response:
                    data = json.load(response)
                break
            except urllib.error.HTTPError as error:
                if error.code in RETRY_STATUSES and attempt < self.retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise SerpApiError(error.code, _error_message(error)) from None
            except urllib.error.URLError as error:
                if attempt < self.retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise SerpApiError(0, str(error.reason)) from None
        message = data.get("error")
        if message and not any(marker in message.lower() for marker in EMPTY_RESULT_MARKERS):
            raise SerpApiError(0, message)
        return data

    def account(self):
        """Info akun & sisa kuota. Endpoint ini gratis, tidak mengurangi kuota."""
        return self._get("/account.json", {})

    def maps_search(self, query, ll=None, start=0):
        """Google Maps search. Satu halaman = 1 kuota, maksimal 20 tempat."""
        data = self._get(
            "/search.json",
            {
                "engine": "google_maps",
                "type": "search",
                "q": query,
                "ll": ll,
                "start": start or None,
                "hl": self.hl,
                "gl": self.gl,
            },
        )
        if data.get("place_results"):
            return [normalize_place(data["place_results"])]
        return [normalize_place(item) for item in data.get("local_results", [])]

    def reviews(self, place_id, next_page_token=None):
        """Ulasan terbaru satu tempat. Halaman pertama berisi 8 ulasan, berikutnya sampai 20."""
        params = {
            "engine": "google_maps_reviews",
            "sort_by": "newestFirst",
            "hl": self.hl,
            "next_page_token": next_page_token,
            "num": 20 if next_page_token else None,
        }
        params["data_id" if is_data_id(place_id) else "place_id"] = place_id
        data = self._get("/search.json", params)
        return {
            "place_info": data.get("place_info") or {},
            "reviews": data.get("reviews") or [],
            "next_page_token": (data.get("serpapi_pagination") or {}).get("next_page_token"),
        }


def _error_message(error):
    raw = error.read().decode("utf-8", errors="replace")
    try:
        return json.loads(raw)["error"]
    except (ValueError, KeyError, TypeError):
        return raw[:300] or error.reason
