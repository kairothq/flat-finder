"""Polite, cached, resumable GujRERA crawler for Gujarat cities that Magicbricks does not list.

usage: python gujrera_crawl.py <city> [--cached]   -> out/<city>/projects.json (same record shape build_city.py reads)
--cached writes projects.json from what is already cached, without fetching missing project details (they stay empty).
<city> is a key in data/cities.json with a "gujrera_district" (e.g. "Vadodara").

Three public GujRERA endpoints, all used by gujrera.gujarat.gov.in itself:
  dashboard/get-district-wise-projectlist/0/0/all/<district>/all  every registered project in the district (one call)
  maplocation/public/getProjectMapView  (POST [ids])               site boundary each promoter drew on the RERA map
  project_reg/public/getproject-details/<id>                      land area, carpet area, village, TP scheme, description
The promoter's phone and email are kept: GujRERA publishes them so buyers can reach the promoter. PAN and Aadhaar fields
are dropped and never written to disk outside the raw cache.
"""
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.request

import geo

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "gujrera"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
BASE = "https://gujrera.gujarat.gov.in/"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DELAY = 1.0
TIMEOUT = 150  # GujRERA sometimes takes 80+ s per project detail; a shorter timeout only wastes the work in retries
CACHED_ONLY = "--cached" in sys.argv
MAP_BATCH = 100
SQM_PER_ACRE = 4046.86

# RERA project type -> Flat Finder kind
KIND = {"Residential/Group Housing": "apartment", "Mixed Development": "apartment", "Commercial": "commercial",
        "Plotted Development": "plot"}


def fetch(path, body=None, optional=False):
    """GET (or POST JSON) a GujRERA API path; responses cached gzipped by URL and body.
    optional: with --cached, return None instead of fetching when not cached."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = path + ("" if body is None else json.dumps(body, sort_keys=True))
    f = CACHE / (hashlib.sha1(key.encode()).hexdigest() + ".json.gz")
    if f.exists():
        return json.loads(gzip.decompress(f.read_bytes()))
    if optional and CACHED_ONLY:
        return None
    for attempt in range(3):
        try:
            data = None if body is None else json.dumps(body).encode()
            req = urllib.request.Request(BASE + path, data=data, headers={"User-Agent": UA, "Content-Type": "application/json"})
            raw = urllib.request.urlopen(req, timeout=TIMEOUT).read()
            obj = json.loads(raw)
            f.write_bytes(gzip.compress(raw, 9))
            time.sleep(DELAY)
            return obj
        except Exception as e:  # network hiccup or server error: back off and retry
            print("  retry", attempt + 1, path, e, flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def site_ring(coords):
    """[[lng, lat], ...] closed ring from GujRERA's [{"lat", "lang"}] points, or None if unusable."""
    ring = []
    for c in coords or []:
        try:
            pt = [float(c["lang"]), float(c["lat"])]
        except (TypeError, ValueError, KeyError):
            continue
        if not ring or pt != ring[-1]:
            ring.append(pt)
    if len(ring) < 3:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring if len(ring) >= 4 else None


def check_ring(ring, land_sqm):
    """(ring, point, note) after a sanity check. A site far wider than its filed land area has stray points (a mis-click
    on the RERA map): its outline is dropped, and it is placed at the median point only if most points sit within 300 m."""
    x0, y0, x1, y1 = geo.bbox(ring)
    span = geo.dist_m((x0, y0), (x1, y1))
    limit = max(400.0, 6 * land_sqm ** 0.5) if land_sqm else 600.0
    if span <= limit:
        return ring, geo.centroid(ring), None
    pts = ring[:-1]
    med = (sorted(p[0] for p in pts)[len(pts) // 2], sorted(p[1] for p in pts)[len(pts) // 2])
    close = sum(1 for p in pts if geo.dist_m(p, med) <= 300)
    if close >= 0.75 * len(pts):
        return None, med, "GujRERA site map has stray points; placed at the cluster, outline not used"
    return None, None, "GujRERA site map is not usable"


def in_bbox(lng, lat, bbox):
    s, w, n, e = bbox
    return s <= lat <= n and w <= lng <= e


# Locality names. GujRERA's village ("moje") is the whole city for most central projects, so those fall back to the
# town-planning scheme's name, then to an area named in the address. Nothing is inferred from nearby projects.
GENERIC_PLACES = {"vadodara", "vadodara kasba", "baroda", "vadodara city", "gujarat"}
CITY_AREAS = ["Alkapuri", "New Alkapuri", "Fatehgunj", "Pratapnagar", "Sayajigunj", "Raopura", "Akota", "Karelibaug",
              "Nizampura", "Subhanpura", "Manjalpur", "Makarpura", "Jetalpur", "Vasna", "Gorwa", "Sama", "Harni", "Kalali",
              "Atladra", "Tandalja", "Bhayli", "Gotri", "Sevasi", "Vadsar", "Shiyabaug", "Wadi", "Kapurai", "Vemali",
              "Undera", "Ankhol", "Baranpura", "Diwalipura", "Race Course", "Mandvi", "Tarsali", "Chhani", "Bapod", "Bill",
              "Sayajipura", "Karodiya", "Dumad", "Koyali", "Varasiya", "Panigate", "Waghodia Road", "Old Padra Road",
              "Ajwa Road", "Dabhoi Road", "Productivity Road", "Vasna Road", "Gotri Road", "Sun Pharma Road", "Rajmahal Road",
              "Somatalav", "Navapura", "Khanpur", "Jubilee Baug"]
ALIASES = {"atladara": "Atladra", "bhayali": "Bhayli", "tandalaja": "Tandalja", "gorva": "Gorwa", "karelibag": "Karelibaug",
           "sayajiganj": "Sayajigunj", "fatehganj": "Fatehgunj", "chani": "Chhani", "vasana": "Vasna",
           "warasia": "Varasiya", "warasiya": "Varasiya", "siyabaug": "Shiyabaug", "soma talav": "Somatalav"}
# an area name followed by one of these is a road, landmark or school named after the area, not where the project is
NOT_AREA_AFTER = re.compile(r"\s*[-–]?\s*(road|rd\b|marg|by\s*pass|bypass|circle|char\s*rasta|chokdi|crossing|school|hotel|"
                            r"high\s*school|bong|ring\s*road|main\s*road|savli|sevasi|koyali|tank|garden|lake|talav)", re.I)


def is_generic(place):
    return not place or place.lower().strip(" .") in GENERIC_PLACES


def area_names(villages):
    """Known area names: Vadodara's urban areas, plus every specific village GujRERA uses in this district."""
    names = {n.lower(): n for n in CITY_AREAS}
    names.update({v.lower(): v for v in villages if v and not is_generic(v)})
    names.update(ALIASES)
    return names


def area_from_address(address, names):
    """The last area named in an address, skipping names that are part of a road or landmark ("Gotri Sevasi Road")."""
    text = " " + re.sub(r"[^a-z0-9]+", " ", (address or "").lower()) + " "
    hits = []
    for key in sorted(names, key=len, reverse=True):
        for m in re.finditer(rf"(?<= ){re.escape(key)}(?= )", text):
            if any(a < m.end() and m.start() < b for a, b, _ in hits):
                continue  # inside a longer name already found ("new alkapuri" over "alkapuri")
            if not key.endswith("road") and NOT_AREA_AFTER.match(text[m.end():]):
                continue
            hits.append((m.start(), m.end(), names[key]))
    if hits:
        return max(hits)[2]
    # only roads named: "<area> Road" is how people place it ("Jetalpur Road", "Kalali Road")
    roads = [(m.start(), names[k]) for k in names if not k.endswith("road")
             for m in re.finditer(rf"(?<= ){re.escape(k)} (?:main )?road(?= )", text)]
    return max(roads)[1] + " Road" if roads else None


def tp_area(tp_name, names):
    """Area name from a town-planning scheme's name ("( Manjalpur )", "Tandalaja", "Sama-Dumad-Vemali" -> first area)."""
    clean = re.sub(r"[()]", " ", tp_name or "").strip()
    if is_generic(clean):
        return None
    hit = area_from_address(clean.replace("-", " "), names)
    return hit or (title(clean) if re.fullmatch(r"[A-Za-z ]{3,30}", clean) and not is_generic(clean) else None)


def locality(d, row, names):
    """(locality, where it came from)."""
    village = title(d.get("moje")) or title(d.get("subDistName"))
    if not is_generic(village):
        return village, "village"
    tp = tp_area(d.get("tPName"), names)
    if tp:
        return tp, "TP scheme"
    addr = area_from_address(" ".join(x for x in (d.get("projectAddress"), d.get("projectAddress2"), row.get("project_address")) if x), names)
    if addr:
        return addr, "address"
    return village or "Vadodara", "village"


def title(s):
    return " ".join(w.capitalize() for w in re.sub(r"[()]", " ", s or "").split()) or None


def num(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def contact(row):
    """Promoter phone and email as GujRERA lists them, or None."""
    digits = re.sub(r"\D", "", row.get("pr_mobile_no") or "")
    phone = "+91 " + digits[-10:] if len(digits) >= 10 else None
    email = (row.get("pmtr_email_id") or "").strip().lower()
    email = email if re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", email) else None
    return {"phone": phone, "email": email} if phone or email else None


def to_project(row, loc, det, cfg, names=None):
    """One project record in the shape build_city.py expects (the Magicbricks fields it has no data for stay empty)."""
    pid = row["projectRegId"]
    d = (det or {}).get("projectDetail") or {}
    if isinstance(d, list):
        d = d[0] if d else {}
    land = num(d.get("totAreaOfLand"))
    ring = site_ring((loc or {}).get("coordinates"))
    lng = lat = site_note = None
    if ring:
        ring, pt, site_note = check_ring(ring, land)
        if pt:
            lng, lat = pt
        if pt and not in_bbox(lng, lat, cfg["bbox"]):
            ring, lng, lat = None, None, None  # drawn far outside the city: a mis-click on the RERA map, not a location
    place, place_from = locality(d, row, names if names is not None else area_names([]))
    status = "Ready To Move (completion filed with GujRERA)" if row.get("project_status") == "Completed" else "Not marked complete on GujRERA"
    return {
        "mb_id": f"gj{pid}",
        "source": "gujrera",
        "name": title(row.get("projectName")),
        "developer": title(row.get("promoterName")),
        "contact": contact(row),
        "promoter_type": title((loc or {}).get("promotorType")),
        "locality": place,
        "locality_from": place_from,
        "address": ", ".join(x for x in (d.get("projectAddress") or row.get("project_address"), d.get("projectAddress2")) if x),
        "lat": lat, "lng": lng, "site_ring": ring, "site_note": site_note,
        "status": status,
        "rera_status": row.get("project_status"),
        "possession": (row.get("endDate") or "")[-4:] or None,
        "rera_id": row.get("regNo"),
        "approved_on": row.get("approvedOn"),
        "kind": KIND.get(row.get("projectType"), "other"),
        "config_text": row.get("projectType"),
        "description": d.get("projectDesc"),
        "acres": round(land / SQM_PER_ACRE, 2) if land else None,
        "land_sqm": land,
        "carpet_sqm": num(d.get("totCarpetAreaForProjectUnderReg")),
        "tp_scheme": f"TP {d['tPNo']} {title(d.get('tPName')) or ''}".strip() if d.get("tPNo") else None,
        "approving_authority": d.get("approvingAuthority"),
        "project_cost": num(row.get("total_est_cost_of_proj") or row.get("projectCost")),
        "url": f"{BASE}project_reg/public/getproject-details/{pid}",
    }


def main(city):
    cfg = CITIES[city]
    district = cfg["gujrera_district"]
    out = ROOT / "out" / city
    listing = fetch(f"dashboard/get-district-wise-projectlist/0/0/all/{district}/all")
    rows = {r["projectRegId"]: r for r in (listing or {}).get("data") or []}
    print(f"{len(rows)} projects registered in {district}", flush=True)

    ids = sorted(rows)
    locs = {}
    for i in range(0, len(ids), MAP_BATCH):
        batch = ids[i:i + MAP_BATCH]
        for loc in (fetch("maplocation/public/getProjectMapView", batch) or {}).get("data") or []:
            locs[loc["projectId"]] = loc
        print(f"map {min(i + MAP_BATCH, len(ids))}/{len(ids)}: {len(locs)} with a site", flush=True)

    dets = {}
    for n, pid in enumerate(ids, 1):
        dets[pid] = (fetch(f"project_reg/public/getproject-details/{pid}", optional=True) or {}).get("data")
        if n % 100 == 0 or n == len(ids):
            print(f"details {n}/{len(ids)}", flush=True)
    villages = set()
    for det in dets.values():
        d = (det or {}).get("projectDetail") or {}
        d = (d[0] if d else {}) if isinstance(d, list) else d
        villages.add(title(d.get("moje")))
    names = area_names(villages)
    projects = [to_project(rows[pid], locs.get(pid), dets[pid], cfg, names) for pid in ids]
    out.mkdir(parents=True, exist_ok=True)
    (out / "projects.json").write_text(json.dumps(projects, indent=0))
    located = sum(1 for p in projects if p["lat"])
    from collections import Counter
    print("locality from", dict(Counter(p["locality_from"] for p in projects)),
          "still generic", sum(1 for p in projects if is_generic(p["locality"])))
    print(f"wrote {len(projects)} projects, {sum(1 for d in dets.values() if d)} with details, {located} with a site boundary inside the city")


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a in CITIES), "vadodara"))
