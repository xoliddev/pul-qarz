// JS port of pulqarz/bot/views.py: the same screens, locale keys and callback data ("n:menu", "a:1002:7:1"...).
import { daysLeft, escapeHtml, formatNumber, Raw } from '../shared/calc.js';

export function makeViews(t) {
  const money = (lang, minor, cur) => t.money(lang, minor, cur);
  const day = (iso) => iso.split('-').reverse().join('.');
  const btn = (text, data) => ({ text, data });
  const back = (lang, data) => [btn(t(lang, 'btn.back'), data)];
  const localDay = (at) => day(new Date(Date.parse(at) + 5 * 3_600_000).toISOString().slice(0, 10));
  const left = (lang, due, today) => {
    const n = daysLeft(due, today);
    if (n > 0) return t(lang, 'left.in', { n });
    return n === 0 ? t(lang, 'left.today') : t(lang, 'left.over', { n: -n });
  };
  const amounts = (lang, byCur) => {
    const parts = Object.entries(byCur).filter(([, v]) => v).map(([c, v]) => money(lang, v, c));
    return parts.length ? parts.join(', ') : '0';
  };
  const what = (lang, p) => (p.kind === 'correction' ? t(lang, 'what.correction')
    : t(lang, `what.${p.kind}`, { amount: money(lang, p.amount, p.cur) }));
  const change = (lang, p) => {
    const parts = [];
    if (p.amount !== undefined && p.kind === 'correction') {
      parts.push(t(lang, 'change.amount', { from: money(lang, p.from_amount, p.cur), to: money(lang, p.amount, p.cur) }));
    }
    if (p.due !== undefined) parts.push(t(lang, 'change.due', { from: day(p.from_due), to: day(p.due) }));
    return new Raw(parts.join(', '));
  };
  const netLines = (lang, name, net) => ['UZS', 'USD'].filter((c) => net[c]).map((c) => t(lang,
    net[c] > 0 ? 'balance.they_owe' : 'balance.you_owe', { name, amount: money(lang, Math.abs(net[c]), c) }));

  return {
    what, money, day,
    mainMenu(lang, pending, hello = false) {
      const kb = [
        [btn(t(lang, 'btn.lent'), 'n:lent'), btn(t(lang, 'btn.borrowed'), 'n:borrowed')],
        [btn(t(lang, 'btn.balance'), 'n:balance'), btn(t(lang, 'btn.people'), 'n:people')],
        [{ text: t(lang, 'btn.app'), app: true }],
        [btn(t(lang, 'btn.lang'), 'n:lang')],
      ];
      if (pending) kb.unshift([btn(t(lang, 'btn.pending', { n: pending }), 'n:pending')]);
      return { html: t(lang, hello ? 'start.hello' : 'start.menu'), kb };
    },
    balance(lang, s) {
      const lines = [t(lang, 'balance.title')];
      if (!Object.values(s.owed_to_me).some(Boolean) && !Object.values(s.i_owe).some(Boolean)) {
        lines.push(t(lang, 'balance.none'));
      } else {
        lines.push(t(lang, 'balance.owed', { list: new Raw(amounts(lang, s.owed_to_me)) }),
          t(lang, 'balance.owe', { list: new Raw(amounts(lang, s.i_owe)) }), '');
        for (const [uid, net] of Object.entries(s.people)) lines.push(...netLines(lang, s.names[uid], net));
      }
      return { html: lines.join('\n'), kb: [back(lang, 'n:menu')] };
    },
    people(lang, s) {
      const kb = Object.entries(s.names).map(([uid, name]) => {
        const net = s.people[uid] ?? {};
        const abs = Object.fromEntries(Object.entries(net).map(([c, v]) => [c, Math.abs(v)]));
        return [btn((name + (Object.keys(net).length ? ` · ${amounts(lang, abs)}` : '')).slice(0, 60), `p:${uid}:open`)];
      });
      return { html: kb.length ? t(lang, 'people.title') : t(lang, 'people.empty'), kb: [...kb, back(lang, 'n:menu')] };
    },
    person(lang, p, today) {
      const lines = [`<b>${escapeHtml(p.name)}</b>`, ...netLines(lang, p.name, p.net)];
      if (!Object.keys(p.net).length) lines.push(t(lang, 'balance.even', { name: p.name }));
      const open = p.debts.filter((d) => d.status === 'active' || d.status === 'pending');
      lines.push('', open.length ? t(lang, 'person.open') : t(lang, 'person.none'));
      const kb = [];
      for (const d of open.slice(-8)) {
        lines.push(t(lang, 'debt.line', { seq: d.seq, remaining: money(lang, d.remaining, d.cur),
          left: d.status === 'active' ? left(lang, d.due, today) : t(lang, 'status.pending') }));
        kb.push([btn(t(lang, 'btn.debt', { seq: d.seq, amount: money(lang, d.remaining, d.cur) }), `b:${p.other}:${d.seq}:open`)]);
      }
      kb.push([btn(t(lang, 'btn.history'), `p:${p.other}:hist`), btn(t(lang, 'btn.verify'), `p:${p.other}:verify`)]);
      return { html: lines.join('\n'), kb: [...kb, back(lang, 'n:people')] };
    },
    debtCard(lang, uid, d, waiting, today) {
      let html = t(lang, 'debt.card', { seq: d.seq, role: t(lang, `role.${d.role}`), principal: money(lang, d.principal, d.cur),
        paid: money(lang, d.paid, d.cur), remaining: money(lang, d.remaining, d.cur), due: day(d.due),
        left: left(lang, d.due, today), note: d.note || '—', status: t(lang, `status.${d.status}`), seal: d.seal || '—' });
      const kb = [];
      if (waiting) html += `\n\n${t(lang, 'debt.waiting')}`;
      else if (d.status === 'active') {
        kb.push([btn(t(lang, 'btn.pay'), `b:${uid}:${d.seq}:pay`), btn(t(lang, 'btn.correct'), `b:${uid}:${d.seq}:correct`)]);
        if (d.role === 'lender') kb.push([btn(t(lang, 'btn.writeoff'), `b:${uid}:${d.seq}:wo`)]);
      }
      return { html, kb: [...kb, back(lang, `p:${uid}:open`)] };
    },
    history(lang, p) {
      const roles = Object.fromEntries(p.debts.map((d) => [d.seq, d.role]));
      let lines = [t(lang, 'history.title', { name: p.name })];
      for (const x of p.props) {
        let body;
        if (x.kind === 'debt') body = t(lang, 'hist.debt', { ref: x.ref, amount: money(lang, x.amount, x.cur), role: t(lang, `role.${roles[x.ref]}`) });
        else if (x.kind === 'correction') body = t(lang, 'hist.correction', { ref: x.ref, change: change(lang, x) });
        else body = t(lang, `hist.${x.kind}`, { ref: x.ref, amount: money(lang, x.amount, x.cur) });
        const status = x.status === 'confirmed' ? t(lang, 'hist.sealed', { seal: x.seal })
          : x.status === 'rejected' ? t(lang, 'hist.rejected', { reason: x.reason }) : t(lang, 'hist.waiting');
        lines.push(`${localDay(x.at)} · ${body} · ${status}`);
      }
      if (!p.props.length) lines.push(t(lang, 'history.empty'));
      if (lines.length > 41) lines = [lines[0], ...lines.slice(-40)];
      return { html: lines.join('\n'), kb: [back(lang, `p:${p.other}:open`)] };
    },
    verify(lang, uid, v) {
      const html = v.ok ? t(lang, 'verify.ok', { count: v.count, head: `${v.head.slice(0, 16)}…` })
        : t(lang, 'verify.bad', { seq: v.seq, reason: t(lang, `verify.reason.${v.reason}`) });
      return { html, kb: [back(lang, `p:${uid}:open`)] };
    },
    pending(lang, items) {
      const kb = items.slice(0, 20).map((i) => [btn(t(lang, 'pending.item', { name: i.name, what: new Raw(what(lang, i.prop)) }).slice(0, 60), `a:${i.other}:${i.prop.seq}:2`)]);
      return { html: kb.length ? t(lang, 'pending.title') : t(lang, 'pending.empty'), kb: [...kb, back(lang, 'n:menu')] };
    },
    ask(lang, name, uid, prop, debt) {
      let html;
      if (prop.kind === 'debt') {
        const line = t(lang, debt.lender === prop.by ? 'ask.lent_to_you' : 'ask.borrowed_from_you', { name });
        html = t(lang, 'ask.debt', { name, line: new Raw(line), amount: money(lang, debt.principal, debt.cur), due: day(debt.due), note: debt.note || '—' });
      } else if (prop.kind === 'correction') html = t(lang, 'ask.correction', { name, ref: prop.ref, change: change(lang, prop) });
      else html = t(lang, `ask.${prop.kind}`, { name, ref: prop.ref, amount: money(lang, prop.amount, prop.cur) });
      return { html, kb: [[btn(t(lang, 'btn.confirm'), `a:${uid}:${prop.seq}:1`), btn(t(lang, 'btn.reject'), `a:${uid}:${prop.seq}:0`)], back(lang, 'n:pending')] };
    },
    reasons(lang, uid, seq) {
      const kb = ['amount', 'none', 'date'].map((c) => [btn(t(lang, `reason.${c}`), `r:${uid}:${seq}:${c}`)]);
      kb.push([btn(t(lang, 'btn.reason_type'), `r:${uid}:${seq}:type`)]);
      return { html: t(lang, 'reject.why'), kb: [...kb, back(lang, `a:${uid}:${seq}:2`)] };
    },
    done: (lang, html) => ({ html, kb: [back(lang, 'n:menu')] }),
    reminder(lang, name, debt, kind, me, today) {
      const title = kind.startsWith('overdue') ? t(lang, 'remind.title.overdue', { n: -daysLeft(debt.due, today) })
        : t(lang, `remind.title.${kind}`);
      return t(lang, debt.lender === me ? 'remind.lender' : 'remind.borrower', { title,
        amount: money(lang, debt.principal - debt.paid, debt.cur), name, due: day(debt.due) });
    },
    cancelRow: (lang) => [btn(t(lang, 'btn.back'), 's:back'), btn(t(lang, 'btn.cancel'), 's:cancel')],
    formatNumber,
  };
}
