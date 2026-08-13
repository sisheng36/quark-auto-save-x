import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const EXE = '/Users/knight/Library/Caches/ms-playwright/chromium-1223/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const creds = JSON.parse(readFileSync(path.join(root, 'config/quark_config.json'), 'utf8')).webui;
const browser = await chromium.launch({ executablePath: EXE, headless: true });
const page = await browser.newPage();
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') console.log('CONSOLE', m.type(), m.text().slice(0, 250)); });
await page.goto('http://127.0.0.1:5005/login', { waitUntil: 'networkidle' });
await page.fill('#username', creds.username);
await page.fill('#password', creds.password);
await Promise.all([page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}), page.click('button[type="submit"]')]);
await page.waitForTimeout(3000);
const info = await page.evaluate(() => {
  const app = window.__QAS_APP__;
  const el = document.querySelector('.overview-greeting-text');
  return {
    webui: JSON.stringify(app.formData.webui),
    text: el ? el.textContent : '无元素',
    greeting: JSON.stringify(app.overviewGreeting)
  };
});
console.log(JSON.stringify(info, null, 1));
await browser.close();
process.exit(0);
