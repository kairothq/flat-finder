"""Live rental listings for a whole city from Magicbricks search pages (for cities whose societies come from GujRERA,
where there are no Magicbricks project pages to carry listings).

usage: python mb_rent.py <city>   -> out/<city>/mb_rent.json
Polite and cached like mb_crawl.py (same fetch and cache). Search order can shift between pages, so it keeps paging
past the expected count until a few pages in a row bring nothing new, and reports coverage against Magicbricks' total.
"""
import json
import re
import sys

import mb_crawl
import mb_parse

SEARCH = "https://www.magicbricks.com/property-for-rent-in-{slug}-pppfr"
_DEC = json.JSONDecoder()


def parse_search_page(html):
    """Rental listing records embedded in a Magicbricks search page."""
    found = {}
    for m in re.finditer(r'"encId":', html or ""):
        j = html.rfind("{", 0, m.start())
        while j > 0:
            try:
                obj, _ = _DEC.raw_decode(html[j:])
                if "encId" in obj and "price" in obj:
                    found[obj["encId"]] = obj
                    break
            except ValueError:
                pass
            j = html.rfind("{", 0, j)
    return list(found.values())


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def poster(r):
    """Who posted it, as Magicbricks shows it: an agent's firm in full, an owner as initial and surname ("R. Shah")."""
    if (r.get("userType") or "").lower() == "owner":
        parts = [w for w in re.findall(r"[A-Za-z]+", r.get("oname") or "")]
        if not parts:
            return None
        return (parts[0][0].upper() + ". " + parts[-1].capitalize()) if len(parts) > 1 else parts[0].capitalize()
    firm = (r.get("caCompNameD") or r.get("oname") or "").strip()
    return " ".join(w.capitalize() if w.isupper() else w for w in firm.split()) or None


def to_listing(r):
    """One rental listing: what it is, where, the rent, and the society it says it is in."""
    base = mb_parse._listing(r)
    path = (r.get("url") or "").lstrip("/")
    return {
        "id": r["encId"],
        "society": (r.get("prjname") or "").strip() or None,
        "mb_society_id": r.get("psmid"),
        "locality": r.get("lmtDName"),
        "lat": _float(r.get("pmtLat")), "lng": _float(r.get("pmtLong")),
        "kind": r.get("propTypeD"),
        "bhk": base["bhk"], "price": base["price"], "sqft": base["sqft"], "furnished": base["furnished"], "floor": base["floor"],
        "posted": base["posted"],
        "posted_by": r.get("userType"),
        "poster": poster(r),
        "tenants": r.get("tenantsPreference") or None,
        "url": "https://www.magicbricks.com/propertyDetails/" + path if path else None,
    }


def main(city):
    cfg = mb_crawl.CITIES[city]
    slug = cfg.get("magicbricks") or city
    base = SEARCH.format(slug=slug)
    first = mb_crawl.fetch(base)
    total = mb_parse.parse_total(first) or 0
    listings = {r["encId"]: r for r in parse_search_page(first)}
    expected = -(-total // 30)
    page, dry = 2, 0
    while dry < 3 and page <= expected * 2:
        html = mb_crawl.fetch(f"{base}/page-{page}")
        new = [r for r in parse_search_page(html) if r["encId"] not in listings]
        listings.update({r["encId"]: r for r in new})
        dry = dry + 1 if not new else 0
        print(f"page {page}: +{len(new)} -> {len(listings)} of {total}", flush=True)
        page += 1
    rows = [to_listing(r) for r in listings.values() if r.get("price")]
    out = mb_crawl.ROOT / "out" / city
    out.mkdir(parents=True, exist_ok=True)
    (out / "mb_rent.json").write_text(json.dumps(rows, indent=0))
    named = sum(1 for r in rows if r["society"])
    print(f"wrote {len(rows)} rental listings ({len(rows) / max(total, 1):.0%} of the {total} Magicbricks reports), {named} name a society")


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a in mb_crawl.CITIES), "vadodara"))
