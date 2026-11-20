"""Polite, cached, resumable Magicbricks crawler.

usage: python mb_crawl.py list <city>      # all list pages -> out/<city>/mb_index.json
       python mb_crawl.py projects <city>  # every project page -> out/<city>/mb_projects.json
<city> is a key in data/cities.json (default gurgaon).
"""
import gzip
import hashlib
import json
import pathlib
import sys
import threading
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
DELAY = 1.0  # seconds between requests for the whole crawl, not for each worker
WORKERS = 3  # overlapping fetches; the gate below sets the request rate, this only hides latency
EVERY = 500  # projects between checkpoints: a city the size of Hyderabad rewrites ~140 MB each time
# A block or captcha page answers 200 and looks like any other page, so only the body gives it away.
BLOCK = ("access denied", "captcha", "unusual traffic", "request unsuccessful", "verify you are a human")
STATE = "window.SERVER_PRELOADED_STATE_"  # every real list and project page carries it

_gate = threading.Lock()
_slot = 0.0  # monotonic time the next request may leave
stop = threading.Event()  # set when the site blocks us, so the other workers stop asking


class Blocked(Exception):
    """The site refused us. Report it and stop: never retry around it, never cache it."""


def wait_turn():
    """Hand out one request slot per DELAY seconds, shared by every worker.

    The sleep used to sit after each fetch inside the worker, so three threads meant three requests a
    second (1.7/s measured, the rest of the budget eaten by fetch latency) against a docstring that
    promises one. Reserving the slot under the lock and sleeping outside it keeps fetches overlapping.
    """
    global _slot
    with _gate:
        now = time.monotonic()
        _slot = max(now, _slot) + DELAY
        wait = _slot - DELAY - now
    time.sleep(max(0.0, wait))


def read_cache(f):
    """The cached page, or None when the file cannot be read.

    A half-written cache file is bigger than the size test but fails to decompress, and that used to
    raise out of the worker and kill a run with hours of work behind it. Drop it and fetch it again.
    """
    try:
        return gzip.decompress(f.read_bytes()).decode("utf-8", "ignore")
    except Exception as e:
        print("  unreadable cache file, refetching:", f.name, e, flush=True)
        f.unlink(missing_ok=True)
        return None


def is_block(html):
    """True when the site served a block or captcha page instead of the thing we asked for.

    These answer 200, so no status code reveals them. Caching one would poison the cache for good (a
    real block page clears the 2 KB size test) and parse to all-nulls merged into a record that looks
    exactly like a real project whose page happened to be thin.
    """
    return STATE not in html and any(s in html[:4000].lower() for s in BLOCK)


def write_atomic(f, data):
    """Write beside the file and rename, so a kill mid-write cannot leave a truncated file behind.

    mb_projects.json is read by the build with a bare json.loads, and serialising ~140 MB leaves a
    window long enough to catch: polling the old write_text caught the file at 0 bytes.
    """
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode())
    tmp.replace(f)


def fetch(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (hashlib.sha1(url.encode()).hexdigest() + ".html.gz")
    if f.exists() and f.stat().st_size > 2000:
        html = read_cache(f)
        if html is not None:
            return html  # a cache hit sends no request, so it takes no rate slot
    for attempt in range(3):
        try:
            wait_turn()
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            html = urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "ignore")
            if is_block(html):
                raise Blocked(url)
            write_atomic(f, gzip.compress(html.encode("utf-8"), 9))
            return html
        except Blocked:
            raise
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
    write_atomic(OUT / "mb_index.json", json.dumps(list(projects.values()), indent=0))
    print("total reported", total, "collected", len(projects))


def resume(f, index):
    """(projects an earlier run already parsed, keyed by url) and (rows this crawler did not write).

    The page cache means a restart costs no requests, but re-parsing a whole city costs half an hour,
    so a record that already carries a detail-page field is kept as it is. Rows whose url is not in
    the index belong to someone else -- build_hyderabad.py seeds this same file -- and are written
    back untouched: the crawl must not delete a society it did not create.
    """
    if not f.exists():
        return {}, []
    try:
        rows = json.loads(f.read_text())
    except Exception as e:
        print("  unreadable checkpoint, parsing again from the page cache:", e, flush=True)
        return {}, []
    urls = {p["url"] for p in index}
    # lat is read off the project page and is never on an index card, so it marks a parsed record
    return ({r["url"]: r for r in rows if r.get("url") in urls and r.get("lat")},
            [r for r in rows if r.get("url") not in urls])


def save(f, index, done, foreign):
    """The checkpoint, in index order, with the rows this crawl did not write last: build_city.dedupe
    keeps the first of two near-duplicates, which should be the crawled copy with the prices on it."""
    write_atomic(f, json.dumps([done[p["url"]] for p in index if p["url"] in done] + foreign, indent=0))


def crawl_projects():
    index = json.loads((OUT / "mb_index.json").read_text())
    f = OUT / "mb_projects.json"
    done, foreign = resume(f, index)
    todo = [p for p in index if p["url"] not in done]
    print(f"{len(index)} projects: {len(done)} already parsed, {len(todo)} to fetch"
          + (f", {len(foreign)} rows from another source kept" if foreign else ""), flush=True)

    def one(p):
        if stop.is_set():
            return None  # a block ended this run: stop asking, and publish nothing half-read
        try:
            html = fetch(p["url"])
        except Blocked:
            print("  blocked:", p["url"], flush=True)
            stop.set()
            return None
        try:
            detail = mb_parse.parse_project_page(html) if html else {}
        except Exception as e:
            print("  parse failed", p["url"], e, flush=True)
            detail = {}
        return {**p, **{k: v for k, v in detail.items() if v not in (None, [], "")}}

    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, merged in enumerate(ex.map(one, todo), 1):
            if merged:
                done[merged["url"]] = merged
            if i % EVERY == 0 or i == len(todo):
                print(f"project {i}/{len(todo)}", flush=True)
                save(f, index, done, foreign)
    save(f, index, done, foreign)
    if stop.is_set():
        print(f"stopped: the site blocked us, {len(index) - len(done)} projects still unread. Re-run "
              "later and it picks up from here -- nothing was worked around.", flush=True)


if __name__ == "__main__":
    try:
        {"list": crawl_list, "projects": crawl_projects}[sys.argv[1]]()
    except Blocked as e:
        sys.exit(f"blocked by the site at {e}: stopping instead of working around it")
