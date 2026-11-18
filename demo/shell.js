// Demo page: Ali's and Vali's phones, the guided story, "+1 day" and the language switch.
import { makeT } from '../shared/calc.js';
import { mountApp } from '../webapp/ui.js';
import { h, loadCatalogs, plain } from '../webapp/util.js';
import { BotSim } from './bot-flows.js';
import { makeViews } from './bot-views.js';
import { createPhone } from './phone.js';
import { ALI, createDemo, VALI } from './seed.js';
import { runStep, STEPS } from './story.js';

const catalogs = await loadCatalogs(new URL('../shared/locales/', import.meta.url));
const t = makeT(catalogs);
const views = makeViews(t);
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};
let lang = store.get('pulqarz.demo.lang') === 'ru' ? 'ru' : 'uz';
const texts = { P: (key, params) => plain(t(lang, key, params)) };
const backend = createDemo({ lang });
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

const people = { [ALI]: { who: 'ali', label: 'Ali', role: 'demo.lender' }, [VALI]: { who: 'vali', label: 'Vali', role: 'demo.borrower' } };
const phones = {};
const bots = {};
const apps = {};
let shown = ALI;

function openApp(uid, relaunch) {
  phones[uid].show('app');
  if (relaunch) mount(uid);
  else apps[uid].refresh();
}

function onLink(fromUid, link) {
  const other = fromUid === ALI ? VALI : ALI;
  const token = /start=(d_[A-Za-z0-9_-]+)/.exec(link)?.[1];
  if (!token) return;
  focus(other, 'chat');
  bots[other].start(token);
}

// The demo phones always use Telegram's light theme, so the frame, the chat and the Mini App match.
const demoTg = (uid) => ({ colorScheme: 'light', openTelegramLink: (url) => onLink(uid, decodeURIComponent(url)) });

function mount(uid) {
  apps[uid] = mountApp(phones[uid].appRoot, { api: backend.apiFor(uid), catalogs, lang, tg: demoTg(uid),
    onLang: (l) => setLang(l) });
}

for (const uid of [ALI, VALI]) {
  const meta = people[uid];
  bots[uid] = new BotSim(backend, uid, t, views, {
    onChange: () => phones[uid]?.renderChat(),
    onAlert: (text) => phones[uid].alert(text),
  });
  phones[uid] = createPhone({ ...meta, bot: bots[uid], texts, onOpenApp: (relaunch) => openApp(uid, relaunch),
    onLink: (link) => onLink(uid, link) });
}

backend.on((ev) => {
  if (ev.type === 'clock') dateEl.textContent = texts.P('demo.date', { date: views.day(ev.today) });
  if (ev.type === 'tamper') {
    phones[VALI].alert(texts.P('demo.tampered', { seq: ev.seq }));
  }
  if (bots[ev.to]) {
    const msg = bots[ev.to].deliver(ev);
    phones[ev.to].ping(msg.html);
  }
  for (const uid of [ALI, VALI]) {
    const root = phones[uid].appRoot;
    if (root.dataset.screen !== 'form' && !root.querySelector('.pq-backdrop')) apps[uid]?.refresh();
  }
});

function focus(uid, pane) {
  phones[uid].show(pane);
  if (pane === 'app') apps[uid].refresh();
  if (window.matchMedia('(max-width: 600px)').matches) pick(uid);
}

// ── page ──
const dateEl = h('span', { class: 'demo-date', 'data-testid': 'demo-date' });
const badgeText = h('span');
const langBtn = h('button', { class: 'demo-btn', type: 'button', 'data-testid': 'demo-lang', onclick: () => setLang(lang === 'uz' ? 'ru' : 'uz') });
const skipBtn = h('button', { class: 'demo-btn solid', type: 'button', 'data-testid': 'skip-day', onclick: () => backend.skipDays(1) });
const resetBtn = h('button', { class: 'demo-btn', type: 'button', onclick: () => window.location.reload() });
const bar = h('header', { class: 'demo-bar' },
  h('a', { class: 'demo-logo', href: './' }, h('span', { class: 'demo-mark' }, 'PQ'), 'Pul Qarz'),
  h('span', { class: 'demo-badge', 'data-testid': 'demo-badge' }, h('span', { class: 'dot' }), badgeText), dateEl,
  h('div', { class: 'demo-tools' }, langBtn, skipBtn, resetBtn,
    h('a', { class: 'demo-btn gh', href: 'https://github.com/xoliddev/pul-qarz', target: '_blank', rel: 'noopener' }, 'GitHub')));
const title = h('h1');
const lead = h('p');
let done = 0;
let running = false;
const storyBtns = STEPS.map((key, i) => h('button', { class: 'story-btn', type: 'button', 'data-testid': `story-${i + 1}`,
  onclick: async () => {
    if (running || i !== done) return;
    running = true;
    paintStory();
    try {
      await runStep(i + 1, { backend, bots, wait, focus });
      done = i + 1;
    } catch (err) {
      console.error(err); // eslint-disable-line no-console
      phones[shown].alert(t(lang, 'err.generic'));
    }
    running = false;
    paintStory();
  } }, h('b', {}, String(i + 1)), h('span')));
function paintStory() {
  storyBtns.forEach((b, i) => {
    b.lastChild.textContent = texts.P(`demo.${STEPS[i]}`);
    b.classList.toggle('done', i < done);
    b.classList.toggle('next', i === done && !running);
    b.disabled = running || i !== done;
  });
}
const whoBtns = [ALI, VALI].map((uid) => h('button', { type: 'button', 'data-testid': `switch-${people[uid].who}`, onclick: () => pick(uid) }, people[uid].label));
function pick(uid) {
  shown = uid;
  whoBtns.forEach((b, i) => b.classList.toggle('on', [ALI, VALI][i] === uid));
  for (const id of [ALI, VALI]) phones[id].side.classList.toggle('show', id === uid);
}

function paintTexts() {
  document.documentElement.lang = lang;
  badgeText.textContent = texts.P('demo.badge');
  dateEl.textContent = texts.P('demo.date', { date: views.day(backend.today()) });
  langBtn.textContent = lang === 'uz' ? 'RU' : 'UZ';
  skipBtn.textContent = texts.P('demo.skip');
  skipBtn.title = texts.P('demo.skip_title');
  resetBtn.textContent = texts.P('demo.reset');
  title.textContent = texts.P('demo.title');
  lead.textContent = texts.P('demo.lead');
  paintStory();
  for (const uid of [ALI, VALI]) phones[uid].renderLabels();
}

function setLang(next) {
  if (next === lang) return;
  lang = next;
  store.set('pulqarz.demo.lang', lang);
  for (const uid of [ALI, VALI]) {
    backend.setLang(uid, lang);
    mount(uid);
  }
  paintTexts();
}

document.body.append(bar, h('section', { class: 'demo-intro' }, title, lead), h('nav', { class: 'story', 'aria-label': 'story' }, storyBtns),
  h('div', { class: 'who-switch', role: 'tablist' }, whoBtns),
  h('main', { class: 'demo-stage' }, phones[ALI].side, phones[VALI].side));
for (const uid of [ALI, VALI]) {
  mount(uid);
  bots[uid].start();
}
pick(ALI);
paintTexts();
document.body.dataset.ready = '1';
