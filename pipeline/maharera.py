"""Match each society to its MahaRERA registration(s), from MahaRERA's public project search.

usage: python maharera.py <city>   -> data/verified/<city>-maharera.json (registrations in or near the city)
       then build_city.py <city> matches societies to them and fixes portal pins that fall outside the city
<city> needs "maharera_districts" in data/cities.json (MahaRERA district codes, e.g. Thane 517, Palghar 990).

Only the public search list is read (registration number, name, promoter, pincode, location, last
modified, link). MahaRERA's project detail pages, where floor plans are filed, sit behind a captcha:
we do not fetch them. Each society card links to its filing so a person can open the plans (skill, Job 3).
Pages are fetched one per second and cached.
"""
import json
import pathlib
import re
import subprocess
import sys
import time

import geo

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "maharera"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
SEARCH = ("https://www.maharera.maharashtra.gov.in/projects-search-result?project_name=&project_location=&project_completion_date="
          "&project_state=27&project_district={d}&carpetAreas=&completionPercentages=&project_division=&op=Search&page={p}")
NAME_MATCH_M = 600   # a name match must also be this close (MahaRERA pins are approximate)


def get(url, cache_name):
    f = CACHE / cache_name
    if f.exists() and f.stat().st_size > 5000:
        return f.read_text(errors="ignore")
    for attempt in range(3):
        r = subprocess.run(["curl", "-sL", "-A", UA, "--max-time", "60", url], capture_output=True)
        html = r.stdout.decode("utf-8", "ignore")
        time.sleep(1)
        if r.returncode == 0 and ("row shadow" in html or "Unable to find records" in html):
            CACHE.mkdir(parents=True, exist_ok=True)
            f.write_text(html)
            return html
        print("  retry", attempt + 1, url, flush=True)
        time.sleep(5 * (attempt + 1))
    return ""


def _text(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).replace("&amp;", "&").strip()


def parse_rows(html):
    """One dict per project card on a search result page."""
    out = []
    for block in html.split("row shadow p-3")[1:]:
        reg = re.search(r"#\s*([A-Z0-9]{8,})", block)
        name = re.search(r'<h4[^>]*>(.*?)</h4>', block, re.S)
        promoter = re.search(r'<p class="darkBlue[^"]*">(.*?)</p>', block, re.S)
        ll = re.search(r"query=(-?[\d.]+),(-?[\d.]+)", block)
        view = re.search(r'href="(https://maharerait\.maharashtra\.gov\.in/public/project/view/\d+)"', block)
        field = lambda k: (re.search(rf">{k}</div>\s*<p>([^<]*)</p>", block) or [None, None])[1]
        if not (reg and name):
            continue
        lat, lng = (float(ll.group(1)), float(ll.group(2))) if ll else (None, None)
        out.append({"reg": reg.group(1), "name": _text(name.group(1)), "promoter": _text(promoter.group(1)) if promoter else None,
                    "lat": lat if lat else None, "lng": lng if lng else None, "pincode": field("Pincode"),
                    "district": field("District"), "last_modified": field("Last Modified"),
                    "url": view.group(1) if view else None})
    return out


def total_pages(html):
    m = re.search(r"of (\d+) ", html)
    return int(m.group(1)) if m else 1


def registrations(district):
    first = get(SEARCH.format(d=district, p=1), f"{district}-1.html")
    pages = total_pages(first)
    rows = parse_rows(first)
    for p in range(2, pages + 1):
        rows += parse_rows(get(SEARCH.format(d=district, p=p), f"{district}-{p}.html"))
        if p % 50 == 0 or p == pages:
            print(f"district {district}: page {p}/{pages}, {len(rows)} registrations", flush=True)
    return rows


def reg_ids(text):
    """MahaRERA numbers in a portal field like 'P51800008104 / P51800008105'."""
    return set(re.findall(r"\b(P[0-9]{11}|PC[0-9]{11,13}|PR[0-9A-Z]{8,})\b", (text or "").upper()))


STOP = {"the", "of", "and", "by", "at", "in", "no", "co", "op", "chs", "ltd", "phase", "project", "building", "bldg", "new"}
ROMAN = {"i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}


def strict_tokens(name):
    """Words of a name for MahaRERA matching. Unlike build_city.tokens, building-type words (tower, heights, park,
    residency) and wing letters stay, so "Krishna Tower" never matches "Krishna Heights"."""
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return {ROMAN.get(w, w) for w in words if w not in STOP}


def distinctive(name):
    from build_city import tokens
    return bool(tokens(name))


def match(society, regs, by_reg):
    """Registrations for a society: by the portal's RERA numbers first, else by name and distance."""
    ids = reg_ids(society.get("rera_id"))
    hits = [by_reg[i] for i in sorted(ids) if i in by_reg]
    if hits:
        return hits, "rera number"
    want = strict_tokens(society["name"])
    if not want or not distinctive(society["name"]):
        return [], None
    pt = (society["lng"], society["lat"])
    found = []
    for r in regs:
        if not r["lat"]:
            continue
        have = strict_tokens(r["name"])
        # every distinctive word of the portal name must be in the MahaRERA name (MahaRERA adds phase / wing words)
        if want <= have and geo.dist_m(pt, (r["lng"], r["lat"])) <= NAME_MATCH_M:
            found.append(r)
    return found, "name and location" if found else None


def relocate(project, regs, by_reg, box):
    """(lat, lng, how) from MahaRERA for a portal project whose own pin is outside the city box, or None.

    By the project's RERA number; else by a name whose distinctive words equal exactly one registration's in the area.
    """
    south, west, north, east = box
    inside = lambda r: r["lat"] and south < r["lat"] < north and west < r["lng"] < east
    hits = [by_reg[i] for i in sorted(reg_ids(project.get("rera_id"))) if i in by_reg and inside(by_reg[i])]
    if hits:
        return hits[0]["lat"], hits[0]["lng"], "MahaRERA pin, matched by RERA number " + hits[0]["reg"]
    want = strict_tokens(project.get("name")) if distinctive(project.get("name")) else set()
    same = [r for r in regs if inside(r) and want and strict_tokens(r["name"]) == want]
    if len(same) == 1 or (same and max(geo.dist_m((a["lng"], a["lat"]), (b["lng"], b["lat"])) for a in same for b in same) < 300):
        return same[0]["lat"], same[0]["lng"], "MahaRERA pin, matched by name " + same[0]["reg"]
    return None


def load(city):
    """Registrations saved for a city (empty if maharera.py has not been run)."""
    f = ROOT.parent / "data" / "verified" / f"{city}-maharera.json"
    regs = json.loads(f.read_text())["registrations"] if f.exists() else []
    return regs, {r["reg"]: r for r in regs}


def main(city):
    cfg = json.loads((ROOT.parent / "data" / "cities.json").read_text())[city]
    south, west, north, east = cfg.get("located_bbox") or cfg["bbox"]
    regs = []
    for d in cfg["maharera_districts"]:
        regs += registrations(d)
    pad = 0.05
    local = [r for r in regs if r["lat"] and south - pad < r["lat"] < north + pad and west - pad < r["lng"] < east + pad]
    print("MahaRERA registrations", len(regs), "in or near the city area", len(local), flush=True)
    path = ROOT.parent / "data" / "verified" / f"{city}-maharera.json"
    path.write_text(json.dumps({"source": "MahaRERA public project search, https://maharera.maharashtra.gov.in/projects-search-result",
                                "registrations": local}, indent=0))
    print("wrote", path, "- run build_city.py", city, "to match societies")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "mira-road")
