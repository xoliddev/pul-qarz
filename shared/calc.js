// JS port of pulqarz/core/balance.py, schedule.py, money.py and the text renderer in pulqarz/i18n.py.

export const CURRENCIES = ['UZS', 'USD'];

// ── balances ──
export const remaining = (d) => d.principal - d.paid;

export function pairBalance(state, me) {
  const net = {};
  for (const d of Object.values(state.debts)) {
    if (d.status !== 'active') continue;
    const sign = d.lender === me ? 1 : -1;
    net[d.cur] = (net[d.cur] ?? 0) + sign * remaining(d);
  }
  const out = {};
  for (const cur of Object.keys(net).sort()) if (net[cur] !== 0) out[cur] = net[cur];
  return out;
}

export function summary(states, me) {
  const people = {};
  const owed = { UZS: 0, USD: 0 };
  const owe = { UZS: 0, USD: 0 };
  const ids = Object.keys(states).map(Number).sort((a, b) => a - b);
  for (const other of ids) {
    const net = pairBalance(states[other], me);
    people[other] = net;
    for (const [cur, v] of Object.entries(net)) {
      if (v > 0) owed[cur] += v;
      else owe[cur] += -v;
    }
  }
  return { people, owed_to_me: owed, i_owe: owe };
}

export function debtView(d, me) {
  return {
    seq: d.seq, role: d.lender === me ? 'lender' : 'borrower', cur: d.cur, principal: d.principal,
    paid: d.paid, remaining: remaining(d), due: d.due, note: d.note, status: d.status, seal: d.seal,
  };
}

// ── reminders (09:00 Tashkent = 04:00 UTC) ──
export const OFFSETS = [['before3', -3], ['due', 0], ['overdue1', 1], ['overdue7', 7], ['overdue30', 30]];
const DAY = 86_400_000;

export function addDays(day, n) {
  return new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
}

export function reminderPlan(due, today) {
  const plan = [];
  for (const [kind, offset] of OFFSETS) {
    const date = addDays(due, offset);
    if (date >= today) plan.push({ kind, date, key: `${kind}@${due}` });
  }
  return plan;
}

export const fireAt = (day) => `${day}T04:00:00Z`;
export const localToday = (nowMs) => new Date(nowMs + 5 * 3_600_000).toISOString().slice(0, 10);
export const daysLeft = (due, today) => Math.round((Date.parse(`${due}T00:00:00Z`) - Date.parse(`${today}T00:00:00Z`)) / DAY);

// ── money (integer minor units, 1/100) ──
const GROUPED = /^(\d{1,3}(?:[ ,]\d{3})+)(?:[.,](\d{1,2}))?$/;
const PLAIN = /^(\d+)(?:[.,](\d{1,2}))?$/;

export function parseAmount(text) {
  if (typeof text !== 'string' || text.length > 32) throw new Error('bad_amount');
  let s = text.trim().replace(/[\s  _]+/g, ' ').trim();
  s = s.replace(/\s*(so'?m|sum|сум|uzs|usd|\$)\s*$/i, '').replace(/^[$ ]+/, '').trim();
  const m = GROUPED.exec(s) || PLAIN.exec(s);
  if (!m) throw new Error('bad_amount');
  const majorStr = m[1].replace(/[ ,]/g, '');
  if (majorStr.replace(/^0+/, '').length > 12) throw new Error('bad_amount');
  const major = Number(majorStr);
  const value = major * 100 + Number((m[2] ?? '').padEnd(2, '0') || 0);
  if (value <= 0 || major >= 10 ** 12) throw new Error('bad_amount');
  return value;
}

export function group(n) {
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
}

export function formatNumber(minor) {
  const sign = minor < 0 ? '-' : '';
  const abs = Math.abs(minor);
  const major = Math.floor(abs / 100);
  const cents = abs % 100;
  return sign + group(major) + (cents ? `,${String(cents).padStart(2, '0')}` : '');
}

// ── texts ──
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;' };
export const escapeHtml = (s) => String(s).replace(/[&<>]/g, (c) => ESC[c]);

/** Wraps already-safe HTML so `render` does not escape it again. */
export class Raw {
  constructor(html) {
    this.html = html;
  }
}

export function render(template, params = {}) {
  return template.replace(/\{(\w+)\}/g, (all, key) => {
    if (!(key in params)) return all;
    const v = params[key];
    return v instanceof Raw ? v.html : escapeHtml(v);
  });
}

export function makeT(catalogs, fallback = 'uz') {
  const t = (lang, key, params) => render(catalogs[lang]?.[key] ?? catalogs[fallback]?.[key] ?? key, params);
  t.money = (lang, minor, cur) => render(catalogs[lang][`amount.${cur}`], { n: formatNumber(minor) });
  return t;
}

export const day = (iso) => iso.split('-').reverse().join('.');
