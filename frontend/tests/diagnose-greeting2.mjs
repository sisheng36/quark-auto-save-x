import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const EXE = '/Users/knight/Library/Caches/ms-playwright/chromium-1223/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const creds = JSON.parse(readFileSync(path.join(root, 'config/quark_config.json'), 'utf8')).webui;
const browser = await chromium.launch({ executablePath: EXE, headless: true });
const page = await browser.newPage();
const failed = [];
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('CONSOLE', m.type(), m.text().slice(0, 300)); });
page.on('pageerror', e => console.log('PAGEERROR', (e.stack || e.message).slice(0, 400)));
page.on('requestfailed', r => failed.push(r.url() + ' -> ' + (r.failure()?.errorText)));
page.on('response', r => { if (r.status() >= 400) failed.push(r.status() + ' ' + r.url()); });
await page.goto('http://127.0.0.1:5005/login', { waitUntil: 'networkidle' });
await page.fill('#username', creds.username);
await page.fill('#password', creds.password);
await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}), page.click('button[type="submit"]')]);
await page.waitForTimeout(3000);
const info = await page.evaluate(async () => {
  const app = window.__QAS_APP__;
  // 手动调一次 /data 看响应
  let raw = null, err = null;
  try { const r = await window.axios.get('/data'); raw = JSON.stringify(r.data).slice(0, 300); } catch (e) { err = String(e && e.message || e); }
  return {
    configHasLoaded: app.configHasLoaded,
    webui: JSON.stringify(app.formData.webui),
    raw: raw,
    err: err,
    tasklistLen: (app.formData.tasklist || []).length
  };
});
console.log(JSON.stringify(info, null, 1));
console.log('失败请求:', failed.length);
for (const f of failed.slice(0, 8)) console.log('  ', f);
await browser.close();
process.exit(0);
