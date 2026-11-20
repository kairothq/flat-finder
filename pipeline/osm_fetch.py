"""Fetch residential areas and building footprints for a city bbox from Overpass, once.

usage: python osm_fetch.py <city> [pois|transit]  -> out/<city>/osm_areas.geojson, osm_buildings.geojson, osm_pois.json, osm_transit.geojson
"""
import json
import pathlib
import re
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
OUT = OUT / CITY
CACHE = CACHE / CITY
MIRRORS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def overpass(query, name):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / f"{name}.json"
    if f.exists():
        return json.loads(f.read_text())
    body = urllib.parse.urlencode({"data": query}).encode()
    for url in MIRRORS * 2:
        try:
            req = urllib.request.Request(url, data=body, headers={"User-Agent": "flat-finder/0.1"})
            raw = urllib.request.urlopen(req, timeout=300).read()
            data = json.loads(raw)
            f.write_bytes(raw)
            return data
        except Exception as e:
            print("mirror failed", url, e, flush=True)
            time.sleep(10)
    raise SystemExit("all Overpass mirrors failed")


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

    blds = overpass(f'[out:json][timeout:280];way["building"]{bb};out geom;', "buildings")
    bf = []
    for el in blds["elements"]:
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


TRANSIT_QUERY = """[out:json][timeout:280];
(
  way["railway"~"^(rail|subway|light_rail|monorail)$"]["service"!~"."]{bb};
  way["railway"~"^(construction|proposed)$"]{bb};
)->.w;
.w out geom;
rel(bw.w)["route"~"^(subway|light_rail|monorail|train)$"];
out body;"""
METRO = {"subway", "light_rail", "monorail"}


def transit_features(data):
    """Metro and rail track as LineStrings: kind metro|rail, status open|construction|proposed, line name, colour."""
    routes = {}  # way id -> route relation tags; a metro route wins over a train route
    for el in data["elements"]:
        if el["type"] != "relation":
            continue
        t = el.get("tags", {})
        for m in el.get("members", []):
            if m["type"] == "way" and (m["ref"] not in routes or t.get("route") in METRO):
                routes[m["ref"]] = t
    feats = []
    for el in data["elements"]:
        if el["type"] != "way" or "geometry" not in el:
            continue
        t = el.get("tags", {})
        rw = t["railway"]
        status = rw if rw in ("construction", "proposed") else "open"
        mode = t.get(rw) if status != "open" else rw
        if mode not in METRO | {"rail"}:
            continue
        r = routes.get(el["id"], {})
        name = r.get("name") or t.get("name")
        if name:  # "Line 9 (Dahisar (East) → Kashigaon)" -> "Line 9": one name per line, not per direction
            name = re.sub(r"\s*[:(].*(→|=>|->).*$", "", name).strip() or name
        feats.append({"type": "Feature",
                      "properties": {"kind": "metro" if mode in METRO else "rail", "status": status, "name": name,
                                     "ref": r.get("ref"), "colour": r.get("colour") or t.get("colour")},
                      "geometry": {"type": "LineString", "coordinates": [list(c) for c in _pts(el["geometry"])]}})
    # unfinished sections often lack the colour tag: take the colour of the open section with the same name
    colour = {f["properties"]["name"]: f["properties"]["colour"] for f in feats if f["properties"]["colour"] and f["properties"]["name"]}
    for f in feats:
        f["properties"]["colour"] = f["properties"]["colour"] or colour.get(f["properties"]["name"])
    return feats


def fetch_transit():
    s, w, n, e = BBOX
    pad = 0.05  # lines run on past the city edge; keep a little of them for context
    data = overpass(TRANSIT_QUERY.replace("{bb}", f"({s - pad},{w - pad},{n + pad},{e + pad})"), "transit")
    feats = transit_features(data)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "osm_transit.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}))
    from collections import Counter
    print("transit", Counter((f["properties"]["kind"], f["properties"]["status"]) for f in feats))
    print("lines", Counter(f["properties"]["name"] for f in feats).most_common(12))


if __name__ == "__main__":
    if "pois" in sys.argv:
        fetch_pois()
    elif "transit" in sys.argv:
        fetch_transit()
    else:
        main()
        fetch_pois()
        fetch_transit()
