"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city>      # all list pages -> out/<city>/mb_index.json
       python mb_crawl.py harvest <city>   # no project index (Dehradun): sale and rent listing pages, then
                                           # each project page's related projects -> out/<city>/mb_index.json
       python mb_crawl.py projects <city>  # every project page -> out/<city>/mb_projects.json
<city> is a key in data/cities.json (default gurgaon).
"""
import gzip
import hashlib
import json
import pathlib
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


LISTING_PAGES = ["flats-in-{c}-for-sale-pppfs", "villa-for-sale-in-{c}-pppfs", "flats-for-rent-in-{c}-pppfr",
                 "property-for-rent-in-{c}-pppfr"]


def crawl_harvest(max_pages=60, dry_pages=8):
    """Find projects through listing pages and related-project links, for cities Magicbricks gives no index."""
    slug = CFG["magicbricks"]
    links = {}
    for pattern in LISTING_PAGES:
        base, dry = "https://www.magicbricks.com/" + pattern.format(c=slug), 0
        for n in range(1, max_pages + 1):
            html = fetch(base if n == 1 else f"{base}/page-{n}")
            found = mb_parse.pdp_links(html or "", slug)
            new = {k: v for k, v in found.items() if k not in links}
            links.update(new)
            dry = 0 if new else dry + 1
            print(f"{pattern.format(c=slug)} page {n}: +{len(new)} = {len(links)} projects", flush=True)
            if not found or dry >= dry_pages:  # past the last page, or no new projects for a while
                break
    from_listings = len(links)
    projects, queue = {}, list(links)
    while queue:
        key = queue.pop(0)
        html = fetch(links[key])
        p = mb_parse.page_to_project(html, links[key]) if html else None
        if p and (p.get("city_name") or CFG["name"]).lower() == CFG["name"].lower():
            projects[p["mb_id"]] = p
        for k, v in mb_parse.pdp_links(html or "", slug).items():
            if k not in links:
                links[k] = v
                queue.append(k)
        if len(projects) % 25 == 0:
            print(f"project pages: {len(projects)} kept, {len(queue)} queued", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "mb_index.json").write_text(json.dumps(list(projects.values()), indent=0))
    print(f"from listings {from_listings}, from project links {len(links) - from_listings}, kept {len(projects)}")


def crawl_projects():
    index = json.loads((OUT / "mb_index.json").read_text())
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
    {"list": crawl_list, "harvest": crawl_harvest, "projects": crawl_projects}[sys.argv[1]]()
