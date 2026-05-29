// Render dashboard/og_card.html to a 1200x630 PNG (the og:image).
// Usage: node dashboard/render_og.mjs
import pw from '/usr/lib/node_modules/playwright/index.js';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(here, 'og_card.html'), 'utf8');
const out = join(here, 'public', 'og.png');

const browser = await pw.chromium.launch({ headless: true, args: ['--no-sandbox'] });
const page = await browser.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: 1 });
await page.setContent(html, { waitUntil: 'networkidle' });
await page.screenshot({ path: out, clip: { x: 0, y: 0, width: 1200, height: 630 } });
await browser.close();
console.log('og.png rendered ->', out);
