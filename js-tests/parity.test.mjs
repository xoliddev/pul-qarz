// The JS port (shared/*.js) must agree with the Python core on every shared test vector.
//   node --test js-tests/
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import * as calc from '../shared/calc.js';
import * as L from '../shared/ledger.js';
import { sha256Hex } from '../shared/sha256.js';

const V = JSON.parse(readFileSync(new URL('../shared/test_vectors.json', import.meta.url), 'utf8'));
const clone = (x) => structuredClone(x);

test('sha256 matches node:crypto, including multi-block and non-ASCII input', () => {
  for (const s of ['', 'abc', 'a'.repeat(55), 'a'.repeat(56), 'a'.repeat(64), "so'm ўзбек 💸".repeat(40)]) {
    assert.equal(sha256Hex(s), createHash('sha256').update(s, 'utf8').digest('hex'));
  }
});

test('canonical JSON and hashes', () => {
  for (const c of V.canonical) {
    assert.equal(L.canonical(c.input), c.canonical);
    assert.equal(sha256Hex(c.canonical), c.sha256);
    assert.equal(L.entryHash(L.GENESIS, c.input), c.entry_hash);
  }
  assert.throws(() => L.canonical({ a: 1.5 }));
  assert.throws(() => L.canonical({ a: true }));
  assert.throws(() => L.canonical({ a: null }));
});

test('chain replays to the same entries, seals and debt views', () => {
  const st = L.newState();
  V.chain.steps.forEach((step, i) => assert.deepEqual(L.append(st, V.chain.pair, step), V.chain.entries[i]));
  assert.deepEqual(L.verifyChain(V.chain.entries), V.chain.verify);
  const views = {};
  for (const [s, d] of Object.entries(st.debts)) views[s] = calc.debtView(d, 1001);
  assert.deepEqual(views, V.chain.debts);
});

test('invalid operations are refused with the same error code', () => {
  for (const c of V.invalid) {
    const st = L.fold(V.chain.entries.slice(0, c.prefix));
    const before = clone(st);
    assert.throws(() => L.append(st, V.chain.pair, c.body), (e) => e.code === c.error);
    assert.deepEqual(st, before);
  }
});

test('tampering is detected at the same link', () => {
  for (const c of V.tamper) {
    const bad = clone(V.chain.entries);
    bad[c.seq - 1][c.field] = c.value;
    assert.deepEqual(L.verifyChain(bad), c.result);
  }
});

test('balances and summary', () => {
  const b = V.balances;
  const vali = L.fold(V.chain.entries);
  const sardor = L.fold(b.sardor_entries);
  assert.deepEqual(calc.pairBalance(vali, 1001), b.ali_vali);
  assert.deepEqual(calc.pairBalance(vali, 1002), b.vali_ali);
  assert.deepEqual(calc.summary({ 1002: vali, 1003: sardor }, 1001), b.ali_summary);
});

test('reminder plans and send times', () => {
  for (const c of V.reminders) assert.deepEqual(calc.reminderPlan(c.due, c.today), c.plan);
  for (const c of V.fire_at) assert.equal(calc.fireAt(c.day), c.utc);
});

test('money parsing and formatting', () => {
  for (const c of V.money_parse) {
    if (c.error) assert.throws(() => calc.parseAmount(c.text), c.text);
    else assert.equal(calc.parseAmount(c.text), c.minor, c.text);
  }
  for (const c of V.money_format) assert.equal(calc.formatNumber(c.minor), c.text);
});

test('both locales have the same keys and placeholders', () => {
  const uz = JSON.parse(readFileSync(new URL('../shared/locales/uz.json', import.meta.url), 'utf8'));
  const ru = JSON.parse(readFileSync(new URL('../shared/locales/ru.json', import.meta.url), 'utf8'));
  assert.deepEqual(Object.keys(uz).sort(), Object.keys(ru).sort());
  const ph = (s) => (s.match(/\{\w+\}/g) ?? []).sort().join();
  for (const k of Object.keys(uz)) assert.equal(ph(uz[k]), ph(ru[k]), k);
});
