import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const EXE = '/Users/knight/Library/Caches/ms-playwright/chromium-1223/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const BASE = 'http://127.0.0.1:5005';
const creds = JSON.parse(readFileSync(path.join(root, 'config/quark_config.json'), 'utf8')).webui;

const errors = [];
const browser = await chromium.launch({ executablePath: EXE, headless: true });
const page = await browser.newPage();
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push(`[${m.type()}] ${m.text()}`); });
page.on('pageerror', e => errors.push(`[pageerror] ${e.stack || e.message}`));

await page.goto(`${BASE}/login`, { waitUntil: 'networkidle' });
await page.fill('#username', creds.username);
await page.fill('#password', creds.password);
await Promise.all([
  page.waitForNavigation({ waitUntil: 'networkidle' }).catch(() => {}),
  page.click('button[type="submit"], input[type="submit"]')
]);
await page.waitForTimeout(2500);

// 1) 列表模式：检查第一张任务卡的内容
const listInfo = await page.evaluate(() => {
  const app = window.__QAS_APP__;
  app.activeTab = 'tasklist';
  return new Promise(resolve => setTimeout(() => {
    const card = document.querySelector('.task-card');
    resolve({
      viewMode: app.tasklist.viewMode,
      cardExists: !!card,
      cardHTML: card ? card.outerHTML.slice(0, 1200) : null,
      taskCount: app.formData.tasklist.length,
      sortedCount: app.sortedTasklist ? app.sortedTasklist.length : -1
    });
  }, 400));
});
console.log('=== 列表模式 ===');
console.log('viewMode:', listInfo.viewMode, '| 任务数:', listInfo.taskCount, '| sorted:', listInfo.sortedCount);
console.log('卡片 HTML 片段:', listInfo.cardHTML);
console.log('当前错误数:', errors.length);

// 2) 切换到海报模式
console.log('=== 切换到海报模式 ===');
await page.evaluate(() => { window.__QAS_APP__.tasklist.viewMode = 'poster'; });
await page.waitForTimeout(800);
const posterInfo = await page.evaluate(() => ({
  appChildren: document.querySelector('#app').children.length,
  innerHTMLLen: document.querySelector('#app').innerHTML.length,
  posterCount: document.querySelectorAll('.tasklist-poster-mode .discovery-poster').length,
  bodyText: document.body.innerText.slice(0, 80)
}));
console.log('#app 子节点:', posterInfo.appChildren, '| innerHTML:', posterInfo.innerHTMLLen, '| 海报数:', posterInfo.posterCount);
console.log('body 文本:', JSON.stringify(posterInfo.bodyText));
console.log('错误数:', errors.length);
for (const e of errors.slice(0, 15)) console.log('  ', e.slice(0, 350));

await page.screenshot({ path: '/tmp/qas-poster.png' });
console.log('截图: /tmp/qas-poster.png');
await browser.close();
process.exit(0);
