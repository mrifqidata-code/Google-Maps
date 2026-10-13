"""Mengubah link Google Maps (atau place ID) menjadi data cabang."""

import re
import urllib.parse
import urllib.request

from monitor.serpapi import is_data_id, maps_url

USER_AGENT = "Mozilla/5.0 (compatible; sparks-swim-review-monitor)"
PLACE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")
AT_COORDS_RE = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
DATA_COORDS_RE = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
# ID internal Google Maps di link lengkap, mis. "!1s0x2e69f1:0x5a2b"; bisa langsung dipakai SerpApi.
URL_DATA_ID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")


class LinkError(Exception):
    pass


def direct_place_id(value):
    """Place ID yang bisa langsung dipakai tanpa pencarian, atau None."""
    value = value.strip()
    if is_data_id(value):
        return value
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
    """Ambil nama tempat, koordinat, dan data ID dari URL Google Maps lengkap."""
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
    data_id = URL_DATA_ID_RE.search(url)
    return name, coords, data_id.group(1) if data_id else None


def placeholder(place_id, name="", data_id=None):
    """Cabang yang ID-nya sudah diketahui; nama & alamat diisi saat fetch pertama."""
    data_id = data_id or (place_id if is_data_id(place_id) else "")
    return {
        "place_id": place_id,
        "data_id": data_id,
        "name": name,
        "address": "",
        "maps_url": maps_url(place_id, data_id),
    }


def resolve(value, client, opener=None):
    """Kembalikan dict cabang untuk link Google Maps, place ID, atau data ID.

    Sebisa mungkin tanpa memakai kuota SerpApi: pencarian hanya dilakukan kalau link
    tidak memuat ID tempat sama sekali.
    """
    place_id = direct_place_id(value)
    if place_id:
        return placeholder(place_id)

    if "://" not in value:
        raise LinkError(f"Bukan link Google Maps atau place ID: {value}")

    url = expand_url(value, opener=opener)
    place_id = direct_place_id(url)
    if place_id:
        return placeholder(place_id)

    name, coords, data_id = parse_maps_url(url)
    if data_id:
        return placeholder(data_id, name or "")
    if not name:
        raise LinkError(f"Nama tempat tidak ditemukan di link: {url}")
    ll = f"@{coords[0]},{coords[1]},17z" if coords else None
    results = client.maps_search(name, ll=ll)
    if not results:
        raise LinkError(f"Tempat '{name}' tidak ditemukan di Google Maps")
    return results[0]
