// Renders scripts/social-preview.html to .github/social-preview.png at exactly 1280x640.
import { chromium } from '../web/node_modules/playwright/index.mjs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const page_url = 'file://' + resolve(here, 'social-preview.html');
const out = process.argv[2] ?? resolve(here, '..', '.github', 'social-preview.jpg');

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1280, height: 640 },
  deviceScaleFactor: 2,
});
await page.goto(page_url, { waitUntil: 'networkidle' });
await page.evaluate(() => document.fonts.ready);
const card = page.locator('#card');
const box = await card.boundingBox();
if (!box || Math.round(box.width) !== 1280 || Math.round(box.height) !== 640) {
  throw new Error(`#card is ${box?.width}x${box?.height}, expected 1280x640`);
}
// GitHub caps the social preview at 1 MB; the photographic backdrop needs JPEG to fit.
const jpeg = /\.jpe?g$/i.test(out);
await card.screenshot(jpeg ? { path: out, type: 'jpeg', quality: 92 } : { path: out });
await browser.close();
console.log('wrote', out);
