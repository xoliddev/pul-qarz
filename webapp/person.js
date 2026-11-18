// One person: net balance, debt cards with seals, the timeline, and a chain check done on this phone.
import { daysLeft } from '../shared/calc.js';
import { verifyChain } from '../shared/ledger.js';
import { openChange } from './form.js';
import { day, h, hue, initials, localDay, plain } from './util.js';

function leftText(ctx, due, today) {
  const n = daysLeft(due, today);
  if (n > 0) return ctx.P('left.in', { n });
  return n === 0 ? ctx.P('left.today') : ctx.P('left.over', { n: -n });
}

function debtCard(ctx, uid, d, props, today) {
  const waiting = props.find((x) => x.ref === d.seq && x.status === 'pending');
  const money = (v) => plain(ctx.M(v, d.cur));
  const pct = d.principal ? Math.round((d.paid / d.principal) * 100) : 0;
  let foot = null;
  if (waiting && waiting.mine) {
    foot = h('p', { class: 'pq-chip wait' }, ctx.P('app.waiting_other', { name: ctx.names[uid] ?? '' }));
  } else if (waiting) {
    foot = h('div', { class: 'pq-row' },
      h('span', { class: 'pq-chip wait', html: ctx.T(`what.${waiting.kind}`, { amount: money(waiting.amount ?? 0) }) }),
      h('button', { class: 'pq-btn primary small', type: 'button', 'data-testid': 'confirm',
        onclick: () => ctx.answer(uid, waiting.seq, true) }, ctx.P('btn.confirm')),
      h('button', { class: 'pq-btn ghost small', type: 'button', onclick: () => ctx.reject(uid, waiting.seq) },
        ctx.P('btn.reject')));
  } else if (d.status === 'active') {
    foot = h('div', { class: 'pq-row' },
      h('button', { class: 'pq-btn small', type: 'button', 'data-testid': 'pay',
        onclick: () => openChange(ctx, uid, d, 'payment') }, ctx.P('btn.pay')),
      h('button', { class: 'pq-btn small', type: 'button', onclick: () => openChange(ctx, uid, d, 'correction') },
        ctx.P('btn.correct')),
      d.role === 'lender' ? h('button', { class: 'pq-btn small ghost', type: 'button',
        onclick: () => openChange(ctx, uid, d, 'writeoff') }, ctx.P('btn.writeoff')) : null);
  }
  return h('article', { class: `pq-card pq-debt ${d.role}`, 'data-status': d.status, 'data-testid': 'debt' },
    d.seal ? ctx.seal(d.seal) : null,
    h('div', { class: 'pq-debt-head' }, h('span', {}, `#${d.seq} · ${ctx.P(`role.${d.role}`)}`),
      h('span', { class: `pq-status ${d.status}` }, ctx.P(`status.${d.status}`))),
    h('div', { class: 'pq-debt-amount' }, h('strong', {}, money(d.remaining)),
      d.paid ? h('small', {}, ` / ${money(d.principal)}`) : null),
    d.paid ? h('div', { class: 'pq-progress', style: `--p:${pct}%`, title: `${ctx.P('app.paid')}: ${money(d.paid)}` }) : null,
    h('dl', { class: 'pq-facts' },
      h('div', {}, h('dt', {}, ctx.P('app.due_short')), h('dd', {}, `${day(d.due)} · ${d.status === 'active'
        ? leftText(ctx, d.due, today) : ctx.P(`status.${d.status}`)}`)),
      d.note ? h('div', {}, h('dt', {}, ctx.P('app.note').replace(/\s*\(.*\)/, '')), h('dd', {}, d.note)) : null),
    foot);
}

function timeline(ctx, p, broken) {
  const debts = Object.fromEntries(p.debts.map((d) => [d.seq, d]));
  return h('ol', { class: 'pq-timeline', 'data-testid': 'timeline' }, p.props.map((x) => {
    const amount = plain(ctx.M(x.amount ?? 0, x.cur));
    let text;
    if (x.kind === 'debt') text = ctx.T('hist.debt', { ref: x.ref, amount, role: ctx.P(`role.${debts[x.ref].role}`) });
    else if (x.kind === 'correction') {
      const parts = [];
      if (x.amount !== undefined) parts.push(ctx.P('change.amount', { from: plain(ctx.M(x.from_amount, x.cur)), to: amount }));
      if (x.due !== undefined) parts.push(ctx.P('change.due', { from: day(x.from_due), to: day(x.due) }));
      text = ctx.T('hist.correction', { ref: x.ref, change: parts.join(', ') });
    } else text = ctx.T(`hist.${x.kind}`, { ref: x.ref, amount });
    const bad = broken && (x.seq >= broken || (x.answer ?? 0) >= broken);
    const status = x.status === 'confirmed' ? ctx.seal(x.seal, true)
      : h('span', { class: `pq-chip ${x.status === 'rejected' ? 'bad' : 'wait'}`,
        html: x.status === 'rejected' ? ctx.T('hist.rejected', { reason: x.reason }) : ctx.T('hist.waiting') });
    return h('li', { class: `${x.status}${bad ? ' broken' : ''}` },
      h('time', {}, localDay(x.at)), h('span', { class: 'pq-tl-text', html: text }), status);
  }));
}

export async function renderPerson(ctx, uid) {
  const p = await ctx.api.person(uid);
  ctx.names[uid] = p.name;
  const today = p.today ?? ctx.today;
  const check = ctx.checked?.[uid] || !p.verify.ok ? verifyChain(p.entries) : null; // recomputed here, not trusted from the server
  const verifyBox = h('div', { class: `pq-verify ${check ? (check.ok ? 'ok' : 'bad') : ''}`, 'data-testid': 'verify' },
    h('button', { class: 'pq-btn small', type: 'button', 'data-testid': 'verify-btn', onclick: () => {
      ctx.checked = { ...(ctx.checked ?? {}), [uid]: true };
      ctx.refresh();
    } }, ctx.P('btn.verify')),
    check ? h('div', { class: 'pq-verify-result' },
      h('b', {}, check.ok ? `✓ ${ctx.P('app.verify_ok')}` : `✕ ${ctx.P('app.verify_bad', { seq: check.seq })}`),
      h('small', {}, check.ok ? ctx.P('app.verify_local', { count: check.count, head: `${check.head.slice(0, 12)}…` })
        : ctx.P(`verify.reason.${check.reason}`))) : null);
  const open = p.debts.filter((d) => d.status === 'active' || d.status === 'pending').reverse();
  const closed = p.debts.filter((d) => !open.includes(d)).reverse();
  return [
    ctx.header(null, true),
    h('section', { class: 'pq-hero' }, h('span', { class: 'pq-avatar big', style: `--h:${hue(p.name)}` }, initials(p.name)),
      h('div', {}, h('h1', { class: 'pq-title' }, p.name), h('p', { class: 'pq-net' }, ctx.netText(p.net, p.name)))),
    verifyBox,
    h('h2', { class: 'pq-h2' }, ctx.P('app.debts')),
    open.length ? open.map((d) => debtCard(ctx, uid, d, p.props, today)) : h('p', { class: 'pq-empty' }, ctx.P('person.none')),
    closed.length ? h('details', { class: 'pq-closed' }, h('summary', {}, `${ctx.P('app.closed')} (${closed.length})`),
      closed.map((d) => debtCard(ctx, uid, d, p.props, today))) : null,
    h('h2', { class: 'pq-h2' }, ctx.P('app.timeline')),
    timeline(ctx, p, check && !check.ok ? check.seq : null),
  ];
}
