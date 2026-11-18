// Demo data, always relative to "today", so the demo works on any date (also across New Year and month ends).
// Every entry goes through the real ledger rules; nothing is hard-coded as a finished state.
import { DemoBackend } from './backend.js';

export const ALI = 1001;
export const VALI = 1002;
export const SARDOR = 1003;
export const DILNOZA = 1004;

const DAY = 86_400_000;

/** `today` is a Tashkent date (YYYY-MM-DD). Returns a timestamp `days` from it at `hour` Tashkent time. */
function at(today, days, hour = 10, minute = 0) {
  const ms = Date.parse(`${today}T00:00:00Z`) + days * DAY + (hour - 5) * 3_600_000 + minute * 60_000;
  return `${new Date(ms).toISOString().slice(0, 19)}Z`;
}

const date = (today, days) => new Date(Date.parse(`${today}T00:00:00Z`) + days * DAY).toISOString().slice(0, 10);

export function seed(backend, lang = 'uz') {
  const today = backend.today();
  const b = backend;
  b.addUser(ALI, 'Ali', lang);
  b.addUser(VALI, 'Vali', lang);
  b.addUser(SARDOR, 'Sardor', lang);
  b.addUser(DILNOZA, 'Dilnoza', lang);

  // Ali and Vali: an old debt, paid back in two parts and closed (shows a full sealed history).
  b.appendAs(ALI, VALI, { kind: 'debt', by: ALI, lender: ALI, borrower: VALI, amount: 80_000_000, cur: 'UZS',
    due: date(today, -15), note: "Ta'mirlash uchun" }, at(today, -45, 11));
  b.appendAs(VALI, ALI, { kind: 'confirm', by: VALI, ref: 1 }, at(today, -45, 11, 6));
  b.appendAs(VALI, ALI, { kind: 'payment', by: VALI, ref: 1, amount: 30_000_000 }, at(today, -30, 18));
  b.appendAs(ALI, VALI, { kind: 'confirm', by: ALI, ref: 3 }, at(today, -30, 18, 20));
  b.appendAs(VALI, ALI, { kind: 'payment', by: VALI, ref: 1, amount: 50_000_000 }, at(today, -16, 9));
  b.appendAs(ALI, VALI, { kind: 'confirm', by: ALI, ref: 5 }, at(today, -16, 9, 40));

  // Sardor lent Ali $150, due in 5 days (Ali gets a reminder after skipping two days).
  b.appendAs(SARDOR, ALI, { kind: 'debt', by: SARDOR, lender: SARDOR, borrower: ALI, amount: 15_000, cur: 'USD',
    due: date(today, 5), note: 'Noutbuk' }, at(today, -20, 15));
  b.appendAs(ALI, SARDOR, { kind: 'confirm', by: ALI, ref: 1 }, at(today, -20, 15, 3));

  // Vali lent Dilnoza 2 000 000 so'm; she has paid 500 000.
  b.appendAs(VALI, DILNOZA, { kind: 'debt', by: VALI, lender: VALI, borrower: DILNOZA, amount: 200_000_000,
    cur: 'UZS', due: date(today, 20), note: "To'y xarajati" }, at(today, -10, 12));
  b.appendAs(DILNOZA, VALI, { kind: 'confirm', by: DILNOZA, ref: 1 }, at(today, -10, 12, 30));
  b.appendAs(DILNOZA, VALI, { kind: 'payment', by: DILNOZA, ref: 1, amount: 50_000_000 }, at(today, -3, 20));
  b.appendAs(VALI, DILNOZA, { kind: 'confirm', by: VALI, ref: 3 }, at(today, -3, 20, 5));

  for (const [x, y] of [[ALI, SARDOR], [VALI, DILNOZA]]) {
    const { pair, state } = b.chain(x, y);
    for (const d of Object.values(state.debts)) if (d.status === 'active') b.scheduleReminders(pair, d);
  }
  return b;
}

export function createDemo({ now, lang = 'uz' } = {}) {
  return seed(new DemoBackend(now ? { now } : {}), lang);
}
