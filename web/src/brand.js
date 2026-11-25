// A branded edition: the host site's colours, logo and header over Flat Finder ("brand" in editions/<name>.json).
// The look is in brand.css; this builds the header bar and hands the map its colours.
import './brand.css';

const BRANDS = {
  uttarakhandhub: {
    words: ['Uttarakhand', 'Hub'], logo: '/brand/uttarakhandhub.svg', url: 'https://uttarakhandhub.com',
    font: 'https://fonts.googleapis.com/css2?family=Lora:wght@500;600;700&display=swap',
    pills: { ink: '#1f2933', on: '#0d2b45' },
    map: {
      palettes: {
        light: { match: '#f28c28', likely: '#f5ad5f', probable: '#f8cc9c', unknown: '#b9b2a4', no: '#e6e1d6', sel: '#0d2b45', city: '#ebe7de', label: '#1f2933' },
        streets: { match: '#f28c28', likely: '#c98a4a', probable: '#9c7a55', unknown: '#4f6377', no: '#1b3148', sel: '#ffffff', city: '#16324c' },
        night: { match: '#f28c28', likely: '#c98a4a', probable: '#9c7a55' },
      },
      light: { 'st-bg': { 'background-color': '#f7f5f0' }, 'st-casing': { 'line-color': '#e2ddd3' }, 'lbl-metro': { 'text-color': '#0d2b45' } },
      dark: { 'st-bg': { 'background-color': '#0a2136' }, 'st-green': { 'fill-color': '#12332f' }, 'st-park': { 'fill-color': '#163a2c' }, 'st-water': { 'fill-color': '#0c3355' },
        'st-casing': { 'line-color': '#071827' } },
    },
  },
};

export const brandOf = (ed) => BRANDS[ed?.brand] || null;

// Build the top bar: logo and wordmark, the product name, then the search box, city picker and top buttons moved into it.
export function applyBrand(ed, brand, { mobile }) {
  document.body.classList.add('brand', `brand-${ed.brand}`);
  document.head.append(Object.assign(document.createElement('link'), { rel: 'stylesheet', href: brand.font }));
  const el = (tag, cls, text) => Object.assign(document.createElement(tag), { className: cls || '', textContent: text || '' });
  const bar = el('header', 'bar');
  const logo = Object.assign(el('a', 'logo'), { href: brand.url, target: '_blank', rel: 'noopener', title: brand.words.join('') });
  logo.append(Object.assign(el('img'), { src: brand.logo, alt: '', width: 34, height: 34 }));
  const word = el('span', 'word', brand.words[0]);
  word.append(el('b', '', brand.words[1]));
  logo.append(word);
  const left = el('div', 'bar-l');
  left.append(logo, el('span', 'prod', ed.product || ed.kicker || ''));
  const right = el('div', 'bar-r');
  right.append(document.getElementById('city-pick'));
  right.append(mobile ? document.getElementById('btn-theme') : document.querySelector('.topbar')); // a phone keeps only light/dark; its tabs already collapse the sheet
  bar.append(left, document.querySelector('.search'), right);
  document.body.prepend(bar);

  // the results sit below the filters: a button that stays in view says how many match and jumps to them
  const panel = document.getElementById('filters'), count = panel.querySelector('.count');
  jump = el('button', 'jump');
  jump.onclick = () => panel.scrollTo({ top: count.offsetTop - 12, behavior: 'smooth' });
  panel.append(jump);
  new IntersectionObserver(([e]) => jump.classList.toggle('gone', e.isIntersecting), { root: panel, threshold: 0.6 }).observe(count);
}

let jump = null;
export function setJump(n, noun) {
  if (jump) jump.textContent = n ? `Show ${n.toLocaleString()} ${noun}` : `No ${noun} match: loosen a filter`;
}
