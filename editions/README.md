# Editions: one city on its own domain

An edition is the normal Flat Finder site cut down to one city, so a city partner can host it on their own subdomain (for example `flats.uttarakhandhub.com`). It is the same code as the main site, with no fork of the UI. An edition:

- ships only that city's data files, so the city picker disappears;
- sets its own page title, description, panel heading and credit link from `editions/<name>.json`;
- can carry a partner's **registered sales** layer (`<city>-registered.json`), which adds a "Registered sales" block to every society card and a `registered_sales` field to `get_society` in the `/mcp` connector. Without the file the site works as before.

## Build

```bash
cd pipeline
python3 mb_crawl.py harvest dehradun && python3 mb_crawl.py projects dehradun   # no project index page in Dehradun
python3 osm_fetch.py dehradun
python3 build_city.py dehradun

cd ../web
npm run edition -- dehradun --registered "/path/to/dehradun-registered.json"
```

The result is `web/dist-editions/dehradun/`, a static folder.

## Host on a subdomain

**Cloudflare Pages (recommended).** It runs the `/mcp` connector too.

```bash
cd web
npx wrangler login                       # once, in your own browser
npx wrangler pages project create dehradun-flats --production-branch main
npx wrangler pages deploy dist-editions/dehradun --project-name dehradun-flats
```

Then go to Pages → dehradun-flats → Custom domains → add `flats.<your domain>`. At your DNS host, add the CNAME it shows (`flats` → `dehradun-flats.pages.dev`).

**Any static host (for example Caddy on a VPS).** Copy the folder and serve it. The map and search work, but `/mcp` does not, because it is a Cloudflare Pages Function.

```
flats.example.com {
	root * /srv/dehradun-flats
	file_server
	encode zstd gzip
}
```

`"noindex": true` in the edition file writes a `robots.txt` that blocks search engines. Remove it when the site is ready to be found.

## A RERA edition (profile "rera")

`"profile": "rera"` in an edition file turns the site into a map of every project on a state RERA register: the same map, search, list, tour and card, with the flat filters (Buy/Rent, BHK, bedrooms, budget, amenities, nearby) replaced by project type, district and registration validity, and a card showing the register entry (number, dates, promoter, units, land, address) and the registered sales. See `web/src/rera.js`.

Its data is not built here. The land-records partner builds it in Flat Finder's format and passes the folder:

```bash
npm run edition -- uttarakhand-rera --data "/path/to/rera-finder"
npx wrangler pages project create uk-rera --production-branch main
npx wrangler pages deploy dist-editions/uttarakhand-rera --project-name uk-rera
```

Each project is a "society" with an extra `rera` object; `editions/uttarakhand-rera.json` holds the page wording.

## The registered-sales file

The land-records partner builds this file, and it is never committed here: this repo is public, and the layer belongs to the partner. It holds aggregates per society id (`s<magicbricks id>`) only: sale counts by year, median and top registered ₹/sq ft from 5 or more deeds, the registry valuation and turnover. It holds no names, flat numbers or single deeds. See `web/src/registered.js` for the fields the card reads.

## Several cities in one edition

Give the edition a `cities` map (id to name) beside `city`, the one the site opens on. The city picker in the top bar switches between them.
Pass `--registered <folder>` and each city's `<city>-registered.json` is picked up from that folder. `uttarakhand-towns.json` is the example.

    node edition.mjs uttarakhand-towns --registered path/to/society-prices

Each city needs its data first: `python pipeline/osm_fetch.py <city>` then `python pipeline/build_city.py <city>`.

## A branded edition

`"brand": "uttarakhandhub"` puts the host site's look over Flat Finder: its colours and fonts, a top bar with its logo and the search box,
price pills on the map, result cards with a heart to save, and a "Show N societies" button. `"product"` is the name shown beside the logo.
A brand is one entry in `web/src/brand.js` (wordmark, logo file in `web/public/brand/`, map colours); the styling is `web/src/brand.css`.
Editions without `brand` keep the original look.
