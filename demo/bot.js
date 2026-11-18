// JS port of the bot handlers (pulqarz/bot/handlers_*.py) driving one simulated Telegram chat.
import { cleanNote, Refused } from './backend.js';

const ROUTES = [
  ['nav', /^n:(menu|balance|people|pending|lang|lent|borrowed)$/], ['who', /^w:(\d+)$/], ['cur', /^c:(UZS|USD)$/],
  ['due', /^d:(0|7|14|30)$/], ['step', /^s:(back|cancel|skip|send)$/], ['per', /^p:(\d+):(open|hist|verify)$/],
  ['debt', /^b:(\d+):(\d+):(open|pay|payfull|correct|camount|cdue|ext7|ext30|dtype|wo|woyes)$/],
  ['ans', /^a:(\d+):(\d+):([012])$/], ['why', /^r:(\d+):(\d+):(amount|none|date|type)$/],
];
const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
export class BotSim {
  constructor(backend, uid, t, views, hooks = {}) {
    Object.assign(this, { b: backend, uid, t, v: views, hooks, messages: [], ids: 1, fsm: { data: {}, typed: null } });
  }

  get lang() { return this.b.users[this.uid].lang; }
  changed() { this.hooks.onChange?.(); }
  push(screen, from = 'bot') {
    const msg = { id: this.ids++, from, html: screen.html, kb: screen.kb ?? [], at: this.b.nowMs() };
    this.messages.push(msg);
    this.changed();
    return msg;
  }
  edit(id, screen) {
    const m = this.messages.find((x) => x.id === id);
    if (!m) return this.push(screen);
    Object.assign(m, { html: screen.html, kb: screen.kb ?? [] });
    this.changed();
    return m;
  }
  fail(err, typed) {
    const code = err?.code ?? 'generic';
    let text = this.t(this.lang, `err.${code}`, { example: this.v.day(addDays(this.b.today(), 30)) });
    if (text === `err.${code}`) text = this.t(this.lang, 'err.generic');
    if (typed) this.push({ html: text });
    else this.hooks.onAlert?.(text);
    if (!(err instanceof Refused)) console.error(err); // eslint-disable-line no-console
  }
  menu(hello = false) { return this.v.mainMenu(this.lang, this.b.pendingFor(this.uid).length, hello); }
  name(other) { return this.b.labels(this.uid)[other] ?? ''; }

  start(payload = '') {
    this.push({ html: `/start${payload ? ` ${payload}` : ''}` }, 'me');
    this.fsm = { data: {}, typed: null };
    try {
      if (!payload.startsWith('d_')) return this.push(this.menu(true));
      const r = this.b.openInvite(this.uid, payload.slice(2));
      return this.push(this.v.ask(this.lang, this.name(r.other), r.other, r.prop, r.debt));
    } catch (err) {
      return this.fail(err, true);
    }
  }

  type(text) {
    this.push({ html: text.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' })[c]) }, 'me');
    const typed = this.fsm.typed;
    try {
      if (!typed) return this.push(this.menu());
      return typed(text);
    } catch (err) {
      return this.fail(err, true);
    }
  }

  press(msgId, data) {
    const route = ROUTES.find(([, re]) => re.test(data));
    try {
      if (!route) throw new Refused('stale');
      const args = route[1].exec(data).slice(1);
      this[`on_${route[0]}`](msgId, ...args);
    } catch (err) {
      this.fail(err, false);
    }
  }

  // ── main ──
  on_nav(id, to) {
    const lang = this.lang;
    if (to === 'lent' || to === 'borrowed') {
      this.fsm = { data: { direction: to, trail: [] }, typed: null };
      return this.go(id, 'who');
    }
    this.fsm = { data: {}, typed: null };
    if (to === 'lang') {
      this.b.setLang(this.uid, lang === 'uz' ? 'ru' : 'uz');
      this.hooks.onLang?.(this.lang);
      return this.edit(id, this.menu());
    }
    if (to === 'menu') return this.edit(id, this.menu());
    if (to === 'pending') return this.edit(id, this.v.pending(lang, this.b.pendingFor(this.uid)));
    const s = this.b.summary(this.uid);
    return this.edit(id, to === 'balance' ? this.v.balance(lang, s) : this.v.people(lang, s));
  }

  on_per(id, uid, view) {
    this.fsm = { data: {}, typed: null };
    const p = this.b.person(this.uid, Number(uid));
    if (view === 'hist') return this.edit(id, this.v.history(this.lang, p));
    if (view === 'verify') return this.edit(id, this.v.verify(this.lang, p.other, p.verify));
    return this.edit(id, this.v.person(this.lang, p, this.b.today()));
  }

  pendingProp(other, seq) {
    const { state } = this.b.chain(this.uid, other);
    const prop = state.props[seq];
    if (!prop || prop.status !== 'pending') throw new Refused('not_pending');
    if (prop.by === this.uid) throw new Refused('own_proposal');
    return { prop, debt: state.debts[prop.ref] };
  }

  on_ans(id, uid, seq, ok) {
    const other = Number(uid);
    const { prop, debt } = this.pendingProp(other, Number(seq));
    if (ok === '2') return this.edit(id, this.v.ask(this.lang, this.name(other), other, prop, debt));
    if (ok === '0') return this.edit(id, this.v.reasons(this.lang, other, Number(seq)));
    const out = this.b.answer(this.uid, other, Number(seq), true);
    return this.edit(id, this.v.done(this.lang, this.t(this.lang, 'done.confirmed', { seal: out.prop.seal })));
  }

  reject(id, other, seq, reason) {
    this.b.answer(this.uid, other, seq, false, reason);
    const screen = this.v.done(this.lang, this.t(this.lang, 'done.rejected', { name: this.name(other) }));
    return id ? this.edit(id, screen) : this.push(screen);
  }

  on_why(id, uid, seq, code) {
    const other = Number(uid);
    this.pendingProp(other, Number(seq));
    if (code !== 'type') return this.reject(id, other, Number(seq), this.t(this.lang, `reason.${code}`));
    this.fsm = { data: {}, typed: (text) => {
      const reason = cleanNote(text, 200, 'reason', true);
      this.fsm = { data: {}, typed: null };
      return this.reject(null, other, Number(seq), reason);
    } };
    return this.edit(id, { html: this.t(this.lang, 'reject.type'), kb: [[{ text: this.t(this.lang, 'btn.back'), data: `a:${uid}:${seq}:0` }]] });
  }
}
