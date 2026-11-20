"""Fetch residential areas and building footprints for a city bbox from Overpass, once.

usage: python osm_fetch.py <city>  -> out/<city>/osm_areas.geojson, out/<city>/osm_buildings.geojson
"""
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "osm"
OUT = ROOT / "out"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
CITY = next((a for a in sys.argv[1:] if a in CITIES), "gurgaon")
BBOX = tuple(CITIES[CITY]["bbox"])  # south, west, north, east
TILES = int(CITIES[CITY].get("tiles") or 1)  # split the buildings query when one bbox is too big for Overpass
OUT = OUT / CITY
CACHE = CACHE / CITY
MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    # last: this mirror has answered every recent request with an SSL EOF, so it only costs a round trip
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]
ROUNDS = 4  # passes over the mirror list before giving up


def backoff(attempt):
    """Seconds to wait after a failed attempt.

    A busy mirror answers "server is currently at capacity" and asks for exponential backoff, so wait longer
    on each pass over the list while still moving to the next mirror quickly (a different one may be free).
    Capped, so a many-tile fetch cannot stall forever.
    """
    return min(10 * 2 ** (attempt // len(MIRRORS)), 300)


def overpass(query, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    body = urllib.parse.urlencode({"data": query}).encode()
    for attempt, url in enumerate(MIRRORS * ROUNDS):
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "flat-finder/0.1"})
            raw = urllib.request.urlopen(req, timeout=300).read()
            data = json.loads(raw)
            f.write_bytes(raw)
            return data
        except Exception as e:
            wait = backoff(attempt)
            print(f"mirror failed {url} {e} (retry in {wait}s)", flush=True)
            time.sleep(wait)
    raise SystemExit(f"all Overpass mirrors failed for {name}")


def tile_bboxes(bbox, n):
    """Split a bbox into an n x n grid. One query for a city the size of Hyderabad times out."""
    s, w, north, e = bbox
    dy, dx = (north - s) / n, (e - w) / n
    return [(s + i * dy, w + j * dx, s + (i + 1) * dy, w + (j + 1) * dx) for i in range(n) for j in range(n)]


def building_elements():
    """Every building way in the city bbox. Tiles are cached separately so a failure only repeats one tile."""
    tiles = tile_bboxes(BBOX, TILES)
    seen, els = set(), []
    for i, (s, w, n, e) in enumerate(tiles):
        # keep the original cache name for untiled cities so their cached response is still reused
        name = "buildings" if len(tiles) == 1 else f"buildings-{i:02d}"
        data = overpass(f'[out:json][timeout:280];way["building"]({s},{w},{n},{e});out geom;', name)
        for el in data["elements"]:
            if el["id"] not in seen:  # a way on a tile edge comes back in both tiles
                seen.add(el["id"])
                els.append(el)
        if len(tiles) > 1:
            print(f"tile {i + 1}/{len(tiles)}: {len(els)} buildings so far", flush=True)
    return els


def _pts(geom):
    return [(round(p["lon"], 6), round(p["lat"], 6)) for p in geom]


def ring_from_relation(el):
    """Join a multipolygon relation's outer member ways into closed rings."""
    segs = [_pts(m["geometry"]) for m in el.get("members", []) if m.get("role") == "outer" and m.get("geometry")]
    rings = []
    while segs:
        ring = segs.pop(0)
        changed = True
        while ring[0] != ring[-1] and changed:
            changed = False
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]
                elif s[-1] == ring[-1]:
                    ring += s[::-1][1:]
                elif s[-1] == ring[0]:
                    ring = s[:-1] + ring
                elif s[0] == ring[0]:
                    ring = s[::-1][:-1] + ring
                else:
                    continue
                segs.pop(i)
                changed = True
                break
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def height_of(tags):
    try:
        if tags.get("height"):
            return float(str(tags["height"]).split()[0])
        if tags.get("building:levels"):
            return float(tags["building:levels"]) * 3.2
    except ValueError:
        pass
    return None


def main():
    s, w, n, e = BBOX
    bb = f"({s},{w},{n},{e})"
    areas = overpass(f'[out:json][timeout:280];(way["landuse"="residential"]["name"]{bb};relation["landuse"="residential"]["name"]{bb};);out geom;', "areas")
    feats = []
    for el in areas["elements"]:
        rings = ring_from_relation(el) if el["type"] == "relation" else [_pts(el["geometry"])]
        for r in rings:
            feats.append({"type": "Feature", "properties": {"osm": f"{el['type']}/{el['id']}", "name": el["tags"]["name"]},
                          "geometry": {"type": "Polygon", "coordinates": [r]}})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "osm_areas.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    print("areas", len(feats))

    bf = []
    for el in building_elements():
        if "geometry" not in el:
            continue
        r = _pts(el["geometry"])
        if r[0] != r[-1]:
            r.append(r[0])
        bf.append({"type": "Feature", "properties": {"osm": el["id"], "h": height_of(el.get("tags", {}))},
                   "geometry": {"type": "Polygon", "coordinates": [r]}})
    (OUT / "osm_buildings.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": bf}))
    print("buildings", len(bf))


POI_QUERY = """[out:json][timeout:280];(
  way["leisure"="park"]{bb};relation["leisure"="park"]{bb};node["leisure"="park"]{bb};
  node["railway"="station"]{bb};node["station"="subway"]{bb};node["railway"="halt"]{bb};
  node["amenity"="school"]{bb};way["amenity"="school"]{bb};
  node["amenity"="hospital"]{bb};way["amenity"="hospital"]{bb};
  node["shop"="mall"]{bb};way["shop"="mall"]{bb};way["shop"="supermarket"]{bb};node["shop"="supermarket"]{bb};
);out center tags;"""


def poi_kind(t):
    if t.get("leisure") == "park":
        return "park"
    if t.get("station") == "subway" or "metro" in (t.get("name") or "").lower() or t.get("subway") == "yes":
        return "metro"
    if t.get("railway") in ("station", "halt"):
        return "rail"
    if t.get("amenity") in ("school", "hospital"):
        return t["amenity"]
    if t.get("shop") in ("mall", "supermarket"):
        return "shopping"
    return None


def fetch_pois():
    s, w, n, e = BBOX
    data = overpass(POI_QUERY.replace("{bb}", f"({s},{w},{n},{e})"), "pois")
    out = []
    for el in data["elements"]:
        c = el.get("center") or ({"lat": el["lat"], "lon": el["lon"]} if "lat" in el else None)
        k = poi_kind(el.get("tags", {}))
        if c and k:
            out.append({"k": k, "name": el.get("tags", {}).get("name"), "lng": round(c["lon"], 5), "lat": round(c["lat"], 5)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "osm_pois.json").write_text(json.dumps(out))
    from collections import Counter
    print("pois", Counter(p["k"] for p in out))


if __name__ == "__main__":
    if "pois" in sys.argv:
        fetch_pois()
    else:
        main()
        fetch_pois()
