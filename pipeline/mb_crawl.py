"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city>          # all list pages -> out/<city>/mb_index.json
       python mb_crawl.py mapped <city>        # exact OSM residential-area name matches -> mb_index.json
       python mb_crawl.py cached <city>        # keep mapped project pages already available in the local source cache
       python mb_crawl.py projects <city>      # mapped project pages -> out/<city>/mb_projects.json (after mapped)
<city> is a key in data/cities.json (default gurgaon).
"""
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.request

import mb_parse

ROOT = pathlib.Path(__file__).parent
CACHE = ROOT / "cache" / "mb"
OUT = ROOT / "out"
CITIES = json.loads((ROOT.parent / "data" / "cities.json").read_text())
CITY = next((a for a in sys.argv[1:] if a in CITIES), "gurgaon")
CFG = CITIES[CITY]
LIST_URL = "https://www.magicbricks.com/residential-projects-in-" + CFG["magicbricks"] + "-nprid/page-{}"
OUT = OUT / CITY
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
DELAY = 1.0


def project_cache_path(url, cache_dir=CACHE):
    return cache_dir / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = project_cache_path(url)
    if f.exists() and f.stat().st_size > 2000:
        return gzip.decompress(f.read_bytes()).decode("utf-8", "ignore")
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
            f.write_bytes(gzip.compress(html.encode("utf-8"), 9))
            time.sleep(DELAY)
            return html
        except Exception as e:  # network hiccup: back off and retry
            print("  retry", attempt + 1, url, e, flush=True)
            time.sleep(5 * (attempt + 1))
    return None


def crawl_list():
    first = fetch(LIST_URL.format(1))
    total = mb_parse.parse_total(first)
    pages = -(-total // 20)
    projects = {}
    for n in range(1, pages + 1):
        html = fetch(LIST_URL.format(n))
        if not html:
            continue
        for c in mb_parse.parse_list_page(html):
            projects[c["psmid"]] = mb_parse.card_to_project(c)
        print(f"list {n}/{pages}: {len(projects)} projects", flush=True)
        if n % 20 == 0 or n == pages:
            OUT.mkdir(parents=True, exist_ok=True)
            (OUT / "mb_index.json").write_text(json.dumps(list(projects.values()), indent=0))
    print("total reported", total, "collected", len(projects))


def normal_name(value):
    return " ".join(re.findall(r"[a-z0-9]+", (value or "").lower()))


def mapped_project_candidates(projects, areas):
    """Keep portal projects with an exact named OSM residential-area match."""
    area_names = {normal_name(a.get("properties", {}).get("name")) for a in areas}
    area_names.discard("")
    return [p for p in projects if normal_name(p.get("name")) in area_names]


def select_mapped_projects():
    index = json.loads((OUT / "mb_index.json").read_text(encoding="utf-8"))
    areas_path = OUT / "osm_areas.geojson"
    areas = json.loads(areas_path.read_text(encoding="utf-8"))["features"]
    selected = mapped_project_candidates(index, areas)
    (OUT / "mb_index.json").write_text(json.dumps(selected, separators=(",", ":")), encoding="utf-8")
    print(f"mapped projects {len(selected)}/{len(index)} by exact OSM residential-area name", flush=True)


def select_cached_projects():
    index = json.loads((OUT / "mb_index.json").read_text(encoding="utf-8"))
    selected = [p for p in index if project_cache_path(p["url"]).exists() and project_cache_path(p["url"]).stat().st_size > 2000]
    (OUT / "mb_index.json").write_text(json.dumps(selected, separators=(",", ":")), encoding="utf-8")
    print(f"cached project pages {len(selected)}/{len(index)}", flush=True)


def crawl_projects(index_file="mb_index.json"):
    index = json.loads((OUT / index_file).read_text(encoding="utf-8"))
    from concurrent.futures import ThreadPoolExecutor

    def one(p):
        html = fetch(p["url"])
        try:
            detail = mb_parse.parse_project_page(html) if html else {}
        except Exception as e:
            print("  parse failed", p["url"], e, flush=True)
            detail = {}
        return {**p, **{k: v for k, v in detail.items() if v not in (None, [], "")}}

    out = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, merged in enumerate(ex.map(one, index), 1):
            out.append(merged)
            if i % 100 == 0 or i == len(index):
                print(f"project {i}/{len(index)}", flush=True)
                (OUT / "mb_projects.json").write_text(json.dumps(out, indent=0))


if __name__ == "__main__":
    {"list": crawl_list, "mapped": select_mapped_projects, "cached": select_cached_projects,
     "projects": crawl_projects}[sys.argv[1]]()
