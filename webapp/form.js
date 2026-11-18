// New-debt form, the share-link card, and the sheets for payment / correction / write-off.
import { parseAmount } from '../shared/calc.js';
import { addDays, h, haptic, plain } from './util.js';

function field(label, control, hint) {
  return h('label', { class: 'pq-field' }, h('span', {}, label), control, hint ? h('small', {}, hint) : null);
}

function segmented(name, options, value, onPick) {
  const wrap = h('div', { class: 'pq-seg', role: 'radiogroup' });
  for (const [val, label] of options) {
    const b = h('button', { class: `pq-seg-btn${val === value ? ' on' : ''}`, type: 'button', role: 'radio',
      'aria-checked': String(val === value), 'data-value': val, 'data-testid': `${name}-${val}`,
      onclick: () => {
        for (const x of wrap.children) {
          x.classList.toggle('on', x === b);
          x.setAttribute('aria-checked', String(x === b));
        }
        onPick(val);
      } }, label);
    wrap.append(b);
  }
  return wrap;
}

function shareCard(ctx, res) {
  const share = `https://t.me/share/url?${new URLSearchParams({ url: res.link, text: ctx.P('share.text') })}`;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(res.link);
      ctx.toast(ctx.T('app.copied'));
    } catch {
      input.select();
    }
  };
  const input = h('input', { class: 'pq-input mono', readonly: true, value: res.link, 'data-testid': 'share-link',
    onfocus: (e) => e.target.select() });
  return [
    ctx.header(null, true),
    h('section', { class: 'pq-card pq-share' },
      h('h1', { class: 'pq-title' }, ctx.P('app.link_title', { name: res.name })),
      input,
      h('div', { class: 'pq-row' },
        h('button', { class: 'pq-btn primary', type: 'button', onclick: () => (ctx.tg?.openTelegramLink
          ? ctx.tg.openTelegramLink(share) : window.open(share, '_blank', 'noopener')) }, ctx.P('btn.share')),
        h('button', { class: 'pq-btn', type: 'button', onclick: copy }, ctx.P('app.copy'))),
      h('p', { class: 'pq-hint' }, ctx.P('app.link_hint'))),
  ];
}

export async function renderForm(ctx, direction) {
  if (ctx.shared) {
    const res = ctx.shared;
    ctx.shared = null;
    return shareCard(ctx, res);
  }
  if (!ctx.today) ctx.today = (await ctx.api.me()).today;
  const st = { other: null, cur: 'UZS', due: addDays(ctx.today, 14) };
  const contacts = Object.entries(ctx.names);
  const nameInput = h('input', { class: 'pq-input', maxlength: 40, autocomplete: 'off', 'data-testid': 'name',
    placeholder: plain(ctx.T('create.name')).split(': ').pop() });
  const nameField = field(ctx.P('app.name'), nameInput);
  const amount = h('input', { class: 'pq-input amount', inputmode: 'decimal', autocomplete: 'off', maxlength: 24,
    placeholder: '1 500 000', 'data-testid': 'amount' });
  const dateInput = h('input', { class: 'pq-input', type: 'date', min: ctx.today, value: st.due, 'data-testid': 'due',
    onchange: (e) => { st.due = e.target.value; } });
  const note = h('textarea', { class: 'pq-input', maxlength: 200, rows: 2, 'data-testid': 'note' });
  const pickPerson = (val) => {
    st.other = val === 'new' ? null : Number(val);
    nameField.hidden = val !== 'new';
  };
  const people = contacts.length ? segmented('who', [...contacts.map(([id, n]) => [id, n]), ['new', ctx.P('app.new_person')]],
    'new', pickPerson) : null;
  const submit = h('button', { class: 'pq-btn primary big', type: 'submit', 'data-testid': 'submit' }, ctx.P('app.send'));
  const form = h('form', { class: 'pq-form', novalidate: true, onsubmit: async (e) => {
    e.preventDefault();
    let minor;
    try {
      minor = parseAmount(amount.value);
    } catch {
      amount.focus();
      return ctx.fail({ code: 'amount' });
    }
    submit.disabled = true;
    try {
      const res = await ctx.api.create({ direction, other: st.other ?? undefined, name: st.other ? undefined : nameInput.value,
        amount: amount.value, cur: st.cur, due: st.due, note: note.value });
      haptic(ctx.tg, 'success');
      if (res.link) {
        ctx.shared = res;
        ctx.refresh();
      } else {
        ctx.toast(ctx.T('create.sent', { name: ctx.names[st.other] ?? '' }));
        ctx.back();
      }
    } catch (err) {
      ctx.fail(err);
    } finally {
      submit.disabled = false;
    }
    return minor;
  } },
  people ? field(ctx.P('app.person'), people) : null, nameField,
  field(ctx.P('app.amount'), h('div', { class: 'pq-amount-row' }, amount,
    segmented('cur', [['UZS', 'UZS'], ['USD', 'USD']], 'UZS', (c) => { st.cur = c; }))),
  field(ctx.P('app.due'), h('div', {}, segmented('due', [[7, ctx.P('btn.due7')], [14, ctx.P('btn.due14')],
    [30, ctx.P('btn.due30')]], 14, (n) => { st.due = addDays(ctx.today, n); dateInput.value = st.due; }), dateInput)),
  field(ctx.P('app.note'), note), submit);
  return [ctx.header(null, true), h('h1', { class: 'pq-title pad' }, ctx.P(`create.who_${direction}`)), form];
}

/** Payment, correction or write-off: a new entry that the other side must confirm. */
export function openChange(ctx, uid, d, kind) {
  const money = (v) => plain(ctx.M(v, d.cur));
  const send = async (body, close, doneKey) => {
    try {
      await ctx.api.change(uid, { seq: d.seq, kind, ...body });
      close();
      haptic(ctx.tg, 'success');
      ctx.toast(ctx.T(doneKey, { name: ctx.names[uid] ?? '' }));
      ctx.refresh();
    } catch (err) {
      ctx.fail(err);
    }
  };
  if (kind === 'payment') {
    ctx.sheet(ctx.T('btn.pay'), (close) => {
      const input = h('input', { class: 'pq-input amount', inputmode: 'decimal', maxlength: 24, 'data-testid': 'pay-amount' });
      return h('div', { class: 'pq-sheet-body' }, h('p', { html: ctx.T('pay.ask', { remaining: money(d.remaining) }) }),
        h('button', { class: 'pq-chip', type: 'button', onclick: () => send({ amount: `${Math.floor(d.remaining / 100)}.${String(d.remaining % 100).padStart(2, '0')}` }, close, 'pay.sent') },
          ctx.P('btn.pay_full', { amount: money(d.remaining) })),
        input, h('button', { class: 'pq-btn primary', type: 'button', 'data-testid': 'pay-send',
          onclick: () => send({ amount: input.value }, close, 'pay.sent') }, ctx.P('app.send')));
    });
  } else if (kind === 'correction') {
    ctx.sheet(ctx.T('correct.ask'), (close) => {
      const amt = h('input', { class: 'pq-input amount', inputmode: 'decimal', maxlength: 24, placeholder: money(d.principal) });
      const due = h('input', { class: 'pq-input', type: 'date', min: ctx.today ?? undefined, value: d.due });
      return h('div', { class: 'pq-sheet-body' }, field(ctx.P('app.new_amount'), amt), field(ctx.P('app.new_due'), due),
        h('button', { class: 'pq-btn primary', type: 'button', onclick: () => send({
          amount: amt.value.trim() || undefined, due: due.value !== d.due ? due.value : undefined }, close, 'correct.sent') },
        ctx.P('app.send')));
    });
  } else {
    ctx.sheet(ctx.T('btn.writeoff'), (close) => h('div', { class: 'pq-sheet-body' },
      h('p', { html: ctx.T('writeoff.ask', { amount: money(d.remaining), name: ctx.names[uid] ?? '' }) }),
      h('button', { class: 'pq-btn primary', type: 'button', onclick: () => send({}, close, 'writeoff.sent') },
        ctx.P('btn.writeoff_yes'))));
  }
}
