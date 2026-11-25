// Registered sales: an optional per-city layer (/data/<city>-registered.json) from a land-records partner.
// Prices on registered deeds, next to the portal's asking prices. A city without the file shows nothing.
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

export async function loadRegistered(cityId) {
  try {
    const r = await fetch(`/data/${cityId}-registered.json`);
    return r.ok ? await r.json() : null;
  } catch {
    return null;
  }
}

const psf = (v) => (v ? `₹${Math.round(v).toLocaleString('en-IN')}` : '');
const CONF = { A: 'Matched by RERA number', B: 'Matched by the society name on the deeds', C: 'Matched by the land parcel' };

function yearBars(byYear) {
  if (!byYear?.length) return '';
  const hi = Math.max(...byYear.map((y) => y[1])), w = 200, h = 34, bw = w / byYear.length;
  const bars = byYear.map(([, n], i) => `<rect x="${i * bw + 1}" y="${h - 2 - (n / hi) * (h - 6)}" width="${Math.max(2, bw - 2)}" height="${(n / hi) * (h - 6)}" rx="1"/>`).join('');
  return `<div class="trend"><svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" aria-hidden="true" fill="currentColor">${bars}</svg>
    <span class="fine">Sales registered each year, ${byYear[0][0]} to ${byYear.at(-1)[0]}</span></div>`;
}

export function registeredBlock(layer, s) {
  if (!layer) return '';
  const head = `<h4>Registered sales <span class="fine">· ${esc(layer.source?.name || 'land records')}</span></h4>`;
  const r = layer.societies?.[s.id];
  if (!r) return `${head}<div class="fine">No registered sales matched to this society yet.</div>`;
  const row = (label, v, note) => (v?.value ? `<tr><td>${label}</td><td><b>${psf(v.value)}</b><span class="fine">/sq ft</span></td><td class="fine">${note || `${v.n} deeds`}</td></tr>` : '');
  const rows = [
    row(r.unit_word === 'plots' ? 'First sales, typical' : 'Builder sales, typical', r.first_psf),
    row('Resales, typical', r.resale_psf),
    row('Top registered', r.top_psf, r.top_psf ? `top ${r.top_psf.group} of ${r.top_psf.n} deeds` : ''),
    r.valuation_psf ? `<tr><td>Registry valuation</td><td><b>${psf(r.valuation_psf)}</b><span class="fine">/sq ft</span></td><td class="fine">the government rate the deeds were valued at</td></tr>` : '',
  ].join('');
  const turnover = r.units_seen ? ` · ${r.units_seen.toLocaleString()} ${esc(r.unit_word || 'homes')} on the deeds, ${r.resold || 0} sold again` : '';
  return `${head}
    <div class="meta"><b>${r.sales.toLocaleString()}</b> sale deeds since ${esc(String(layer.since || ''))}${r.last ? ` · latest ${esc(r.last)}` : ''}${turnover}</div>
    ${rows ? `<table class="prices reg"><tr><th>Price on the deed</th><th>Per sq ft</th><th></th></tr>${rows}</table>` : '<div class="fine">Too few deeds with a usable area for a price.</div>'}
    ${yearBars(r.by_year)}
    <div class="fine">${esc(layer.caveat || '')} ${r.area_note ? esc(r.area_note) + ' ' : ''}${esc(layer.conf_labels?.[r.confidence] || CONF[r.confidence] || '')}. ${layer.source?.url ? `<a href="${esc(layer.source.url)}" target="_blank" rel="noopener">${esc(layer.source.name)}</a>, ` : ''}deeds to ${esc(layer.as_of || '')}.</div>`;
}
