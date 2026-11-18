// Small DOM and text helpers for the Mini App. No framework, no build step.
import { day, makeT } from '../shared/calc.js';

export { day };

/** Load both locale files (the bot reads the very same JSON). */
export async function loadCatalogs(base = new URL('../shared/locales/', import.meta.url)) {
  const get = (l) => fetch(new URL(`${l}.json`, base)).then((r) => r.json());
  const [uz, ru] = await Promise.all([get('uz'), get('ru')]);
  return { uz, ru };
}

export function texts(catalogs) {
  return makeT(catalogs);
}

/** h('div', {class: 'x', onclick: fn}, child, 'text') — children may be nodes, strings or arrays. */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v; // only ever locale templates rendered with escaped params
    else if (k === 'text') el.textContent = v;
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else if (k === 'dataset') Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? '' : v);
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return el;
}

/** Strip the few tags our templates use, for places that need plain text (alerts, aria-labels). */
export const plain = (html) => {
  const d = document.createElement('div');
  d.innerHTML = html;
  return d.textContent;
};

export function initials(name) {
  const parts = String(name).replace(/^#/, '').trim().split(/\s+/);
  return (parts[0]?.[0] ?? '?').toUpperCase() + (parts[1]?.[0] ?? '').toUpperCase();
}

/** Hue from a name, so each person keeps the same avatar colour. */
export function hue(name) {
  let x = 0;
  for (const ch of String(name)) x = (x * 31 + ch.codePointAt(0)) % 360;
  return x;
}

export function addDays(iso, n) {
  return new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
}

export function localDay(atUtc) {
  return day(new Date(Date.parse(atUtc) + 5 * 3_600_000).toISOString().slice(0, 10));
}

/** Apply Telegram theme params on top of our palette (light/dark follow the user's Telegram theme). */
export function applyTheme(root, tg) {
  const p = tg?.themeParams ?? {};
  const map = {
    '--bg': p.secondary_bg_color || p.bg_color, '--surface': p.section_bg_color || p.bg_color,
    '--ink': p.text_color, '--muted': p.hint_color || p.subtitle_text_color, '--btn': p.button_color,
    '--btn-ink': p.button_text_color, '--link': p.link_color,
  };
  for (const [k, v] of Object.entries(map)) if (v) root.style.setProperty(k, v);
  if (tg?.colorScheme) root.dataset.scheme = tg.colorScheme;
}

export function haptic(tg, kind = 'light') {
  try {
    if (kind === 'success' || kind === 'error') tg?.HapticFeedback?.notificationOccurred(kind);
    else tg?.HapticFeedback?.impactOccurred(kind);
  } catch {
    /* not inside Telegram */
  }
}
