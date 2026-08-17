// 用本机已缓存的 Chromium 内核真实加载页面，抓取控制台报错与渲染状态。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const EXE = '/Users/knight/Library/Caches/ms-playwright/chromium-1223/chrome-mac-x64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing';
const BASE = 'http://127.0.0.1:5005';

const creds = JSON.parse(readFileSync(path.join(root, 'config/quark_config.json'), 'utf8')).webui;
const consoleMsgs = [];
const pageErrors = [];
const failedRequests = [];

const browser = await chromium.launch({ executablePath: EXE, headless: true });
const page = await browser.newPage();

page.on('console', m => {
  consoleMsgs.push(`[${m.type()}] ${m.text()}`);
});
page.on('pageerror', e => pageErrors.push(String(e.stack || e.message || e)));
page.on('requestfailed', r => failedRequests.push(`${r.method()} ${r.url()} -> ${r.failure()?.errorText}`));
page.on('response', r => {
  if (r.status() >= 400) failedRequests.push(`${r.status()} ${r.url()}`);
});

console.log('=== 打开登录页 ===');
await page.goto(`${BASE}/login`, { waitUntil: 'networkidle', timeout: 30000 });
console.log('登录页 URL:', page.url());
console.log('登录页表单存在:', await page.$('#username') !== null);

await page.fill('#username', creds.username);
await page.fill('#password', creds.password);
await Promise.all([
  page.waitForNavigation({ waitUntil: 'networkidle', timeout: 30000 }).catch(() => {}),
  page.click('button[type="submit"], input[type="submit"]')
]);
await page.waitForTimeout(3000);

console.log('=== 登录后 ===');
console.log('URL:', page.url());
const appChildren = await page.evaluate(() => {
  const el = document.querySelector('#app');
  return { count: el ? el.children.length : -1, htmlLen: el ? el.innerHTML.length : -1 };
});
console.log('#app 子节点数:', appChildren.count, 'innerHTML 长度:', appChildren.htmlLen);

// 通过暴露的实例遍历全部标签页，触发各页面渲染路径
const tabResult = await page.evaluate(async () => {
  const app = window.__QAS_APP__;
  const out = [];
  for (const tab of ['overview', 'tasklist', 'discovery', 'calendar', 'history', 'filemanager', 'config', 'runlogs']) {
    try {
      app.activeTab = tab;
      await new Promise(r => setTimeout(r, 250));
      out.push(tab + ': ok');
    } catch (e) {
      out.push(tab + ': FAIL ' + (e.message || e));
    }
  }
  return out;
});
for (const t of tabResult) console.log('  标签页', t);
const bodyText = await page.evaluate(() => document.body.innerText.slice(0, 200));
console.log('body 文本片段:', JSON.stringify(bodyText));
console.log('pageerrors:', pageErrors.length);
for (const e of pageErrors.slice(0, 8)) console.log('  PAGE ERROR:', e.slice(0, 400));
console.log('failed requests:', failedRequests.length);
for (const f of failedRequests.slice(0, 12)) console.log('  FAIL:', f);
const consoleErrors = consoleMsgs.filter(m => m.startsWith('[error]'));
console.log('console errors:', consoleErrors.length);
for (const c of consoleErrors.slice(0, 8)) console.log('  CONSOLE:', c.slice(0, 300));
const consoleWarns = consoleMsgs.filter(m => m.startsWith('[warning]'));
for (const w of consoleWarns.slice(0, 8)) console.log('  WARN:', w.slice(0, 250));

// 移动端侧边栏抽屉回归检查
console.log('=== 移动端侧边栏抽屉 ===');
await page.setViewportSize({ width: 390, height: 844 });
await page.reload({ waitUntil: 'networkidle', timeout: 30000 });
await page.waitForSelector('.mobile-sidebar-toggle', { timeout: 10000 }).catch(() => {});
const toggleInfo = await page.evaluate(() => {
  const btn = document.querySelector('.mobile-sidebar-toggle');
  if (!btn) return 'button-missing';
  const r = btn.getBoundingClientRect();
  const cs = getComputedStyle(btn);
  return { display: cs.display, visible: r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' };
});
console.log('汉堡按钮:', JSON.stringify(toggleInfo));
if (!toggleInfo || toggleInfo === 'button-missing' || !toggleInfo.visible) {
  console.error('FAIL: 移动端汉堡按钮不存在或不可见');
  process.exit(1);
}
const drawerOpened = await (async () => {
  // 真实点击（命中测试）：若按钮被 toast 等元素遮挡，这里会直接失败
  await page.click('.mobile-sidebar-toggle', { timeout: 10000 });
  await page.waitForTimeout(400); // 等待 0.25s 滑入动画
  return page.evaluate(() => {
    const btn = document.querySelector('.mobile-sidebar-toggle');
    const sidebar = document.getElementById('sidebarMenu');
    const navText = document.querySelector('.glass-sidebar .nav-text');
    return {
      show: sidebar.classList.contains('show'),
      ariaExpanded: btn.getAttribute('aria-expanded'),
      labelDisplay: navText ? getComputedStyle(navText).display : 'no-label'
    };
  });
})();
console.log('抽屉展开:', JSON.stringify(drawerOpened));
if (!drawerOpened.show || drawerOpened.ariaExpanded !== 'true' || drawerOpened.labelDisplay === 'none') {
  console.error('FAIL: 移动端抽屉未展开或文字标签不可见');
  process.exit(1);
}
const drawerClosed = await (async () => {
  // 点击抽屉中靠下的导航项（避开可能的 toast 通知区域），验证 changeTab 自动收起
  try {
    await page.click('#sidebarMenu .nav-link:has-text("运行日志")', { timeout: 10000 });
  } catch {
    await page.evaluate(() => {
      const links = document.querySelectorAll('#sidebarMenu .nav-link');
      (Array.from(links).find(a => a.textContent.includes('运行日志')) || links[links.length - 1]).click();
    });
  }
  await page.waitForTimeout(400);
  return page.evaluate(() => ({ show: document.getElementById('sidebarMenu').classList.contains('show') }));
})();
console.log('抽屉收起:', JSON.stringify(drawerClosed));
if (drawerClosed.show) {
  console.error('FAIL: 点击导航项后抽屉未自动收起');
  process.exit(1);
}
// 还原桌面视口，避免影响后续截图
await page.setViewportSize({ width: 1280, height: 800 });

await page.screenshot({ path: '/tmp/qas-browser-main.png', fullPage: false });
console.log('截图已保存: /tmp/qas-browser-main.png');
await browser.close();
process.exit(0);
