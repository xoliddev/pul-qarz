// Create-debt steps and per-debt actions for the simulated bot (ports handlers_create.py / handlers_debt.py).
import { parseAmount, Raw } from '../shared/calc.js';
import { BotSim } from './bot.js';
import { cleanName, cleanNote, Refused } from './backend.js';

const addDays = (iso, n) => new Date(Date.parse(`${iso}T00:00:00Z`) + n * 86_400_000).toISOString().slice(0, 10);
const amountOf = (text) => {
  try { return parseAmount(text); } catch { throw new Refused('amount'); }
};
function parseDay(text) {
  const m = /^\s*(\d{1,2})[./-](\d{1,2})[./-](\d{4})\s*$/.exec(text ?? '');
  if (!m) return null;
  const iso = `${m[3]}-${m[2].padStart(2, '0')}-${m[1].padStart(2, '0')}`;
  const d = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(d.getTime()) && d.toISOString().slice(0, 10) === iso ? iso : null;
}

const P = BotSim.prototype;

P.stageScreen = function stageScreen(stage) {
  const { t, lang, fsm: { data } } = this;
  const b = (text, d) => ({ text, data: d });
  const cancel = this.v.cancelRow(lang);
  if (stage === 'who') {
    const kb = Object.entries(this.b.labels(this.uid)).slice(0, 10).map(([id, n]) => [b(n.slice(0, 40), `w:${id}`)]);
    kb.push([b(t(lang, 'btn.new_person'), 'w:0')], [b(t(lang, 'btn.back'), 'n:menu')]);
    return { html: t(lang, `create.who_${data.direction}`), kb };
  }
  if (stage === 'cur') return { html: t(lang, 'create.currency'), kb: [['UZS', 'USD'].map((c) => b(t(lang, `btn.${c}`), `c:${c}`)), cancel] };
  if (stage === 'due') {
    return { html: t(lang, 'create.due'), kb: [[7, 14, 30].map((n) => b(t(lang, `btn.due${n}`), `d:${n}`)),
      [b(t(lang, 'btn.due_type'), 'd:0')], cancel] };
  }
  if (stage === 'note') return { html: t(lang, 'create.note'), kb: [[b(t(lang, 'btn.skip'), 's:skip')], cancel] };
  if (stage === 'review') {
    return { html: t(lang, 'create.review', { direction: t(lang, `dir.${data.direction}`), name: data.name,
      amount: this.v.money(lang, data.amount, data.cur), due: this.v.day(data.due), note: data.note || '—' }),
    kb: [[b(t(lang, 'btn.send'), 's:send')], cancel] };
  }
  const key = { name: 'create.name', amount: 'create.amount', due_text: 'create.due_type' }[stage];
  return { html: t(lang, key, { example: this.v.day(addDays(this.b.today(), 30)) }), kb: [cancel] };
};

const TYPED = {
  name(text) { this.fsm.data.name = cleanName(text); return this.go(null, 'amount'); },
  amount(text) { this.fsm.data.amount = amountOf(text); return this.go(null, 'cur'); },
  due_text(text) { this.fsm.data.due = this.b.checkDue(parseDay(text) ?? ''); return this.go(null, 'note'); },
  note(text) { this.fsm.data.note = cleanNote(text); return this.go(null, 'review'); },
};

P.go = function go(id, stage, push = true) {
  if (push) this.fsm.data.trail = [...(this.fsm.data.trail ?? []), stage];
  this.fsm.typed = TYPED[stage] ? TYPED[stage].bind(this) : null;
  const screen = this.stageScreen(stage);
  return id ? this.edit(id, screen) : this.push(screen);
};

P.on_who = function onWho(id, uid) {
  if (!this.fsm.data.direction) throw new Refused('stale');
  if (uid === '0') {
    this.fsm.data.other = null;
    return this.go(id, 'name');
  }
  const labels = this.b.labels(this.uid);
  if (!(uid in labels)) throw new Refused('not_found');
  Object.assign(this.fsm.data, { other: Number(uid), name: labels[uid] });
  return this.go(id, 'amount');
};

P.on_cur = function onCur(id, cur) {
  if (!this.fsm.data.amount) throw new Refused('stale');
  this.fsm.data.cur = cur;
  return this.go(id, 'due');
};

P.on_due = function onDue(id, days) {
  if (!this.fsm.data.cur) throw new Refused('stale');
  if (days === '0') return this.go(id, 'due_text');
  this.fsm.data.due = addDays(this.b.today(), Number(days));
  return this.go(id, 'note');
};

P.on_step = function onStep(id, act) {
  const data = this.fsm.data;
  if (act === 'cancel' || !data.direction) {
    this.fsm = { data: {}, typed: null };
    return this.edit(id, this.menu());
  }
  if (act === 'back') {
    const trail = (data.trail ?? []).slice(0, -1);
    if (!trail.length) {
      this.fsm = { data: {}, typed: null };
      return this.edit(id, this.menu());
    }
    data.trail = trail;
    return this.go(id, trail.at(-1), false);
  }
  if (act === 'skip') {
    data.note = '';
    return this.go(id, 'review');
  }
  if (!(data.amount && data.cur && data.due && data.name)) throw new Refused('stale');
  this.fsm = { data: {}, typed: null };
  const res = this.b.proposeDebt(this.uid, { direction: data.direction, amount: data.amount, cur: data.cur, due: data.due,
    note: data.note ?? '', other: data.other ?? null, name: data.name });
  const back = [{ text: this.t(this.lang, 'btn.back'), data: 'n:menu' }];
  if (res.token) {
    const share = `https://t.me/share/url?${new URLSearchParams({ url: res.link, text: this.t(this.lang, 'share.text') })}`;
    return this.edit(id, { html: this.t(this.lang, 'create.link', { name: res.name, link: res.link }),
      kb: [[{ text: this.t(this.lang, 'btn.share'), url: share, link: res.link }], back] });
  }
  return this.edit(id, { html: this.t(this.lang, 'create.sent', { name: data.name }), kb: [back] });
};

P.on_debt = function onDebt(id, uid, seq, act) {
  const { t, lang } = this;
  const other = Number(uid);
  const n = Number(seq);
  this.fsm = { data: {}, typed: null };
  const p = this.b.person(this.uid, other);
  const d = p.debts.find((x) => x.seq === n);
  if (!d) throw new Refused('not_found');
  const waiting = p.props.some((x) => x.ref === n && x.status === 'pending');
  const back = [{ text: t(lang, 'btn.back'), data: `b:${uid}:${seq}:open` }];
  const b = (text, a) => ({ text, data: `b:${uid}:${seq}:${a}` });
  if (act === 'open') return this.edit(id, this.v.debtCard(lang, other, d, waiting, this.b.today()));
  if (waiting || d.status !== 'active') throw new Refused(waiting ? 'change_pending' : 'debt_not_active');
  const rem = this.v.money(lang, d.remaining, d.cur);
  const propose = (kind, body, msgId) => {
    this.b.proposeChange(this.uid, other, n, kind, body);
    this.fsm = { data: {}, typed: null };
    const key = { payment: 'pay.sent', correction: 'correct.sent', writeoff: 'writeoff.sent' }[kind];
    const screen = { html: t(lang, key, { name: p.name }), kb: [back] };
    return msgId ? this.edit(msgId, screen) : this.push(screen);
  };
  const typed = (fn) => { this.fsm.typed = fn; };
  switch (act) {
    case 'pay':
      typed((text) => propose('payment', { amount: amountOf(text) }));
      return this.edit(id, { html: t(lang, 'pay.ask', { remaining: rem }), kb: [[b(t(lang, 'btn.pay_full', { amount: rem }), 'payfull')], back] });
    case 'payfull': return propose('payment', { amount: d.remaining }, id);
    case 'correct':
      return this.edit(id, { html: t(lang, 'correct.ask'), kb: [[b(t(lang, 'btn.correct_amount'), 'camount'), b(t(lang, 'btn.correct_due'), 'cdue')], back] });
    case 'camount':
      typed((text) => propose('correction', { amount: amountOf(text) }));
      return this.edit(id, { html: t(lang, 'correct.amount', { amount: this.v.money(lang, d.principal, d.cur), paid: this.v.money(lang, d.paid, d.cur) }), kb: [back] });
    case 'cdue':
      return this.edit(id, { html: t(lang, 'correct.due', { due: this.v.day(d.due) }),
        kb: [[b(t(lang, 'btn.ext7'), 'ext7'), b(t(lang, 'btn.ext30'), 'ext30')], [b(t(lang, 'btn.due_type'), 'dtype')], back] });
    case 'ext7': case 'ext30': {
      const base = d.due > this.b.today() ? d.due : this.b.today();
      return propose('correction', { due: addDays(base, act === 'ext7' ? 7 : 30) }, id);
    }
    case 'dtype':
      typed((text) => {
        const due = parseDay(text);
        if (!due) throw new Refused('date');
        return propose('correction', { due });
      });
      return this.edit(id, { html: t(lang, 'create.due_type', { example: this.v.day(addDays(this.b.today(), 30)) }), kb: [back] });
    case 'wo':
      if (d.role !== 'lender') throw new Refused('only_lender');
      return this.edit(id, { html: t(lang, 'writeoff.ask', { amount: rem, name: p.name }), kb: [[b(t(lang, 'btn.writeoff_yes'), 'woyes')], back] });
    default: return propose('writeoff', {}, id);
  }
};

/** Messages the bot pushes on its own: questions from the other side, their answers, and reminders. */
P.deliver = function deliver(ev) {
  const lang = this.lang;
  const name = this.name(ev.from ?? ev.other);
  if (ev.type === 'ask') return this.push(this.v.ask(lang, name, ev.from, ev.prop, ev.debt));
  if (ev.type === 'answered') {
    const what = this.v.what(lang, ev.prop);
    const html = ev.prop.status === 'confirmed'
      ? this.t(lang, 'notify.confirmed', { name, what: new Raw(what), seal: ev.prop.seal })
      : this.t(lang, 'notify.rejected', { name, what: new Raw(what), reason: ev.prop.reason });
    return this.push({ html, kb: [[{ text: this.t(lang, 'btn.back'), data: 'n:menu' }]] });
  }
  const html = this.v.reminder(lang, name, ev.debt, ev.kind, this.uid, this.b.today());
  return this.push({ html, kb: [[{ text: this.t(lang, 'btn.open'), data: `b:${ev.other}:${ev.debt.seq}:open` }]] });
};

export { BotSim };
