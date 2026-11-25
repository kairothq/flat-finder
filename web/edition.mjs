// Build one city as its own site, for hosting on its own domain (e.g. a city partner's subdomain).
//
//   node edition.mjs dehradun [--registered path/to/dehradun-registered.json]
//   node edition.mjs uttarakhand-rera --data path/to/folder   (the city's data files come from outside this repo)
//   node edition.mjs uttarakhand-towns --registered path/to/folder   (several cities: "cities" in the edition file,
//        and a folder holding each city's <city>-registered.json)
//
// Reads editions/<name>.json, runs the normal Vite build, then keeps only that city's data in
// dist-editions/<name>/, writes /data/edition.json (the site and the /mcp connector read it for the
// default city, title and credit) and sets the page title and description for search engines.
// Deploy the folder with `npx wrangler pages deploy dist-editions/<name> --project-name <project>`.
import { execFileSync } from 'node:child_process';
import { copyFileSync, cpSync, existsSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from 'node:fs';
import path from 'node:path';

const name = process.argv[2];
if (!/^[a-z0-9-]+$/.test(name || '')) throw new Error('usage: node edition.mjs <edition> [--registered <file>] [--data <folder>]');
const cfg = JSON.parse(readFileSync(path.join('..', 'editions', `${name}.json`), 'utf8'));
const city = cfg.city; // the city the site opens on
const cities = cfg.cities || { [city]: cfg.city_name }; // every city the edition carries, id -> name
const regArg = process.argv.indexOf('--registered');
const registered = regArg > 0 ? process.argv[regArg + 1] : null;
const dataArg = process.argv.indexOf('--data');
const dataDir = dataArg > 0 ? process.argv[dataArg + 1] : null;

for (const c of Object.keys(cities)) if (!existsSync(path.join(dataDir || 'public/data', `${c}.json`))) throw new Error(`public/data/${c}.json is missing: run pipeline/build_city.py ${c} first`);
const out = path.join('dist-editions', name);
execFileSync('npx', ['vite', 'build'], { stdio: 'inherit' });
rmSync(out, { recursive: true, force: true });
cpSync('dist', out, { recursive: true });

// only this city's data files
const data = path.join(out, 'data');
const ours = (f) => Object.keys(cities).some((c) => f.startsWith(`${c}.`) || f.startsWith(`${c}-`));
for (const f of readdirSync(data)) if (!ours(f)) rmSync(path.join(data, f));
if (dataDir) for (const f of readdirSync(dataDir)) if (ours(f)) copyFileSync(path.join(dataDir, f), path.join(data, f));
writeFileSync(path.join(data, 'cities.json'), JSON.stringify(Object.fromEntries(Object.entries(cities).map(([c, n]) => [c, { name: n }]))));
const { city: _city, city_name: _name, cities: _cities, description, noindex, ...edition } = cfg;
writeFileSync(path.join(data, 'edition.json'), JSON.stringify({ city, ...edition }));
if (registered && statSync(registered).isDirectory()) {
  for (const c of Object.keys(cities)) if (existsSync(path.join(registered, `${c}-registered.json`))) copyFileSync(path.join(registered, `${c}-registered.json`), path.join(data, `${c}-registered.json`));
} else if (registered) copyFileSync(registered, path.join(data, `${city}-registered.json`));
for (const c of Object.keys(cities)) if (!existsSync(path.join(data, `${c}-registered.json`))) console.warn(`no ${c}-registered.json: ${c} builds without registered sales`);

// title and description in the HTML itself, so search engines and link previews see them
const html = path.join(out, 'index.html');
const esc = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
writeFileSync(html, readFileSync(html, 'utf8')
  .replace(/<title>[^<]*<\/title>/, `<title>${esc(cfg.title)}</title>`)
  .replace(/<meta name="description" content="[^"]*">/, `<meta name="description" content="${esc(description)}">`
    + (cfg.brand ? `\n  <link rel="icon" type="image/svg+xml" href="/brand/${cfg.brand}.svg">\n  <meta name="theme-color" content="${cfg.theme_color || '#0d2b45'}">` : '')));
if (noindex) writeFileSync(path.join(out, 'robots.txt'), 'User-agent: *\nDisallow: /\n');
const withReg = Object.keys(cities).filter((c) => existsSync(path.join(data, `${c}-registered.json`)));
console.log(`edition ${name}: ${out} (${Object.keys(cities).join(', ')}${withReg.length ? `; registered sales for ${withReg.join(', ')}` : ''})`);
