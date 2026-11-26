"""Peak-hour drive time and distance between every society and an office, from Google's Routes API.

usage: python commute.py <city>          -> data/commute/<city>-<office key>.json       (Google, peak traffic; needs a key)
       python commute.py <city> --osrm   -> data/commute/<city>-<office key>-osrm.json  (OpenStreetMap, no traffic; free, no key)
       (run build_city.py <city> first so web/public/data/<city>.json exists, and again afterwards)

The office is set per city in data/cities.json under "commute". Morning is home -> office leaving 9:00,
evening is office -> home leaving 18:00, both on the next Wednesday (a typical midweek day), local time.
Google predicts these from historical and live traffic (TRAFFIC_AWARE_OPTIMAL, best guess). Times are
Google's prediction, not ours, and every result keeps the departure time it was asked for.

--osrm asks the public OSRM server (OpenStreetMap roads) for road distance and drive time with no traffic,
both ways. It cannot say anything about 9 AM or 6 PM; the site labels these as traffic-free.

Key: GOOGLE_MAPS_KEY in the environment or in ~/.claude/.env (Routes API enabled). Resumable: societies
already looked up are skipped, so a rerun only costs the new ones.
"""
import datetime
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).parent
URL = "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
BATCH = 100  # Google's element limit per request for TRAFFIC_AWARE_OPTIMAL (100 origins x 1 destination)
IST = datetime.timezone(datetime.timedelta(hours=5, minutes=30))


def key():
    if os.environ.get("GOOGLE_MAPS_KEY"):
        return os.environ["GOOGLE_MAPS_KEY"]
    env = pathlib.Path.home() / ".claude" / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GOOGLE_MAPS_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise SystemExit("GOOGLE_MAPS_KEY not found: set it in the environment or in ~/.claude/.env")


def next_wednesday(hour, today=None):
    """Next Wednesday (at least a day ahead, so Google always gets a future time) at hour:00 IST, as RFC 3339 UTC."""
    today = today or datetime.datetime.now(IST).date()
    days = (2 - today.weekday()) % 7 or 7
    d = today + datetime.timedelta(days=days)
    return datetime.datetime(d.year, d.month, d.day, hour, tzinfo=IST).astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def point(s):
    return {"waypoint": {"location": {"latLng": {"latitude": s["lat"], "longitude": s["lng"]}}}}


def matrix(origins, destinations, depart, api_key):
    body = {"origins": origins, "destinations": destinations, "travelMode": "DRIVE",
            "routingPreference": "TRAFFIC_AWARE_OPTIMAL", "trafficModel": "BEST_GUESS", "departureTime": depart}
    req = urllib.request.Request(URL, data=json.dumps(body).encode(), method="POST", headers={
        "Content-Type": "application/json", "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "originIndex,destinationIndex,duration,staticDuration,distanceMeters,condition,status"})
    for attempt in range(4):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=120).read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:400]
            if e.code in (400, 401, 403):  # a key or request problem: retrying will not help
                raise SystemExit(f"Google Routes API refused the request ({e.code}): {msg}")
            print("  retry", attempt + 1, e.code, msg, flush=True)
        except Exception as e:
            print("  retry", attempt + 1, e, flush=True)
        time.sleep(5 * (attempt + 1))
    raise SystemExit("Google Routes API kept failing")


def minutes(d):
    return round(int(d.rstrip("s")) / 60, 1) if d else None


OSRM = "https://router.project-osrm.org/table/v1/driving/"


def osrm(city, cfg, office, data):
    out_file = ROOT.parent / "data" / "commute" / f"{city}-{office['key']}-osrm.json"
    doc = {"office": office, "source": "OSRM (OpenStreetMap road network), driving, no traffic", "societies": {}}
    socs = data["societies"]
    here = f"{office['lng']},{office['lat']}"
    for i in range(0, len(socs), BATCH):
        chunk = socs[i:i + BATCH]
        coords = ";".join([here] + [f"{s['lng']},{s['lat']}" for s in chunk])
        rest = ";".join(str(j) for j in range(1, len(chunk) + 1))
        got = {}
        for way, q in (("to", f"sources={rest}&destinations=0"), ("back", f"sources=0&destinations={rest}")):
            for attempt in range(4):
                try:
                    # curl uses the macOS trust store and TLS (the system Python's older TLS fails on this server)
                    import subprocess
                    raw = subprocess.run(["curl", "-s", "--max-time", "120", "-A", "flat-finder/0.1",
                                          f"{OSRM}{coords}?{q}&annotations=duration,distance"], capture_output=True, check=True).stdout
                    r = json.loads(raw)
                    if r.get("code") == "Ok":
                        break
                except Exception as e:
                    print("  retry", attempt + 1, e, flush=True)
                time.sleep(5 * (attempt + 1))
            else:
                raise SystemExit("OSRM kept failing")
            got[way] = r
            time.sleep(1.5)  # public demo server: keep it gentle
        for j, s in enumerate(chunk):
            d, t = got["to"]["distances"][j][0], got["to"]["durations"][j][0]
            d2, t2 = got["back"]["distances"][0][j], got["back"]["durations"][0][j]
            if d is None or t is None:
                continue
            doc["societies"][s["id"]] = {"km": round(d / 1000, 1), "free_min": round(t / 60, 1),
                                         "back_km": round(d2 / 1000, 1) if d2 is not None else None,
                                         "back_free_min": round(t2 / 60, 1) if t2 is not None else None}
        print(f"{min(i + BATCH, len(socs))}/{len(socs)}", flush=True)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(doc, indent=0))
    import statistics
    v = list(doc["societies"].values())
    print("routes", len(v), "of", len(socs), "| median", statistics.median(r["km"] for r in v), "km,", statistics.median(r["free_min"] for r in v), "min without traffic")


def main(city):
    cfg = json.loads((ROOT.parent / "data" / "cities.json").read_text())[city]
    office = cfg.get("commute")
    if not office:
        raise SystemExit(f"no commute office set for {city} in data/cities.json")
    data = json.loads((ROOT.parent / "web" / "public" / "data" / f"{city}.json").read_text())
    if "--osrm" in sys.argv:
        return osrm(city, cfg, office, data)
    out_file = ROOT.parent / "data" / "commute" / f"{city}-{office['key']}.json"
    doc = json.loads(out_file.read_text()) if out_file.exists() else {}
    if doc.get("office", {}).get("address") != office["address"]:
        doc = {}  # a different office: start over
    doc.setdefault("office", office)
    doc.setdefault("am_departure", next_wednesday(9))
    doc.setdefault("pm_departure", next_wednesday(18))
    doc.setdefault("source", "Google Maps Routes API, driving, TRAFFIC_AWARE_OPTIMAL, best-guess traffic model")
    res = doc.setdefault("societies", {})
    todo = [s for s in data["societies"] if s["id"] not in res]
    print(f"societies to look up {len(todo)} of {len(data['societies'])}; morning {doc['am_departure']}, evening {doc['pm_departure']} (UTC)", flush=True)
    # departure times must be in the future: if a resumed run's date has passed, ask for the next one
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if todo and doc["am_departure"] < now:
        doc["am_departure"], doc["pm_departure"] = next_wednesday(9), next_wednesday(18)
    api_key = key()
    there = [{"waypoint": {"address": office["address"]}}]
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        pts = [point(s) for s in chunk]
        am = matrix(pts, there, doc["am_departure"], api_key)   # home -> office at 9:00
        pm = matrix(there, pts, doc["pm_departure"], api_key)   # office -> home at 18:00
        am_by = {e.get("originIndex", 0): e for e in am}
        pm_by = {e.get("destinationIndex", 0): e for e in pm}
        for j, s in enumerate(chunk):
            a, p = am_by.get(j, {}), pm_by.get(j, {})
            ok = lambda e: e.get("condition") == "ROUTE_EXISTS"
            res[s["id"]] = {
                "am_min": minutes(a.get("duration")) if ok(a) else None,
                "am_km": round(a["distanceMeters"] / 1000, 1) if ok(a) and a.get("distanceMeters") else None,
                "pm_min": minutes(p.get("duration")) if ok(p) else None,
                "pm_km": round(p["distanceMeters"] / 1000, 1) if ok(p) and p.get("distanceMeters") else None,
                "free_min": minutes(a.get("staticDuration")) if ok(a) else None,  # same route without traffic
            }
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps(doc, indent=0))
        print(f"{min(i + BATCH, len(todo))}/{len(todo)}", flush=True)
    vals = [r for r in res.values() if r["am_min"] is not None]
    if vals:
        import statistics
        print("routes found", len(vals), "of", len(res), "| median morning", statistics.median(r["am_min"] for r in vals),
              "min, evening", statistics.median(r["pm_min"] for r in vals if r["pm_min"] is not None), "min")


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if not a.startswith("-")), "noida"))
