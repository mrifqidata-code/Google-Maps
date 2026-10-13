"""Mengubah link Google Maps (atau place ID) menjadi data tempat dari Places API."""

import re
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (compatible; sparks-swim-review-monitor)"
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
AT_COORDS_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
DATA_COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")


class LinkError(Exception):
    pass


def direct_place_id(value):
    """Place ID yang bisa langsung dipakai tanpa pencarian, atau None."""
    value = value.strip()
    if value.startswith("place_id:"):
        return value[len("place_id:") :]
    if "://" not in value and PLACE_ID_RE.match(value):
        return value
    query = urllib.parse.parse_qs(urllib.parse.urlparse(value).query)
    for key in ("query_place_id", "place_id"):
        if query.get(key):
            return query[key][0]
    q = query.get("q", [""])[0]
    if q.startswith("place_id:"):
        return q[len("place_id:") :]
    return None


def expand_url(url, opener=None):
    """Ikuti redirect link pendek (maps.app.goo.gl, goo.gl/maps) ke URL lengkap."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if host not in ("maps.app.goo.gl", "goo.gl", "g.co"):
        return url
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    open_url = opener or urllib.request.urlopen
    with open_url(request, timeout=30) as response:
        final = response.geturl()
    parsed = urllib.parse.urlparse(final)
    # Halaman persetujuan cookie Google menyimpan URL tujuan di parameter "continue".
    if parsed.netloc.startswith("consent."):
        target = urllib.parse.parse_qs(parsed.query).get("continue", [""])[0]
        if target:
            return target
    return final


def parse_maps_url(url):
    """Ambil nama tempat dan koordinat dari URL Google Maps lengkap."""
    parsed = urllib.parse.urlparse(url)
    name = None
    parts = parsed.path.split("/")
    for marker in ("place", "search"):
        if marker in parts:
            index = parts.index(marker)
            if index + 1 < len(parts) and parts[index + 1] and not parts[index + 1].startswith("@"):
                name = urllib.parse.unquote_plus(parts[index + 1])
            break
    if not name:
        query = urllib.parse.parse_qs(parsed.query)
        name = (query.get("q") or query.get("query") or [None])[0]

    # Koordinat di "!3d..!4d.." adalah titik tempatnya; "@lat,lng" hanya pusat tampilan peta.
    match = DATA_COORDS_RE.search(url) or AT_COORDS_RE.search(url)
    coords = (float(match.group(1)), float(match.group(2))) if match else None
    return name, coords


def resolve(value, client, opener=None):
    """Kembalikan dict tempat dari Places API untuk link Google Maps atau place ID."""
    place_id = direct_place_id(value)
    if place_id:
        return client.place_details(place_id)

    if "://" not in value:
        raise LinkError(f"Bukan link Google Maps atau place ID: {value}")

    url = expand_url(value, opener=opener)
    place_id = direct_place_id(url)
    if place_id:
        return client.place_details(place_id)

    name, coords = parse_maps_url(url)
    if not name:
        raise LinkError(f"Nama tempat tidak ditemukan di link: {url}")
    bias = None
    if coords:
        bias = {"circle": {"center": {"latitude": coords[0], "longitude": coords[1]}, "radius": 500.0}}
    results = client.search_text(name, max_pages=1, location_bias=bias)
    if not results:
        raise LinkError(f"Tempat '{name}' tidak ditemukan lewat Places API")
    return results[0]
