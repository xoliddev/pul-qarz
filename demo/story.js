// The guided scenario. Each step presses the same buttons a person would, through the simulated bot.
// Used by the demo page (with pauses, so you can watch) and by js-tests/demo.test.mjs (without pauses).
import { ALI, VALI } from './seed.js';

/** Press the newest button whose callback data matches `re`. */
export function tap(bot, re) {
  for (let i = bot.messages.length - 1; i >= 0; i--) {
    const msg = bot.messages[i];
    for (const row of msg.kb) {
      for (const b of row) {
        if (b.data && re.test(b.data)) {
          bot.press(msg.id, b.data);
          return b.data;
        }
      }
    }
  }
  throw new Error(`no button ${re} in ${bot.uid}'s chat`);
}

function hasButton(bot, re) {
  const last = bot.messages.at(-1);
  return Boolean(last?.kb.some((row) => row.some((b) => b.data && re.test(b.data))));
}

function ensureMenu(bot) {
  if (!hasButton(bot, /^n:lent$/)) bot.start();
}

export const STEPS = ['step1', 'step2', 'step3', 'step4', 'step5'];

export async function runStep(n, { backend, bots, wait = async () => {}, focus = () => {} }) {
  const ali = bots[ALI];
  const vali = bots[VALI];
  const pause = (ms = 650) => wait(ms);
  if (n === 1) {
    focus(ALI, 'chat');
    ensureMenu(ali);
    await pause(400);
    tap(ali, /^n:lent$/);
    await pause();
    tap(ali, new RegExp(`^w:${VALI}$`));
    await pause();
    ali.type('1 500 000');
    await pause();
    tap(ali, /^c:UZS$/);
    await pause();
    tap(ali, /^d:7$/);
    await pause();
    ali.type(ali.lang === 'ru' ? 'На телефон' : 'Telefon uchun');
    await pause(900);
    tap(ali, /^s:send$/);
    focus(VALI, 'chat');
  } else if (n === 2) {
    focus(VALI, 'chat');
    await pause(400);
    tap(vali, new RegExp(`^a:${ALI}:\\d+:1$`));
    await pause(500);
    focus(ALI, 'app');
  } else if (n === 3) {
    focus(VALI, 'chat');
    ensureMenu(vali);
    await pause(400);
    tap(vali, /^n:people$/);
    await pause();
    tap(vali, new RegExp(`^p:${ALI}:open$`));
    await pause();
    tap(vali, new RegExp(`^b:${ALI}:\\d+:open$`));
    await pause();
    tap(vali, /:pay$/);
    await pause();
    vali.type('500 000');
    await pause(900);
    focus(ALI, 'chat');
    tap(ali, new RegExp(`^a:${VALI}:\\d+:1$`));
    await pause(500);
  } else if (n === 4) {
    focus(ALI, 'chat');
    focus(VALI, 'chat');
    for (let i = 0; i < 4; i++) {
      backend.skipDays(1);
      await pause(500);
    }
  } else if (n === 5) {
    const pair = `${ALI}:${VALI}`;
    const entries = backend.entries(pair);
    const debt = [...entries].reverse().find((e) => e.kind === 'debt');
    backend.tamper(pair, debt.seq, 'amount', Math.round(debt.amount / 3));
    focus(VALI, 'chat');
    ensureMenu(vali);
    await pause(400);
    tap(vali, /^n:people$/);
    await pause();
    tap(vali, new RegExp(`^p:${ALI}:open$`));
    await pause();
    tap(vali, new RegExp(`^p:${ALI}:verify$`));
    return debt.seq;
  }
  return null;
}
