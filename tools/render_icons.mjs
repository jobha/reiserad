// Lag favicon-PNG-ene fra brand/*.svg med headless Chrome.
//   16/32 px: brand/favicon-small.svg (forenklet klode, leselig i fanen)
//   48 px og større: brand/logo.svg
// Kjør fra en mappe der puppeteer-core finnes (f.eks. ~/legeonline/app):
//   node /Users/jonasbull/reiseråd/tools/render_icons.mjs /Users/jonasbull/reiseråd
// og bygg deretter favicon.ico av icon-16/32/48 (se README).
import puppeteer from 'puppeteer-core';
import fs from 'fs';
const root = process.argv[2];
const b64 = (f) => Buffer.from(fs.readFileSync(`${root}/brand/${f}`, 'utf8')).toString('base64');
const small = b64('favicon-small.svg'), big = b64('logo.svg');
const browser = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new' });
const p = await browser.newPage();
async function render(file, size, src, bg) {
  await p.setViewport({ width: size, height: size, deviceScaleFactor: 1 });
  const pad = bg ? Math.round(size * 0.12) : 0;
  await p.setContent(`<body style="margin:0;background:${bg || 'transparent'}"><img src="data:image/svg+xml;base64,${src}" style="display:block;width:${size - 2 * pad}px;height:${size - 2 * pad}px;margin:${pad}px"></body>`);
  await p.screenshot({ path: `${root}/${file}`, omitBackground: !bg });
}
fs.mkdirSync(`${root}/.cache/icons`, { recursive: true });
for (const s of [16, 32]) await render(`.cache/icons/icon-${s}.png`, s, small);
await render('.cache/icons/icon-48.png', 48, big);
await render('site/favicon-192.png', 192, big);
await render('site/favicon-512.png', 512, big);
await render('site/apple-touch-icon.png', 180, big, '#f4f1ec');
await browser.close();
