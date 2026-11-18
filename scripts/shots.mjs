// README media from the real demo: desktop + phone screenshots (JPEG), a GIF of the confirm flow,
// and an 800x500 thumbnail. JPEG is encoded by the browser (canvas), the GIF by gifenc.
//   PW_CHANNEL=chrome node scripts/shots.mjs [outDir]       (needs playwright + gifenc)
import { mkdirSync, writeFileSync } from 'node:fs';
import gifenc from 'gifenc';
import { chromium } from 'playwright';
import { startServer } from './serve.mjs';

const { GIFEncoder, quantize, applyPalette } = gifenc;
const OUT = process.argv[2] ?? 'docs/media';
mkdirSync(OUT, { recursive: true });
const server = await startServer(4196);
const browser = await chromium.launch({ channel: process.env.PW_CHANNEL || undefined });

async function open(width, height) {
  const ctx = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, timezoneId: 'Asia/Tashkent' });
  const page = await ctx.newPage();
  await page.goto('http://127.0.0.1:4196/');
  await page.waitForSelector('body[data-ready="1"]');
  return page;
}

/** PNG -> resized JPEG through the page's canvas. */
async function jpeg(page, png, name, w, h, crop = null) {
  const b64 = await page.evaluate(async ([src, W, H, c]) => {
    const img = new Image();
    img.src = `data:image/png;base64,${src}`;
    await img.decode();
    const cv = document.createElement('canvas');
    cv.width = W;
    cv.height = H;
    const g = cv.getContext('2d');
    g.imageSmoothingQuality = 'high';
    const [sx, sy, sw, sh] = c ?? [0, 0, img.width, img.height];
    g.drawImage(img, sx, sy, sw, sh, 0, 0, W, H);
    return cv.toDataURL('image/jpeg', 0.86).split(',')[1];
  }, [png.toString('base64'), w, h, crop]);
  writeFileSync(`${OUT}/${name}`, Buffer.from(b64, 'base64'));
  console.log('wrote', name); // eslint-disable-line no-console
}

const step = async (page, n) => {
  await page.getByTestId(`story-${n}`).click();
  await page.waitForFunction((k) => document.querySelector(`[data-testid=story-${k}]`).classList.contains('done'), n);
};

// desktop: after the debt is confirmed and partly paid, Ali looks at the sealed debt in the Mini App
let page = await open(1440, 900);
await step(page, 1);
await step(page, 2);
await step(page, 3);
await page.getByTestId('ali-tab-app').click();
await page.locator('[data-testid=ali-app] [data-testid=person]').first().click();
await page.locator('[data-testid=ali-app] [data-testid=verify-btn]').click();
await page.waitForTimeout(900);
const desk = await page.screenshot();
await jpeg(page, desk, 'demo-desktop.jpg', 1440, 900);
await jpeg(page, desk, 'thumb.jpg', 800, 500, [160, 120, 1120, 700]);
await page.context().close();

// phone: Vali's Mini App home with a request waiting for him
page = await open(390, 844);
await step(page, 1);
await page.getByTestId('switch-vali').click();
await page.getByTestId('vali-tab-chat').click();
await page.waitForTimeout(600);
await jpeg(page, await page.screenshot(), 'demo-mobile.jpg', 390, 844);
await page.context().close();

// GIF: create -> Vali's phone lights up -> confirm -> seal
page = await open(1280, 800);
const W = 840;
const H = 525;
const gif = GIFEncoder();
async function frame(delay = 160) {
  const png = await page.screenshot({ clip: { x: 160, y: 150, width: 960, height: 600 } });
  const rgba = await page.evaluate(async ([src, w, h]) => {
    const img = new Image();
    img.src = `data:image/png;base64,${src}`;
    await img.decode();
    const c = document.createElement('canvas');
    c.width = w;
    c.height = h;
    const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high';
    g.drawImage(img, 0, 0, w, h);
    return Array.from(g.getImageData(0, 0, w, h).data);
  }, [png.toString('base64'), W, H]);
  const data = Uint8Array.from(rgba);
  const palette = quantize(data, 128);
  gif.writeFrame(applyPalette(data, palette), W, H, { palette, delay });
}
await frame(1000);
for (const n of [1, 2, 3]) {
  await page.getByTestId(`story-${n}`).click();
  for (let k = 0; k < 14; k++) {
    await page.waitForTimeout(450);
    await frame(260);
    const finished = await page.evaluate((s) => document.querySelector(`[data-testid=story-${s}]`).classList.contains('done'), n);
    if (finished && k > 3) break;
  }
  await frame(1200);
}
await page.getByTestId('ali-tab-app').click();
await page.locator('[data-testid=ali-app] [data-testid=person]').first().click();
await page.waitForTimeout(700);
await frame(2600);
gif.finish();
writeFileSync(`${OUT}/confirm-flow.gif`, gif.bytes());
console.log('wrote confirm-flow.gif'); // eslint-disable-line no-console
await browser.close();
server.close();
