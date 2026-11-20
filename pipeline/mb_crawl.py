"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city>      # all list pages -> out/<city>/mb_index.json
       python mb_crawl.py sitemap <city>   # or, for cities with no list page, from sitemaps (needs "sitemap_city")
       python mb_crawl.py projects <city>  # every project page -> out/<city>/mb_projects.json
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


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")
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
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mb_index.json").write_text(json.dumps(list(projects.values()), indent=0))
    print("total reported", total, "collected", len(projects))


SITEMAP_INDEX = "https://www.magicbricks.com/sitemap_index.xml"
# sitemaps that list project pages across all cities (pdp_amenities_1, pdp_floor-plan_1, villas_projects, ...)
SHARED_SITEMAP = re.compile(r"/(pdp_[a-z-]+_\d+|\w*[pP]rojects)\.xml\.gz$")
PAGE_SUFFIX = re.compile(r"-(floor-plan|amenities|reviews|brochure|photo-videos|rera-details)(?=-)")


def fetch_xml(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    raw = urllib.request.urlopen(req, timeout=60).read()
    time.sleep(DELAY)
    return (gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw).decode("utf-8", "ignore")


def sitemap_projects(urls, token):
    """Project page URLs for one city: ending '-<token>-pdpid-<hex>', sub-page suffixes removed, one per project."""
    out = {}
    for u in urls:
        m = re.fullmatch(rf"(https://www\.magicbricks\.com/.+-{re.escape(token)})-pdpid-([0-9a-f]+)", u.strip())
        if not m:
            continue
        mb_id = bytes.fromhex(m.group(2)).decode("ascii", "ignore").removeprefix("MB")
        slug = PAGE_SUFFIX.sub("", m.group(1))
        out.setdefault(mb_id, {"mb_id": mb_id, "from_sitemap": True, "name": slug.rsplit("/", 1)[1].replace("-", " ").title(),
                               "url": f"{slug}-pdpid-{m.group(2)}"})
    return out


def crawl_sitemap():
    """For cities with no -nprid list page (Delhi, Faridabad): build the index from Magicbricks' sitemaps."""
    token = CFG["sitemap_city"]
    index = re.findall(r"<loc>([^<]+)</loc>", fetch_xml(SITEMAP_INDEX))
    maps = [u for u in index if SHARED_SITEMAP.search(u) or any(u.endswith(f"/{s}.xml.gz") for s in CFG.get("sitemaps", []))]
    projects = {}
    for i, sm in enumerate(maps, 1):
        projects.update({k: v for k, v in sitemap_projects(re.findall(r"<loc>([^<]+)</loc>", fetch_xml(sm)), token).items()
                         if k not in projects})
        print(f"sitemap {i}/{len(maps)} {sm.rsplit('/', 1)[1]}: {len(projects)} projects", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mb_index.json").write_text(json.dumps(list(projects.values()), indent=0))
    print("collected", len(projects))


def crawl_projects():
    index = json.loads((OUT / "mb_index.json").read_text())
    from concurrent.futures import ThreadPoolExecutor

    def one(p):
        html = fetch(p["url"])
        try:
            detail = mb_parse.parse_project_page(html) if html else {}
            # list-card fields the index lacks (sitemap cities); never overrides what a list page gave
            card = {k: v for k, v in (mb_parse.parse_project_card(html) if html else {}).items() if not p.get(k) or p.get("from_sitemap")}
        except Exception as e:
            print("  parse failed", p["url"], e, flush=True)
            detail, card = {}, {}
        return {**p, **{k: v for k, v in {**card, **detail}.items() if v not in (None, [], "")}}

    out = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, merged in enumerate(ex.map(one, index), 1):
            out.append(merged)
            if i % 100 == 0 or i == len(index):
                print(f"project {i}/{len(index)}", flush=True)
                (OUT / "mb_projects.json").write_text(json.dumps(out, indent=0))


if __name__ == "__main__":
    {"list": crawl_list, "sitemap": crawl_sitemap, "projects": crawl_projects}[sys.argv[1]]()
