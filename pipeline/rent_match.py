"""Tie Magicbricks rental listings to societies, for cities whose societies come from GujRERA.

A listing matches a project when every word of the project's name is in the listing's society name (or the name with
spaces removed is), phase numbers agree, and it is within 1.5 km (or in the same area when the listing has no map
point). Listings naming a society that is not in GujRERA (mostly built before RERA, 2017) become rental-only
societies placed at the listing's own map point. Listings that name no society are counted but not placed.
"""
import collections
import re
import statistics

import geo
import gujrera_crawl

STOP = {"the", "and", "of", "at", "in", "by", "a", "an", "group", "developers", "developer", "builders", "infra",
        "infrastructure", "realty", "projects", "buildcon", "constructions", "construction", "llp", "pvt", "ltd"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5"}
MAX_M = 1500
KIND = {"Apartment": "apartment", "Penthouse": "apartment", "Studio Apartment": "apartment", "Service Apartment": "apartment",
        "Builder Floor Apartment": "builder floor", "Residential House": "villa", "Villa": "villa"}


def words(name):
    """Name words, singular, without phase numbers or filler words."""
    out = set()
    for w in re.findall(r"[a-z]+", (name or "").lower()):
        if w in STOP or w in ROMAN or len(w) < 2:
            continue
        out.add(w[:-1] if len(w) > 4 and w.endswith("s") else w)
    return out


def phase(name):
    n = (name or "").lower()
    return set(re.findall(r"\d+", n)) | {ROMAN[w] for w in re.findall(r"\b(i{1,3}|iv|v)\b", n)}


def joined(name):
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def dedupe(listings):
    """Drop reposts: same society, BHK, rent, size and floor."""
    seen, out = set(), []
    for l in listings:
        key = (l["society"], l["bhk"], l["price"], l["sqft"], l["floor"])
        if l["society"] and key in seen:
            continue
        seen.add(key)
        out.append(l)
    return out


class Matcher:
    def __init__(self, projects):
        self.projects = [p for p in projects if p.get("lat")]
        self.by_word = collections.defaultdict(list)
        for p in self.projects:
            p["_w"], p["_n"], p["_j"] = words(p["name"]), phase(p["name"]), joined(p["name"])
            for w in p["_w"]:
                self.by_word[w].append(p)
        self.areas = gujrera_crawl.area_names({p.get("locality") for p in self.projects})

    def match(self, l):
        """(project, metres or None) for a listing, or (None, reason)."""
        lw, ln, lj = words(l["society"]), phase(l["society"]), joined(l["society"])
        if not lw:
            return None, "no name"
        area = gujrera_crawl.area_from_address(l.get("locality") or "", self.areas)
        found, phase_unknown = [], []
        for p in {id(p): p for w in lw for p in self.by_word.get(w, [])}.values():
            if not (p["_w"] and p["_w"] <= lw) and not (len(p["_j"]) >= 6 and p["_j"] in lj):
                continue
            if p["_n"] and not ln:
                phase_unknown.append(p)  # a phased project, and the listing does not say which phase
                continue
            if p["_n"] and ln != p["_n"]:
                continue  # a different phase
            short = len(p["_w"]) < 2  # one-word names ("Sharnam", "The Status") need a close map point
            if l.get("lat"):
                d = geo.dist_m((l["lng"], l["lat"]), (p["lng"], p["lat"]))
                if d > (500 if short else MAX_M):
                    continue
            else:
                d = None
                if short:
                    continue
                if area and p.get("locality") and not _same_area(area, p["locality"]):
                    continue
            found.append((len(p["_w"] & lw) * 10 - (d if d is not None else MAX_M) / 500, d, p))
        if not found and phase_unknown:
            if l.get("lat"):  # the listing's own map point picks the phase when it sits on one
                d, p = min((geo.dist_m((l["lng"], l["lat"]), (p["lng"], p["lat"])), id(p), p) for p in phase_unknown)[0::2]
                if d <= 300:
                    return p, d
            return None, "phase unclear"
        if not found:
            return None, "not in GujRERA"
        found.sort(key=lambda x: -x[0])
        if len(found) > 1 and found[0][0] - found[1][0] < 1 and found[0][2]["_w"] != found[1][2]["_w"]:
            return None, "ambiguous"
        return found[0][2], found[0][1]


def _same_area(a, b):
    a, b = a.lower().replace(" road", ""), b.lower().replace(" road", "")
    return a in b or b in a or a.split()[0] == b.split()[0]


def as_rent_listing(l):
    """The listing shape pricing.listing_stats reads, plus where it came from."""
    return {"bhk": l["bhk"], "price": l["price"], "sqft": l["sqft"], "psf": None, "furnished": l["furnished"],
            "floor": l["floor"], "posted": l["posted"], "posted_by": l["posted_by"], "poster": l.get("poster"), "tenants": l["tenants"],
            "url": l["url"]}


def attach(projects, listings):
    """Put rental listings on GujRERA projects; return (rental-only societies, counts)."""
    listings = dedupe(listings)
    m = Matcher(projects)
    counts = collections.Counter()
    extra = collections.defaultdict(list)
    for l in listings:
        if not l["society"]:
            counts["no society named"] += 1
            continue
        p, how = m.match(l)
        if p is None:
            counts[how] += 1
            if how == "not in GujRERA" and l.get("lat"):
                extra[l["society"].strip().lower()].append(l)
            continue
        counts["matched"] += 1
        p.setdefault("rent_listings", []).append(as_rent_listing(l))
    rental_only = []
    for key, ls in extra.items():
        first = ls[0]
        kinds = collections.Counter(KIND.get(l["kind"], "apartment") for l in ls)
        rental_only.append({
            "mb_id": f"mbs{first.get('mb_society_id') or joined(key)[:24]}", "source": "magicbricks-rent",
            "name": first["society"].strip(), "locality": first.get("locality"),
            "lat": statistics.median(l["lat"] for l in ls), "lng": statistics.median(l["lng"] for l in ls),
            "kind": kinds.most_common(1)[0][0], "config_text": "Society seen in Magicbricks rental listings, not in GujRERA",
            "status": "Not in GujRERA (likely built before 2017)", "url": first["url"],
            "rent_listings": [as_rent_listing(l) for l in ls],
        })
    for p in projects + rental_only:
        rl = p.get("rent_listings") or []
        if rl:
            p["rent_count"] = len(rl)
            p["rent_tenants"] = dict(collections.Counter(l["tenants"] for l in rl if l["tenants"]))
            p["rent_posted_by"] = dict(collections.Counter(l["posted_by"] for l in rl if l["posted_by"]))
            newest = sorted(rl, key=lambda l: l["posted"] or "", reverse=True)
            p["rent_links"] = [l["url"] for l in newest[:5] if l["url"]]
            p["rentals"] = [{k: l.get(k) for k in ("bhk", "price", "sqft", "furnished", "floor", "posted", "posted_by", "poster", "tenants", "url")}
                            for l in newest[:12]]
    counts["rental-only societies"] = len(rental_only)
    return rental_only, counts
