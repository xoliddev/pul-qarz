// The Mini App: mountApp(root, {api, catalogs, lang, tg}) renders into `root` and keeps all state per instance,
// so the browser demo can run two of them (Ali's and Vali's phones) side by side.
import { renderForm } from './form.js';
import { renderPerson } from './person.js';
import { applyTheme, h, haptic, hue, initials, plain, texts } from './util.js';

export function mountApp(root, { api, catalogs, lang = 'uz', tg = null, onLang = null }) {
  const t = texts(catalogs);
  const stack = [];
  const ctx = {
    root, api, tg, lang, today: null, seen: new Set(), names: {},
    T: (key, params) => t(ctx.lang, key, params),
    P: (key, params) => plain(t(ctx.lang, key, params)),
    M: (minor, cur) => t.money(ctx.lang, minor, cur),
    go, back, refresh: render, toast, sheet, fail, seal,
  };
  root.classList.add('pq');
  applyTheme(root, tg);
  const main = h('main', { class: 'pq-main' });
  const toasts = h('div', { class: 'pq-toasts', 'aria-live': 'polite' });
  root.replaceChildren(main, toasts);

  function go(screen, arg) {
    stack.push({ screen, arg });
    render();
    root.scrollTop = 0;
  }

  function back() {
    stack.pop();
    render();
  }

  function syncBackButton() {
    const bb = tg?.BackButton;
    if (!bb) return;
    if (stack.length) bb.show();
    else bb.hide();
  }
  tg?.BackButton?.onClick(() => stack.length && back());

  function toast(html, kind = 'ok') {
    const el = h('div', { class: `pq-toast ${kind}`, html, role: 'status' });
    toasts.append(el);
    setTimeout(() => el.classList.add('out'), 2600);
    setTimeout(() => el.remove(), 3000);
  }

  function fail(err) {
    haptic(tg, 'error');
    const code = err?.code ?? 'generic';
    const key = catalogs[ctx.lang][`err.${code}`] ? `err.${code}` : code === 'offline' ? 'app.offline' : 'err.generic';
    toast(ctx.T(key, { example: '25.12.2026' }), 'bad');
  }

  /** Bottom sheet inside this app instance. `build(close)` returns the sheet's content nodes. */
  function sheet(title, build) {
    const close = () => {
      wrap.classList.add('out');
      setTimeout(() => wrap.remove(), 180);
    };
    const panel = h('div', { class: 'pq-sheet', role: 'dialog', 'aria-label': plain(title) },
      h('div', { class: 'pq-sheet-head' }, h('h3', { html: title }),
        h('button', { class: 'pq-x', type: 'button', 'aria-label': ctx.P('app.close'), onclick: close }, '×')),
      build(close));
    const wrap = h('div', { class: 'pq-backdrop', onclick: (e) => e.target === wrap && close() }, panel);
    root.append(wrap);
    panel.querySelector('input, textarea')?.focus({ preventScroll: true });
    return close;
  }

  /** The "muhr": a round stamp with the short hash. Animates the first time this instance shows it. */
  function seal(code, small = false) {
    const fresh = !ctx.seen.has(code);
    ctx.seen.add(code);
    return h('span', { class: `pq-seal${small ? ' small' : ''}${fresh && ctx.animate ? ' stamp' : ''}`,
      title: code, 'data-testid': 'seal' },
    h('span', { class: 'pq-seal-word' }, ctx.P('app.seal')), h('b', {}, code));
  }

  function header(title, withBack) {
    const langBtn = h('button', { class: 'pq-lang', type: 'button', 'data-testid': 'lang',
      onclick: async () => {
        ctx.lang = ctx.lang === 'uz' ? 'ru' : 'uz';
        onLang?.(ctx.lang);
        api.setLang(ctx.lang).catch(() => {});
        render();
      } }, ctx.lang === 'uz' ? 'RU' : 'UZ');
    return h('header', { class: 'pq-top' },
      withBack ? h('button', { class: 'pq-back', type: 'button', onclick: back, 'data-testid': 'back' },
        ctx.P('btn.back')) : h('div', { class: 'pq-brand' }, h('span', { class: 'pq-mark' }, 'PQ'), 'Pul Qarz'),
      title ? h('h1', { class: 'pq-title' }, title) : null, langBtn);
  }
  ctx.header = header;

  function amountsBlock(label, byCur, cls) {
    const lines = Object.entries(byCur).filter(([c, v]) => v || c === 'UZS');
    return h('section', { class: `pq-total ${cls}` }, h('span', { class: 'pq-total-label' }, label),
      lines.map(([c, v]) => h('strong', { class: 'pq-total-amount' }, plain(ctx.M(v, c)))));
  }

  function netText(net, name) {
    const parts = Object.entries(net).map(([c, v]) => `${v > 0 ? ctx.P('app.they_owe') : ctx.P('app.you_owe')} ${plain(ctx.M(Math.abs(v), c))}`);
    return parts.length ? parts.join(' · ') : ctx.P('app.even', { name });
  }
  ctx.netText = netText;

  async function home() {
    const d = await api.me();
    ctx.today = d.today;
    if (!ctx.langSynced && d.me?.lang) ctx.lang = d.me.lang; // the language saved in the bot wins on first load
    ctx.langSynced = true;
    for (const p of d.people) ctx.names[p.id] = p.name;
    const pending = d.pending.map((p) => h('article', { class: 'pq-card pq-ask', 'data-testid': 'pending' },
      h('div', { class: 'pq-ask-who' }, h('span', { class: 'pq-avatar', style: `--h:${hue(p.name)}` }, initials(p.name)),
        h('div', {}, h('b', {}, p.name), h('span', { html: ctx.T(`what.${p.prop.kind}`, {
          amount: plain(ctx.M(p.prop.amount ?? 0, p.prop.cur)) }) }))),
      h('div', { class: 'pq-row' },
        h('button', { class: 'pq-btn primary', type: 'button', 'data-testid': 'confirm',
          onclick: () => ctx.answer(p.other, p.prop.seq, true) }, ctx.P('btn.confirm')),
        h('button', { class: 'pq-btn ghost', type: 'button', onclick: () => ctx.reject(p.other, p.prop.seq) },
          ctx.P('btn.reject')))));
    const people = d.people.map((p) => h('button', { class: 'pq-person', type: 'button', 'data-testid': 'person',
      onclick: () => go('person', p.id) },
    h('span', { class: 'pq-avatar', style: `--h:${hue(p.name)}` }, initials(p.name)),
    h('span', { class: 'pq-person-text' }, h('b', {}, p.name), h('small', {}, netText(p.net, p.name))),
    h('span', { class: 'pq-chev', 'aria-hidden': 'true' }, '›')));
    return [
      header(null, false),
      h('div', { class: 'pq-totals' }, amountsBlock(ctx.P('app.owed'), d.owed_to_me, 'plus'),
        amountsBlock(ctx.P('app.owe'), d.i_owe, 'minus')),
      h('div', { class: 'pq-row pq-actions' },
        h('button', { class: 'pq-btn primary big', type: 'button', 'data-testid': 'new-lent',
          onclick: () => go('form', 'lent') }, ctx.P('btn.lent')),
        h('button', { class: 'pq-btn big', type: 'button', 'data-testid': 'new-borrowed',
          onclick: () => go('form', 'borrowed') }, ctx.P('btn.borrowed'))),
      pending.length ? h('h2', { class: 'pq-h2' }, ctx.P('app.pending')) : null, pending,
      h('h2', { class: 'pq-h2' }, ctx.P('app.people')),
      people.length ? h('div', { class: 'pq-list' }, people) : h('p', { class: 'pq-empty' }, ctx.P('app.empty')),
    ];
  }

  ctx.answer = async (uid, seq, ok, reason) => {
    try {
      const r = await api.answer(uid, { seq, ok, reason });
      haptic(tg, 'success');
      toast(ok ? ctx.T('done.confirmed', { seal: r.seal }) : ctx.T('done.rejected', { name: ctx.names[uid] ?? '' }));
      await render();
    } catch (err) {
      fail(err);
    }
  };

  ctx.reject = (uid, seq) => {
    sheet(ctx.T('reject.why'), (close) => {
      const input = h('textarea', { class: 'pq-input', maxlength: 200, rows: 2, placeholder: ctx.P('app.reason') });
      const pick = (text) => {
        close();
        ctx.answer(uid, seq, false, text);
      };
      return h('div', { class: 'pq-sheet-body' },
        ['amount', 'none', 'date'].map((c) => h('button', { class: 'pq-chip', type: 'button',
          onclick: () => pick(ctx.P(`reason.${c}`)) }, ctx.P(`reason.${c}`))),
        input, h('button', { class: 'pq-btn primary', type: 'button', onclick: () => input.value.trim() && pick(input.value.trim()) },
          ctx.P('app.send')));
    });
  };

  let rendering = Promise.resolve();
  async function render() {
    const top = stack.at(-1) ?? { screen: 'home' };
    const job = async () => {
      try {
        const nodes = top.screen === 'person' ? await renderPerson(ctx, top.arg)
          : top.screen === 'form' ? await renderForm(ctx, top.arg) : await home();
        main.replaceChildren(...nodes.flat().filter(Boolean));
        root.dataset.screen = top.screen;
      } catch (err) {
        if (err?.code === 'not_found' && stack.length) {
          stack.pop();
          return job();
        }
        fail(err);
      }
      syncBackButton();
      ctx.animate = true;
    };
    rendering = rendering.then(job, job);
    return rendering;
  }

  render();
  return { refresh: render, back, go, get lang() { return ctx.lang; } };
}
