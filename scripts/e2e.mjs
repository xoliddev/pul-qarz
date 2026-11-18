// Browser test of the demo at 1440 px and 375 px. Fails on any console error or page error.
//   PW_CHANNEL=chrome node scripts/e2e.mjs        (needs `playwright` installed: npm i -D playwright)
import assert from 'node:assert/strict';
import { chromium } from 'playwright';
import { startServer } from './serve.mjs';

const PORT = Number(process.env.E2E_PORT ?? 4195);
const BASE = process.env.E2E_URL ?? `http://127.0.0.1:${PORT}/`;
const server = process.env.E2E_URL ? null : await startServer(PORT);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });
const errors = [];
let checks = 0;
const ok = (cond, msg) => {
  assert.ok(cond, msg);
  checks += 1;
};

async function open(width, height, lang = 'uz') {
  const ctx = await browser.newContext({ viewport: { width, height }, locale: 'uz-UZ', timezoneId: 'Asia/Tashkent' });
  await ctx.addInitScript((l) => { try { localStorage.setItem('pulqarz.demo.lang', l); } catch { /* */ } }, lang);
  const page = await ctx.newPage();
  page.on('console', (m) => m.type() === 'error' && errors.push(`[${width}] ${m.text()}`));
  page.on('pageerror', (e) => errors.push(`[${width}] ${e.message}`));
  page.on('requestfailed', (r) => errors.push(`[${width}] request failed ${r.url()}`));
  await page.goto(BASE);
  await page.waitForSelector('body[data-ready="1"]', { timeout: 20_000 });
  return page;
}

const text = (page, sel) => page.locator(sel).innerText();
async function step(page, n) {
  await page.getByTestId(`story-${n}`).click();
  await page.waitForFunction((k) => document.querySelector(`[data-testid=story-${k}]`).classList.contains('done'), n, { timeout: 30_000 });
}

async function story(page, mobile) {
  ok((await text(page, '[data-testid=demo-badge]')).includes('brauzeringizda'), 'demo badge');
  if (mobile) {
    ok(await page.getByTestId('ali-phone').isVisible(), 'Ali visible on phone');
    ok(!(await page.getByTestId('vali-phone').isVisible()), 'only one phone at a time');
    const sw = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1);
    ok(sw, 'no horizontal scroll at 375 px');
  } else {
    ok(await page.getByTestId('vali-phone').isVisible(), 'both phones at 1440 px');
  }
  await step(page, 1);
  ok((await text(page, '[data-testid=vali-chat]')).includes('1 500 000'), 'Vali sees the request');
  await step(page, 2);
  ok(/Tasdiqlandi\. Muhr: [0-9A-F]{4}-[0-9A-F]{4}/.test(await text(page, '[data-testid=vali-chat]')), 'Vali sees the seal');
  if (mobile) await page.getByTestId('switch-ali').click();
  await page.getByTestId('ali-tab-app').click();
  await page.locator('[data-testid=ali-app] [data-testid=person]').first().click();
  await page.locator('[data-testid=ali-app] [data-testid=seal]').first().waitFor();
  ok((await text(page, '[data-testid=ali-app]')).includes('1 500 000'), 'Ali Mini App shows the sealed debt');
  await step(page, 3);
  ok((await text(page, '[data-testid=vali-chat]')).includes("tasdiqladi: to'lov 500 000"), 'Ali confirmed the payment');
  await step(page, 4);
  if (mobile) await page.getByTestId('switch-ali').click();
  await page.getByTestId('ali-tab-chat').click();
  ok((await text(page, '[data-testid=ali-chat]')).includes('3 kun qoldi'), 'reminder fired after skipping days');
  await step(page, 5);
  if (mobile) await page.getByTestId('switch-vali').click();
  ok((await text(page, '[data-testid=vali-chat]')).includes('uzilgan'), 'tamper check points to the broken link');
  await page.getByTestId('vali-tab-app').click();
  await page.locator('[data-testid=vali-app] [data-testid=person]').first().click();
  await page.locator('[data-testid=vali-app] .pq-verify.bad').waitFor();
  ok(true, 'Mini App re-verifies the chain on the phone and shows red');
}

async function miniAppFlow(page) {
  // Ali creates a debt in the Mini App; Vali confirms it in his Mini App.
  await page.getByTestId('ali-tab-app').click();
  const ali = page.getByTestId('ali-app');
  await ali.getByTestId('new-lent').click();
  await ali.getByTestId('who-1002').click();
  await ali.getByTestId('amount').fill('250 000');
  await ali.getByTestId('note').fill('Kitoblar');
  await ali.getByTestId('submit').click();
  await page.waitForFunction(() => document.querySelector('[data-testid=vali-phone]').classList.contains('ring'));
  ok(true, "Vali's phone lights up");
  await page.getByTestId('vali-tab-app').click();
  const vali = page.getByTestId('vali-app');
  await vali.getByTestId('pending').first().getByTestId('confirm').click();
  await vali.getByTestId('person').first().click();
  await vali.getByTestId('seal').first().waitFor();
  ok((await vali.innerText()).includes('250 000'), 'confirmed in the Mini App and sealed');
  // a payment from the Mini App, confirmed by Ali in the bot
  await vali.getByTestId('pay').first().click();
  await vali.getByTestId('pay-amount').fill('50 000');
  await vali.getByTestId('pay-send').click();
  await page.getByTestId('ali-tab-chat').click();
  await page.locator('[data-testid=ali-chat] .kb-btn', { hasText: 'Tasdiqlayman' }).last().click();
  await page.waitForFunction(() => document.querySelector('[data-testid=ali-chat]').innerText.includes('Tasdiqlandi'));
  ok(true, 'payment from the Mini App confirmed in the bot');
  // switch to Russian
  await page.getByTestId('demo-lang').click();
  ok((await text(page, '[data-testid=demo-badge]')).includes('браузере'), 'Russian switch');
  await page.getByTestId('ali-tab-app').click();
  await page.waitForFunction(() => document.querySelector('[data-testid=ali-app]').innerText.includes('Мне вернут'));
  ok(true, 'Mini App in Russian');
}

async function manualBot(page) {
  // typing a wrong amount in the bot gives a friendly error, not a crash
  await page.locator('[data-testid=ali-chat] .kb-btn', { hasText: 'Qarz oldim' }).last().click();
  await page.locator('[data-testid=ali-chat] .kb-btn', { hasText: 'Sardor' }).last().click();
  await page.getByTestId('ali-input').fill('ko\'p pul');
  await page.getByTestId('ali-input').press('Enter');
  ok((await text(page, '[data-testid=ali-chat]')).includes('tushunmadim'), 'bad amount is explained');
  await page.locator('[data-testid=ali-chat] .kb-btn', { hasText: 'Bekor qilish' }).last().click();
  ok((await text(page, '[data-testid=ali-chat]')).includes('Bosh menyu'), 'cancel returns to the menu');
}

try {
  for (const [w, h] of [[1440, 900], [375, 812]]) {
    const page = await open(w, h);
    await story(page, w < 600);
    await page.context().close();
  }
  const page = await open(1440, 900);
  await manualBot(page);
  await miniAppFlow(page);
  await page.context().close();
  const phone = await open(375, 812, 'ru');
  ok((await text(phone, '[data-testid=demo-badge]')).includes('браузере'), 'opens in Russian on a phone');
  await phone.context().close();
  assert.deepEqual(errors, [], `console errors:\n${errors.join('\n')}`);
  console.log(`e2e: ${checks} checks passed at 1440 px and 375 px, 0 console errors`); // eslint-disable-line no-console
} finally {
  await browser.close();
  server?.close();
}
