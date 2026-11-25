// The "rera" profile: an edition whose map holds every project on a state RERA register instead of
// portal societies. Same map, search, list and card; the flat filters (BHK, bedrooms, budget) give way
// to district, project type and registration validity, and the card shows the register's own facts.
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export const RERA_KINDS = [
  ['apartment', 'Group housing', '<path d="M5 21V4h9v17M14 9h5v12M8 7h3M8 11h3M8 15h3"/>'],
  ['plot', 'Plotted', '<path d="M4 6l8-3 8 3v12l-8 3-8-3zM12 3v18M4 6l16 12"/>'],
  ['mixed', 'Mixed', '<path d="M3 21V10l6-4v15M9 21V3h8v18M21 21V12h-4"/>'],
  ['commercial', 'Commercial', '<path d="M4 9h16l-1-5H5zM5 9v11h14V9M10 20v-5h4v5"/>'],
  ['other', 'Not stated', '<circle cx="12" cy="12" r="8"/><path d="M12 8v5M12 16v.5"/>'],
];
const VALIDITY = { valid: 'Registration in date', expired: 'Past its validity date', revoked: 'Registration revoked' };
const DATA = { listings: 'On Magicbricks or Square Yards', web: 'Has its own pages', deeds: 'Has registered sales' };
export const RERA_DEFAULT = { districts: [], validity: [], data: [] };
const SOURCE = { magicbricks: 'Magicbricks', squareyards: 'Square Yards' };
const inr = (r) => (r == null ? '' : r >= 1e7 ? `₹${(r / 1e7).toFixed(2).replace(/\.?0+$/, '')} Cr` : r >= 1e5 ? `₹${(r / 1e5).toFixed(1).replace(/\.0$/, '')} L` : `₹${Math.round(r / 1000)}k`);

const fmtDate = (d) => (d ? new Date(d + 'T00:00:00').toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' }) : 'not stated');

export function reraMatch(s, rc, registered) {
  const r = s.rera || {};
  if (rc.data.includes('listings') && !s.listings?.length) return false;
  if (rc.data.includes('deeds') && !registered?.societies?.[s.id]) return false;
  if (rc.data.includes('web') && !s.web) return false;
  if (rc.districts.length && !rc.districts.includes(r.district)) return false;
  if (rc.validity.length && !rc.validity.includes(r.validity)) return false;
  return true;
}

// District and validity chips, drawn into #f-rera
export function reraFilters(el, data, rc, chip, onChange) {
  const n = new Map();
  for (const s of data.societies) n.set(s.rera?.district, (n.get(s.rera?.district) || 0) + 1);
  const districts = [...n].filter(([d]) => d).sort((a, b) => b[1] - a[1]);
  const toggle = (arr, v) => { const i = arr.indexOf(v); i >= 0 ? arr.splice(i, 1) : arr.push(v); onChange(); };
  const box = (title, chips) => {
    const d = document.createElement('div'), k = document.createElement('div'), c = document.createElement('div');
    k.className = 'k'; k.textContent = title; c.className = 'chips'; c.replaceChildren(...chips);
    d.append(k, c);
    return d;
  };
  el.replaceChildren(
    box('District', districts.map(([d, c]) => chip(`${esc(d)} <small>${c}</small>`, rc.districts.includes(d), () => toggle(rc.districts, d)))),
    box('Registration', Object.entries(VALIDITY).map(([k, l]) => chip(l, rc.validity.includes(k), () => toggle(rc.validity, k)))),
    box('Data', Object.entries(DATA).map(([k, l]) => chip(l, rc.data.includes(k), () => toggle(rc.data, k)))),
  );
}

export function reraTag(s) {
  const r = s.rera || {};
  return `${esc(r.district || '')}${r.validity === 'valid' ? '' : ` · <span class="lapsed">${r.validity === 'revoked' ? 'revoked' : 'expired'}</span>`}`;
}

// The card's register section: what the promoter filed, and where the map point comes from.
export function reraBlock(s) {
  const r = s.rera || {};
  const land = r.land_sqm ? `${Math.round(r.land_sqm).toLocaleString('en-IN')} m² (${(r.land_sqm / 4046.86).toFixed(2)} acres)` : null;
  const rows = [
    ['RERA number', `<b>${esc(r.reg)}</b>`],
    ['Registered', fmtDate(r.reg_date)],
    ['Valid to', `${fmtDate(r.valid_to)}${r.validity !== 'valid' ? ` <span class="lapsed">${r.validity === 'revoked' ? 'revoked' : 'past this date; an extension may not show here'}</span>` : ''}`],
    ['Project type', esc(r.type || 'not stated on the register')],
    ['Promoter', `${esc(s.developer)} <span class="fine">(${esc(r.promoter_type)})</span>`],
    r.units && ['Units filed', `${Number(r.units).toLocaleString('en-IN')}${r.inventory ? ` <span class="fine">${esc(r.inventory)}</span>` : ''}`],
    land && ['Land', land],
    r.map_valid_to && ['Map approval to', fmtDate(r.map_valid_to)],
    ['District', `${esc(r.district)}${r.tehsil ? ` · tehsil ${esc(r.tehsil)}` : ''}`],
    ['Address filed', `<span class="fine">${esc(r.address)}</span>`],
  ].filter(Boolean).map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`).join('');
  return `<h4>On the RERA register <span class="fine">· ${esc(r.register)}</span></h4>
    <table class="prices rera">${rows}</table>
    <div class="fine">Map point: ${esc(r.located)}${r.pinned ? ', matched to this registration' : `${r.approx ? ', where several projects share one point, so it is spread around it' : ''}. Not the exact site`}.</div>`;
}

// What the sales portals show for the project: asking prices, kept apart from the registered deeds.
export function listingsBlock(s) {
  const ls = s.listings || [];
  if (!ls.length) return '';
  const one = (x) => {
    const how = x.match === 'rera' ? 'matched by its RERA number' : 'matched by name';
    const range = x.price_min ? `${inr(x.price_min)}${x.price_max && x.price_max !== x.price_min ? ` to ${inr(x.price_max)}` : ''}` : '';
    const facts = [x.status, x.possession && `possession ${x.possession}`, x.config, range && `builder range ${range}`, x.psf && `₹${Math.round(x.psf).toLocaleString('en-IN')}/sq ft ${x.source === 'squareyards' ? 'base price' : 'asking now'}`].filter(Boolean).map(esc).join(' · ');
    const bhk = Object.entries(x.buy || {}).map(([b, v]) => `<tr><td>${b} BHK</td><td><b>${inr(v.median)}</b>${v.psf ? `<div class="fine">₹${v.psf.toLocaleString('en-IN')}/sq ft</div>` : ''}</td><td class="fine">${v.n} for sale${x.rent?.[b] ? ` · rent ${inr(x.rent[b].median)}/mo (${x.rent[b].n})` : ''}</td></tr>`).join('');
    const offers = (x.offers || []).slice(0, 8).map((o) => `<tr><td>${esc(o.label.replace(/,.*$/, ''))}</td><td><b>${inr(o.price)}</b></td><td class="fine">${o.sqft ? `${o.sqft.toLocaleString('en-IN')} sq ft${o.area_basis ? ' ' + esc(o.area_basis) : ''}` : ''}</td></tr>`).join('');
    const listed = x.sale_count || x.rent_count ? ` · ${x.sale_count || 0} for sale, ${x.rent_count || 0} for rent now` : '';
    return `<div class="meta"><a href="${esc(x.url)}" target="_blank" rel="noopener">${esc(SOURCE[x.source] || x.source)}: ${esc(x.name)}</a> <span class="fine">${how}${listed}</span></div>
      ${facts ? `<div class="fine">${facts}</div>` : ''}
      ${bhk ? `<table class="prices"><tr><th>Home</th><th>Asking</th><th></th></tr>${bhk}</table>` : ''}
      ${offers ? `<table class="prices"><tr><th>Unit</th><th>Price list</th><th>Size</th></tr>${offers}</table>` : ''}`;
  };
  return `<h4>On sales portals</h4>${ls.map(one).join('')}
    <div class="fine">Asking and price-list figures as the portals show them, not registered prices. Listing medians are of live listings; a price list is the builder's.</div>`;
}

export function reraNote(data, registered) {
  const c = data.counts;
  return `${c.on_map.toLocaleString()} RERA projects on the map` + (c.not_located ? ` · ${c.not_located} with no usable address` : '')
    + (c.with_listings ? ` · ${c.with_listings} on Magicbricks or Square Yards` : '')
    + (c.with_web ? ` · ${c.with_web} with their own or other web pages (${c.official_sites} official sites)` : '')
    + (registered ? ` · registered sales for ${Object.keys(registered.societies || {}).length} from ${registered.source?.name || 'land records'}` : '');
}

export function reraSteps(data) {
  const c = data.counts;
  return [
    [`Every RERA project in ${data.city.name}, on one map`, `${c.on_map.toLocaleString()} projects from the RERA register, with the promoter, registration dates, units filed and land. Where our land records hold them, the sale deeds each project registered.`],
    ['Narrow it down', 'Pick a project type, a district, or only registrations still in date. Search by project, promoter or place.'],
    ['How to read the map', 'Bright points match your filters, dim ones do not. Most addresses on the register name a village or a town, not a plot, so points are approximate. Projects that share a town centre are spread around it.'],
    ['Open a project, keep a list', 'Click a point for the register entry and the deeds. Star the ones you want to follow, share the list, or download every project as a CSV.'],
  ];
}

// What the project's own website and small property sites say. Every figure links to its page.
const WEB_LABEL = { price_from: 'Price from', price_to: 'Price up to', psf: 'Rate', unit_type: 'Units on offer', plot_size: 'Plot sizes',
  units: 'Units', towers: 'Towers', floors: 'Floors', land_area: 'Land', status: 'Status', possession: 'Possession', launch: 'Launched',
  approval: 'Approvals', rera_printed: 'RERA number shown', location: 'Location', brochure: 'Brochure' };
const host = (u) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return 'source'; } };
export function webBlock(s) {
  const w = s.web;
  if (!w) return '';
  const cite = (x) => `<a class="fine" href="${esc(x.source)}" target="_blank" rel="noopener">${esc(host(x.source))}${x.kind === 'snippet' ? ', search snippet' : x.kind === 'official' ? ', official' : ''}</a>`;
  const val = (x) => [x.value, x.unit, x.detail].filter(Boolean).map(esc).join(' · ');
  const rows = Object.entries(w.facts || {}).filter(([k]) => WEB_LABEL[k] && k !== 'rera_printed' && k !== 'location').map(([k, xs]) => {
    const shown = k === 'brochure' ? xs.slice(0, 2).map((x) => `<a href="${esc(x.value)}" target="_blank" rel="noopener">brochure</a> ${cite(x)}`)
      : xs.slice(0, k === 'unit_type' || k === 'plot_size' ? 8 : 2).map((x) => `${val(x)} ${cite(x)}`);
    return `<tr><td>${WEB_LABEL[k]}</td><td>${shown.join('<br>')}</td></tr>`;
  }).join('');
  const amen = (w.facts?.amenity || []).slice(0, 16).map((x) => `<span>${esc(x.value)}</span>`).join('');
  const printed = (w.facts?.rera_printed || []).map((x) => x.value.toUpperCase());
  const other = printed.filter((r) => r.replace(/\s/g, '') !== (s.rera?.reg || '').toUpperCase());
  const site = w.official_site ? `<div class="meta"><a class="btnlink" href="${esc(w.official_site)}" target="_blank" rel="noopener">Official project website</a> <span class="fine">${esc(host(w.official_site))}</span></div>` : '';
  const pages = (w.pages || []).filter((p) => p.url !== w.official_site).slice(0, 5).map((p) => `<a href="${esc(p.url)}" target="_blank" rel="noopener">${esc(host(p.url))}</a>`).join(' · ');
  return `<h4>Project's own pages and other sites</h4>${site}
    ${rows ? `<table class="prices web">${rows}</table>` : ''}
    ${amen ? `<div class="amen">${amen}</div>` : ''}
    ${pages ? `<div class="fine">Also read: ${pages}</div>` : ''}
    ${other.length ? `<div class="fine lapsed">A page shows RERA ${esc(other.join(', '))}, not this registration: check which phase it describes.</div>` : ''}
    <div class="fine">As these sites state them, found by web search and not checked by us. Promoters' sites state asking prices; registered prices are below.</div>`;
}
