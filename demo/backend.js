// In-browser stand-in for the server: the same rules as pulqarz/service.py, running on the JS port of the core.
// Nothing leaves the browser. `apiFor(uid)` returns the same API shape the real Mini App uses over HTTP.
import { debtView, localToday, pairBalance, parseAmount, reminderPlan, summary } from '../shared/calc.js';
import { append, fold, LedgerError, NOTE_MAX, pairKey, parties, REASON_MAX, verifyChain } from '../shared/ledger.js';
import { sha256Hex } from '../shared/sha256.js';

const DAY = 86_400_000;
const CONTROL = /[\u0000-\u0009\u000b-\u001f\u007f​-‏‪-‮⁦-⁩]/g;
export const BOT_USERNAME = 'PulQarzDemoBot';

export class Refused extends Error {
  constructor(code) {
    super(code);
    this.code = code;
  }
}

const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * DAY).toISOString().slice(0, 10);
const isDate = (v) => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)
  && new Date(`${v}T00:00:00Z`).toISOString().slice(0, 10) === v;
const len = (s) => Array.from(s).length;

export function cleanName(text) {
  const name = String(text ?? '').replace(CONTROL, ' ').split(/\s+/).filter(Boolean).join(' ');
  if (len(name) < 1 || len(name) > 40) throw new Refused('name');
  return name;
}

export function cleanNote(text, limit = NOTE_MAX, code = 'note', required = false) {
  const note = String(text ?? '').replace(CONTROL, ' ').trim();
  if (len(note) > limit || (required && !note)) throw new Refused(code);
  return note;
}

export class DemoBackend {
  constructor({ now = () => Date.now() } = {}) {
    this.realNow = now;
    this.offset = 0;
    this.users = {};
    this.chains = {};
    this.labelsBy = {};
    this.invites = {};
    this.reminders = {};
    this.listeners = new Set();
  }

  // ── clock ──
  nowMs() { return this.realNow() + this.offset * DAY; }
  today() { return localToday(this.nowMs()); }
  stamp(ms = this.nowMs()) { return `${new Date(ms).toISOString().slice(0, 19)}Z`; }
  skipDays(n = 1) {
    this.offset += n;
    const sent = this.runDue();
    this.emit({ type: 'clock', today: this.today() });
    return sent;
  }

  on(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(ev) { for (const fn of this.listeners) fn(ev); }

  addUser(id, name, lang = 'uz') { this.users[id] = { id, name, lang }; }
  setLang(id, lang) { this.users[id].lang = lang; }

  // ── chains ──
  entries(pair) { return this.chains[pair] ?? []; }
  chain(me, other) {
    const pair = pairKey(me, other);
    const entries = this.entries(pair);
    return { pair, entries, state: fold(entries) };
  }
  partners(me) {
    return Object.keys(this.chains).map(parties).filter(([a, b]) => a === me || b === me)
      .map(([a, b]) => (a === me ? b : a)).sort((x, y) => x - y);
  }
  labels(me) {
    const out = {};
    for (const o of this.partners(me)) out[o] = this.labelsBy[me]?.[o] ?? this.users[o]?.name ?? `#${o}`;
    return out;
  }
  setLabel(owner, other, name) { (this.labelsBy[owner] ??= {})[other] = name; }

  /** Validate against the current chain and store (``at`` can be set by the seed). */
  appendAs(me, other, body, at = this.stamp()) {
    const { pair, state } = this.chain(me, other);
    let entry;
    try {
      entry = append(state, pair, { ...body, at });
    } catch (err) {
      if (err instanceof LedgerError) throw new Refused(err.code);
      throw err;
    }
    (this.chains[pair] ??= []).push(entry);
    return { entry, state };
  }

  checkDue(due) {
    const today = this.today();
    if (!isDate(due) || due < today || due > addDays(today, 3660)) throw new Refused('date');
    return due;
  }

  proposeDebt(me, { direction, amount, cur, due, note = '', other = null, name = null }) {
    if (direction !== 'lent' && direction !== 'borrowed') throw new Refused('generic');
    if (cur !== 'UZS' && cur !== 'USD') throw new Refused('bad_amount');
    if (!Number.isSafeInteger(amount) || amount <= 0) throw new Refused('bad_amount');
    const body = { kind: 'debt', amount, cur, due: this.checkDue(due), note: cleanNote(note) };
    if (other === null || other === undefined) {
      const label = cleanName(name);
      const bytes = crypto.getRandomValues(new Uint8Array(16));
      const token = btoa(String.fromCharCode(...bytes)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
      this.invites[sha256Hex(token)] = { creator: me, payload: { ...body, direction, name: label },
        expires: this.nowMs() + 7 * DAY, used: false };
      return { token, name: label, link: `https://t.me/${BOT_USERNAME}?start=d_${token}` };
    }
    if (!this.partners(me).includes(other)) throw new Refused('not_found');
    const [lender, borrower] = direction === 'lent' ? [me, other] : [other, me];
    const { entry, state } = this.appendAs(me, other, { ...body, by: me, lender, borrower });
    this.emit({ type: 'ask', to: other, from: me, prop: state.props[entry.seq], debt: state.debts[entry.seq] });
    return { entry, other, sent: true, seq: entry.seq };
  }

  openInvite(me, token) {
    if (typeof token !== 'string' || !/^[A-Za-z0-9_-]{22,43}$/.test(token)) throw new Refused('link_used');
    const inv = this.invites[sha256Hex(token)];
    if (inv && inv.creator === me) throw new Refused('own_link');
    if (!inv || inv.used || inv.expires <= this.nowMs()) throw new Refused('link_used');
    inv.used = true;
    const p = inv.payload;
    const [lender, borrower] = p.direction === 'lent' ? [inv.creator, me] : [me, inv.creator];
    const { entry, state } = this.appendAs(inv.creator, me, { kind: 'debt', amount: p.amount, cur: p.cur, due: p.due,
      note: p.note, by: inv.creator, lender, borrower });
    this.setLabel(inv.creator, me, p.name);
    return { entry, other: inv.creator, prop: state.props[entry.seq], debt: state.debts[entry.seq] };
  }

  answer(me, other, ref, confirm, reason) {
    const body = { kind: confirm ? 'confirm' : 'reject', by: me, ref: Number(ref) };
    if (!confirm) body.reason = cleanNote(reason, REASON_MAX, 'reason', true);
    const { entry, state } = this.appendAs(me, other, body);
    const prop = state.props[Number(ref)];
    const debt = state.debts[prop.ref];
    if (confirm && debt.status === 'active' && (prop.kind === 'debt' || prop.kind === 'correction')) {
      this.scheduleReminders(entry.pair, debt);
    }
    this.emit({ type: 'answered', to: other, from: me, prop, debt });
    return { entry, prop, debt };
  }

  proposeChange(me, other, seq, kind, { amount, due } = {}) {
    if (!['payment', 'correction', 'writeoff'].includes(kind)) throw new Refused('generic');
    const body = { kind, by: me, ref: Number(seq) };
    if (amount !== undefined && amount !== null) body.amount = amount;
    if (due !== undefined && due !== null) body.due = this.checkDue(due);
    const { entry, state } = this.appendAs(me, other, body);
    const prop = state.props[entry.seq];
    this.emit({ type: 'ask', to: other, from: me, prop, debt: state.debts[Number(seq)] });
    return { entry, prop, debt: state.debts[Number(seq)] };
  }

  scheduleReminders(pair, debt) {
    for (const r of reminderPlan(debt.due, this.today())) {
      for (const uid of [debt.lender, debt.borrower]) {
        const key = `${pair}|${debt.seq}|${r.key}|${uid}`;
        this.reminders[key] ??= { pair, seq: debt.seq, key: r.key, uid, fire: `${r.date}T04:00:00Z`, sent: false };
      }
    }
  }

  /** Same logic as pulqarz/reminders.py: claim, then deliver only if the debt is still open on that due date. */
  runDue() {
    const now = this.stamp();
    const out = [];
    const due = Object.values(this.reminders).filter((r) => !r.sent && r.fire <= now).sort((a, b) => (a.fire < b.fire ? -1 : 1));
    for (const r of due) {
      r.sent = true;
      const [kind, d] = r.key.split('@');
      const debt = fold(this.entries(r.pair)).debts[r.seq];
      if (!debt || debt.status !== 'active' || debt.due !== d) continue;
      const [a, b] = parties(r.pair);
      const ev = { type: 'reminder', to: r.uid, other: r.uid === a ? b : a, debt, kind };
      out.push(ev);
      this.emit(ev);
    }
    return out;
  }

  // ── reading ──
  pendingFor(me) {
    const items = [];
    for (const [o, name] of Object.entries(this.labels(me))) {
      const { state } = this.chain(me, Number(o));
      for (const prop of Object.values(state.props)) {
        if (prop.status === 'pending' && prop.by !== me) items.push({ other: Number(o), name, prop, debt: state.debts[prop.ref] });
      }
    }
    return items.sort((x, y) => (x.prop.at < y.prop.at ? -1 : 1));
  }

  summary(me) {
    const names = this.labels(me);
    const states = {};
    for (const o of Object.keys(names)) states[o] = this.chain(me, Number(o)).state;
    return { ...summary(states, me), names, pending: this.pendingFor(me) };
  }

  person(me, other) {
    const names = this.labels(me);
    if (!(other in names)) throw new Refused('not_found');
    const { entries, state } = this.chain(me, other);
    return { other, name: names[other], net: pairBalance(state, me), today: this.today(),
      debts: Object.values(state.debts).map((d) => debtView(d, me)),
      props: Object.values(state.props).map((x) => ({ ...x, mine: x.by === me })),
      verify: verifyChain(entries), entries: structuredClone(entries) };
  }

  /** Demo only: change a stored entry in place, as an attacker with database access would. */
  tamper(pair, seq, field, value) {
    const e = this.entries(pair)[seq - 1];
    if (e) e[field] = value;
    this.emit({ type: 'tamper', pair, seq });
  }

  apiFor(uid) {
    const run = (fn) => new Promise((resolve, reject) => setTimeout(() => {
      try { resolve(fn()); } catch (err) { reject(err instanceof Refused ? err : Object.assign(err, { code: 'generic' })); }
    }, 60));
    const amount = (v) => { try { return parseAmount(String(v)); } catch { throw new Refused('amount'); } };
    return {
      me: () => run(() => {
        const s = this.summary(uid);
        return { me: this.users[uid], today: this.today(), owed_to_me: s.owed_to_me, i_owe: s.i_owe,
          people: Object.entries(s.names).map(([id, name]) => ({ id: Number(id), name, net: s.people[id] ?? {} })),
          pending: s.pending.map((p) => ({ ...p, debt: debtView(p.debt, uid) })) };
      }),
      person: (o) => run(() => this.person(uid, Number(o))),
      create: (b) => run(() => this.proposeDebt(uid, { ...b, amount: amount(b.amount), other: b.other ?? null })),
      answer: (o, b) => run(() => {
        const r = this.answer(uid, Number(o), b.seq, b.ok, b.reason);
        return { status: r.prop.status, seal: r.prop.seal };
      }),
      change: (o, b) => run(() => this.proposeChange(uid, Number(o), b.seq, b.kind, {
        amount: b.amount ? amount(b.amount) : undefined, due: b.due || undefined })),
      setLang: (lang) => run(() => this.setLang(uid, lang)),
    };
  }
}
