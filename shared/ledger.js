// JS port of pulqarz/core/canon.py + ledger.py. Same rules, same hashes: shared/test_vectors.json is checked
// against both implementations (pytest and `node --test`). Keep the two in step.
import { sha256Hex } from './sha256.js';

export const GENESIS = '0'.repeat(64);
export const CURRENCIES = ['UZS', 'USD'];
export const NOTE_MAX = 200;
export const REASON_MAX = 200;
const MAX_AMOUNT = 10 ** 15;
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const TIME_RE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;

export class LedgerError extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

export function canonical(v) {
  if (typeof v === 'string') return JSON.stringify(v);
  if (typeof v === 'number') {
    if (!Number.isSafeInteger(v)) throw new TypeError('only safe integers are allowed');
    return String(v);
  }
  if (Array.isArray(v)) return `[${v.map(canonical).join(',')}]`;
  if (v && typeof v === 'object') {
    const keys = Object.keys(v).sort();
    return `{${keys.map((k) => `${JSON.stringify(k)}:${canonical(v[k])}`).join(',')}}`;
  }
  throw new TypeError(`unsupported type ${typeof v}`);
}

export const entryHash = (prev, body) => sha256Hex(prev + canonical(body));
export const seal = (h) => `${h.slice(0, 4)}-${h.slice(4, 8)}`.toUpperCase();

export function pairKey(a, b) {
  if (a === b) throw new LedgerError('same_person');
  const [lo, hi] = [Number(a), Number(b)].sort((x, y) => x - y);
  return `${lo}:${hi}`;
}
export const parties = (pair) => pair.split(':').map(Number);

function isDate(v) {
  if (typeof v !== 'string' || !DATE_RE.test(v)) return false;
  const d = new Date(`${v}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === v;
}

function amount(v, upto = MAX_AMOUNT) {
  if (!Number.isSafeInteger(v) || v <= 0 || v > upto) throw new LedgerError('bad_amount');
  return v;
}

export const newState = () => ({ debts: {}, props: {}, pending: {}, head: GENESIS, seq: 0 });

function activeDebt(state, ref) {
  const debt = Number.isInteger(ref) ? state.debts[ref] : undefined;
  if (!debt || debt.status !== 'active') throw new LedgerError('debt_not_active');
  if (ref in state.pending) throw new LedgerError('change_pending');
  return debt;
}

export function apply(state, e) {
  const { kind, by, seq } = e;
  const [a, b] = parties(e.pair);
  if (by !== a && by !== b) throw new LedgerError('not_a_party');
  if (typeof e.at !== 'string' || !TIME_RE.test(e.at)) throw new LedgerError('bad_time');
  if (kind === 'debt') {
    const { lender, borrower } = e;
    const ok = (lender === a && borrower === b) || (lender === b && borrower === a);
    if (!ok || (by !== lender && by !== borrower)) throw new LedgerError('bad_parties');
    if (!CURRENCIES.includes(e.cur)) throw new LedgerError('bad_currency');
    if (!isDate(e.due)) throw new LedgerError('bad_date');
    const note = e.note ?? '';
    if (typeof note !== 'string' || len(note) > NOTE_MAX) throw new LedgerError('bad_note');
    state.debts[seq] = {
      seq, lender, borrower, cur: e.cur, principal: amount(e.amount), paid: 0, due: e.due, note,
      status: 'pending', seal: null, at: e.at, by,
    };
    state.props[seq] = { seq, kind, by, ref: seq, status: 'pending', at: e.at, amount: e.amount, cur: e.cur };
    state.pending[seq] = seq;
  } else if (kind === 'payment' || kind === 'correction' || kind === 'writeoff') {
    const ref = e.ref;
    const debt = activeDebt(state, ref);
    const prop = {
      seq, kind, by, ref, status: 'pending', at: e.at, cur: debt.cur, from_amount: debt.principal, from_due: debt.due,
    };
    if (kind === 'payment') {
      prop.amount = amount(e.amount, debt.principal - debt.paid);
    } else if (kind === 'correction') {
      if (e.amount === undefined && e.due === undefined) throw new LedgerError('nothing_to_change');
      if (e.amount !== undefined) {
        if (amount(e.amount) <= debt.paid || e.amount === debt.principal) throw new LedgerError('bad_amount');
        prop.amount = e.amount;
      }
      if (e.due !== undefined) {
        if (!isDate(e.due) || e.due === debt.due) throw new LedgerError('bad_date');
        prop.due = e.due;
      }
    } else if (by !== debt.lender) {
      throw new LedgerError('only_lender');
    } else {
      prop.amount = debt.principal - debt.paid;
    }
    state.props[seq] = prop;
    state.pending[ref] = seq;
  } else if (kind === 'confirm' || kind === 'reject') {
    answer(state, e);
  } else {
    throw new LedgerError('bad_kind');
  }
}

// JS strings count UTF-16 units, Python counts code points; limits use code points in both.
const len = (s) => Array.from(s).length;

function answer(state, e) {
  const prop = Number.isInteger(e.ref) ? state.props[e.ref] : undefined;
  if (!prop || prop.status !== 'pending') throw new LedgerError('not_pending');
  if (e.by === prop.by) throw new LedgerError('own_proposal');
  const debt = state.debts[prop.ref];
  delete state.pending[prop.ref];
  if (e.kind === 'reject') {
    const r = e.reason;
    if (typeof r !== 'string' || !r.trim() || len(r) > REASON_MAX) throw new LedgerError('bad_reason');
    Object.assign(prop, { status: 'rejected', reason: r, answer: e.seq });
    if (prop.kind === 'debt') debt.status = 'rejected';
    return;
  }
  Object.assign(prop, { status: 'confirmed', answer: e.seq, seal: seal(e.hash) });
  if (prop.kind === 'debt') {
    debt.status = 'active';
    debt.seal = prop.seal;
  } else if (prop.kind === 'payment') {
    debt.paid += prop.amount;
    if (debt.paid === debt.principal) debt.status = 'closed';
  } else if (prop.kind === 'correction') {
    if (prop.amount !== undefined) debt.principal = prop.amount;
    if (prop.due !== undefined) debt.due = prop.due;
  } else {
    debt.status = 'written_off';
  }
}

export function makeEntry(state, pair, body) {
  const full = {};
  for (const [k, v] of Object.entries(body)) if (v !== null && v !== undefined) full[k] = v;
  Object.assign(full, { v: 1, pair, seq: state.seq + 1, prev: state.head });
  full.hash = entryHash(full.prev, full);
  return full;
}

export function foldFrom(state, entries) {
  const out = structuredClone(state);
  for (const e of entries) {
    apply(out, e);
    out.head = e.hash;
    out.seq = e.seq;
  }
  return out;
}

export const fold = (entries) => foldFrom(newState(), entries);

export function append(state, pair, body) {
  const entry = makeEntry(state, pair, body);
  const next = foldFrom(state, [entry]);
  Object.assign(state, next);
  return entry;
}

export function verifyChain(entries) {
  const state = newState();
  let prev = GENESIS;
  const pair = entries.length ? entries[0].pair : null;
  for (let i = 1; i <= entries.length; i++) {
    const e = entries[i - 1];
    const { hash, ...body } = e;
    try {
      if (e.seq !== i || e.pair !== pair || e.v !== 1) return { ok: false, seq: i, reason: 'order' };
      if (e.prev !== prev) return { ok: false, seq: i, reason: 'link' };
      if (entryHash(prev, body) !== hash) return { ok: false, seq: i, reason: 'hash' };
      apply(state, e);
    } catch {
      return { ok: false, seq: i, reason: 'rule' };
    }
    prev = hash;
    state.head = prev;
    state.seq = i;
  }
  return { ok: true, count: entries.length, head: prev };
}

/** Fold only the part of the chain that verifies. Balances never come from tampered entries. */
export function foldTrusted(entries) {
  const result = verifyChain(entries);
  return { state: fold(result.ok ? entries : entries.slice(0, result.seq - 1)), result };
}
