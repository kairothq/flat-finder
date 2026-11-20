#!/usr/bin/env node
// flatfinder: search the Flat Finder data from a terminal. Same filter logic as the website.
import { readFile, realpath } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { DEFAULT_CRITERIA, NEAR, feetLabel, formatINR, matchSociety, priceFor } from '../web/src/filters.js';

// Where the data is fetched from and where the printed links point. FF_SITE moves both: a fork
// publishes its own cities, and `FF_SITE=http://localhost:4173` reads the build in front of you.
const SITE = (process.env.FF_SITE || 'https://flat-finder.pages.dev').replace(/\/+$/, '');

const HELP = `flatfinder: find housing societies that fit

  npx github:kairothq/flat-finder [options]

  --city <id>            gurgaon (default), more as they are added
  --bhk 3,4              BHK types
  --min-bedroom 11'3x12'3   every bedroom must clear both sides (also 11.25x12.25)
  --min-sqft 1620        minimum unit size (super area where known)
  --max-price 3cr        budget to buy, e.g. 90L or 3cr
  --rent                 renting instead of buying
  --max-rent 80k         monthly rent budget
  --amenity squash,pool  squash pool gym club tennis badminton jogging kids
  --near park,metro      ${Object.entries(NEAR).map(([k, n]) => `${k} (${n.m} m)`).join(', ')}
  --type apartment       apartment, "builder floor", villa, plot (comma separated)
  --ready                ready to move only
  --likely               also show "likely" (rooms read so far pass)
  --limit 30             rows to print
  --json                 print JSON
  --data <file>          use a local <city>.json instead of the website
`;

export function parseFeet(s) {
  const m = String(s).trim().match(/^(\d+(?:\.\d+)?)(?:'\s*(\d+(?:\.\d+)?)"?)?$/);
  if (!m) throw new Error(`cannot read length "${s}"`);
  return m[2] !== undefined ? +m[1] + +m[2] / 12 : +m[1];
}

export function parsePrice(s) {
  const m = String(s).trim().toLowerCase().match(/^(\d+(?:\.\d+)?)\s*(cr|crore|l|lac|lakh|k)?$/);
  if (!m) throw new Error(`cannot read price "${s}"`);
  const n = +m[1];
  return m[2]?.startsWith('c') ? n * 1e7 : m[2] === 'k' ? n * 1e3 : m[2] ? n * 1e5 : n;
}

export function parseArgs(argv) {
  const o = { city: 'gurgaon', crit: structuredClone(DEFAULT_CRITERIA), limit: 30, json: false, likely: false, data: null };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i], v = () => argv[++i];
    if (a === '--city') o.city = v();
    else if (a === '--bhk') o.crit.bhk = v().split(',').map(Number);
    else if (a === '--min-bedroom') { const [x, y] = v().split(/x|×/i); o.crit.room = { a: parseFeet(x), b: parseFeet(y) }; }
    else if (a === '--min-sqft') o.crit.minSqft = +v();
    else if (a === '--max-price') o.crit.maxPrice = parsePrice(v());
    else if (a === '--rent') o.crit.mode = 'rent';
    else if (a === '--max-rent') { o.crit.mode = 'rent'; o.crit.maxRent = parsePrice(v()); }
    else if (a === '--amenity') o.crit.amenities = v().split(',');
    // The web app and the MCP server both filter on what is nearby and the CLI could not, though it
    // shares the code that does it. An unknown key is an error rather than a filter that quietly
    // matches nothing: isNear would read NEAR[key].kinds off undefined and crash on the first society.
    else if (a === '--near') o.crit.near = v().split(',').map((k) => {
      const key = k.trim().toLowerCase();
      if (!Object.hasOwn(NEAR, key)) throw new Error(`unknown --near "${k}". Try: ${Object.keys(NEAR).join(', ')}`);
      return key;
    });
    else if (a === '--type') o.crit.kinds = v().split(',');
    else if (a === '--ready') o.crit.ready = true;
    else if (a === '--likely') o.likely = true;
    else if (a === '--limit') o.limit = +v();
    else if (a === '--json') o.json = true;
    else if (a === '--data') o.data = v();
    else if (a === '-h' || a === '--help') o.help = true;
    else throw new Error(`unknown option ${a}`);
  }
  return o;
}

export function search(city, o) {
  const keep = o.likely ? ['match', 'likely'] : ['match'];
  return city.societies
    .map((s) => ({ s, v: matchSociety(s, o.crit) }))
    .filter((r) => keep.includes(r.v))
    .sort((a, b) => (b.v === 'match') - (a.v === 'match') || b.s.verified - a.s.verified || (b.s.units || 0) - (a.s.units || 0));
}

function smallestRoom(s) {
  const rooms = s.unit_types.flatMap((u) => u.bedrooms || []);
  if (!rooms.length) return '';
  const r = rooms.reduce((m, x) => (x[0] < m[0] ? x : m));
  return `${feetLabel(r[0])} x ${feetLabel(r[1])}`;
}

const money = (p, mode) => (p ? `${p.estimated ? '~' : ''}${formatINR(p.value)}${mode === 'rent' ? '/mo' : ''}` : '');

// The city the data says it is, not the one --city defaulted to: `--data hyderabad.json` printed Gurugram
// links, so following one opened the wrong city and the society id resolved to nothing.
export const linkFor = (city, s, fallback) => `${SITE}/?city=${city.city?.id || fallback}&open=${s.id}`;

// A city the site does not publish used to end the run on `Unexpected token '<', "<!doctype "`, with
// no mention of the city or the url. The status is no help: both deployments serve the app's own
// index.html, with a 200, for any path under /data that does not exist. So judge the body, and say
// which cities there are.
async function fetchCity(id) {
  const url = `${SITE}/data/${encodeURIComponent(id)}.json`;
  const res = await fetch(url).catch((e) => { throw new Error(`could not reach ${SITE}: ${e.message}`); });
  try {
    const city = JSON.parse(await res.text());
    if (city?.societies) return city;
  } catch { /* not json at all: the index.html fallback */ }
  const known = await fetch(`${SITE}/data/cities.json`).then((r) => r.json()).catch(() => null);
  const list = known ? ` Cities on ${SITE}: ${Object.keys(known).join(', ')}.` : '';
  throw new Error(`no city data at ${url} (HTTP ${res.status}).${list} Use --data <file> for a local build, or set FF_SITE to read another deployment.`);
}

async function main() {
  const o = parseArgs(process.argv.slice(2));
  if (o.help) return console.log(HELP);
  const city = o.data ? JSON.parse(await readFile(o.data, 'utf8')) : await fetchCity(o.city);
  const rows = search(city, o);
  if (o.json) return console.log(JSON.stringify(rows.slice(0, o.limit).map(({ s, v }) => ({ verdict: v, ...s })), null, 2));
  console.log(`${rows.length} societies in ${city.city.name}${o.likely ? ' (including likely)' : ''}\n`);
  const table = rows.slice(0, o.limit).map(({ s, v }) => ({
    society: s.name.slice(0, 32), area: (s.locality || '').slice(0, 22), verdict: v + (s.verified ? '*' : ''),
    'smallest bedroom': smallestRoom(s), [o.crit.mode === 'rent' ? 'rent from' : 'price from']: money(priceFor(s, o.crit.mode, o.crit.bhk), o.crit.mode), link: linkFor(city, s, o.city),
  }));
  console.table(table);
  console.log('~ = our estimate from the rent-to-price ratio, not a listing.');
  console.log('* verified from brochures or RERA plans. Unit rows without room sizes are "not checked yet" and never shown as matches.');
}

const self = fileURLToPath(import.meta.url);
const invoked = process.argv[1] ? await realpath(process.argv[1]).catch(() => process.argv[1]) : '';
if (invoked === self) main().catch((e) => { console.error(e.message); process.exit(1); });
