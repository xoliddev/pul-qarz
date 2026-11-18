// The browser demo's logic, headless: seeding on any date (30 days in a row, across New Year and a leap day)
// and the whole guided story through the simulated bot.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { makeT } from '../shared/calc.js';
import { verifyChain } from '../shared/ledger.js';
import { BotSim } from '../demo/bot-flows.js';
import { makeViews } from '../demo/bot-views.js';
import { ALI, createDemo, DILNOZA, SARDOR, VALI } from '../demo/seed.js';
import { runStep } from '../demo/story.js';

const load = (l) => JSON.parse(readFileSync(new URL(`../shared/locales/${l}.json`, import.meta.url), 'utf8'));
const t = makeT({ uz: load('uz'), ru: load('ru') });
const views = makeViews(t);
const DAY = 86_400_000;
const noon = (iso) => Date.parse(`${iso}T07:00:00Z`); // 12:00 in Tashkent

function world(nowMs, lang = 'uz') {
  let now = nowMs;
  const backend = createDemo({ now: () => now, lang });
  const alerts = [];
  const bots = {};
  for (const uid of [ALI, VALI]) {
    bots[uid] = new BotSim(backend, uid, t, views, { onAlert: (x) => alerts.push(x) });
    bots[uid].start();
  }
  backend.on((ev) => bots[ev.to]?.deliver(ev));
  return { backend, bots, alerts, advance: (ms) => { now += ms; } };
}

function checkSeed(backend) {
  for (const pair of Object.keys(backend.chains)) assert.equal(verifyChain(backend.entries(pair)).ok, true, pair);
  const ali = backend.summary(ALI);
  assert.equal(ali.i_owe.USD, 15_000);
  assert.equal(ali.owed_to_me.UZS, 0);
  assert.equal(backend.summary(VALI).owed_to_me.UZS, 150_000_000);
  assert.deepEqual(Object.keys(ali.names).map(Number), [VALI, SARDOR]);
  assert.equal(backend.summary(DILNOZA).i_owe.UZS, 150_000_000);
}

const starts = [new Date(Date.now() + 5 * 3_600_000).toISOString().slice(0, 10), '2026-12-15', '2028-02-10'];
for (const start of starts) {
  test(`seed works on 30 consecutive days from ${start}`, () => {
    for (let i = 0; i < 30; i++) {
      const { backend } = world(noon(start) + i * DAY);
      checkSeed(backend);
    }
  });
}

test('seed also works late at night and just after midnight in Tashkent', () => {
  for (const iso of ['2026-12-31T18:59:00Z', '2026-12-31T19:01:00Z', '2027-02-28T23:30:00Z']) {
    checkSeed(world(Date.parse(iso)).backend);
  }
});

async function story(start, lang = 'uz') {
  const w = world(noon(start), lang);
  const { backend, bots } = w;
  await runStep(1, w);
  assert.match(bots[VALI].messages.at(-1).html, /1 500 000/);
  assert.ok(bots[VALI].messages.at(-1).kb[0][0].data.startsWith(`a:${ALI}:`));
  await runStep(2, w);
  const pair = `${ALI}:${VALI}`;
  const debt = Object.values(backend.chain(ALI, VALI).state.debts).at(-1);
  assert.equal(debt.status, 'active');
  assert.match(bots[ALI].messages.at(-1).html, new RegExp(debt.seal));
  await runStep(3, w);
  assert.equal(backend.summary(ALI).owed_to_me.UZS, 100_000_000);
  const before = bots[ALI].messages.length;
  await runStep(4, w);
  const reminders = bots[ALI].messages.slice(before).map((m) => m.html).join('\n');
  assert.match(reminders, lang === 'uz' ? /3 kun qoldi/ : /осталось 3 дня/);
  assert.match(bots[VALI].messages.at(-1).html, /1 000 000/);
  const seq = await runStep(5, w);
  assert.match(bots[VALI].messages.at(-1).html, new RegExp(`#${seq}`));
  assert.equal(verifyChain(backend.entries(pair)).ok, false);
  assert.deepEqual(w.alerts, []);
}

test('guided story: create, confirm, partial payment, reminders, tamper check (uz)', () => story('2026-11-18'));
test('guided story across New Year (ru)', () => story('2026-12-29', 'ru'));
test('guided story on every day of a month', async () => {
  for (let i = 0; i < 31; i++) await story(new Date(noon('2027-01-20') + i * DAY).toISOString().slice(0, 10));
});

test('demo bot refuses forged and stale buttons', () => {
  const { bots, alerts, backend } = world(noon('2026-11-18'));
  const vali = bots[VALI];
  vali.press(1, 'a:1003:1:1');
  vali.press(1, 'b:1001:1:payfull');
  vali.press(1, 'zzz');
  vali.press(1, 'n:admin');
  assert.equal(alerts.length, 4);
  assert.equal(backend.entries('1001:1002').length, 6);
});
