// 总览页首屏初始化回归测试：
// 修复前：mounted() 未调用 updateOverviewGreeting()/loadOverviewTransferStats()，
// 首次进入总览页（默认或 localStorage 恢复的 activeTab）时问候语为空（只显示"，用户名"）、
// 今日转存动态全为 0，切走再切回才正常。
// 本测试断言：挂载后问候语立即生成、/overview_transfer_stats 被请求、DOM 无孤立逗号；
// 且切换标签回总览时统计仍会重新加载（保持原有行为）。
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

let html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
html = html.replace('[[ frontend_scripts | safe ]]', '');
html = html.replace('version: "[[ version ]]"', 'version: "dev"');
html = html.replace('plugin_flags: "[[ plugin_flags ]]"', 'plugin_flags: ""');

// 构建产物路径：优先环境变量，否则读取 dist 目录下唯一的 main-*.js
let bundlePath = process.env.QAS_SMOKE_BUNDLE;
if (!bundlePath) {
  const assetsDir = path.join(root, 'app/static/dist/assets');
  const candidates = readdirSync(assetsDir).filter(f => /^main-.*\.js$/.test(f));
  if (candidates.length !== 1) {
    console.error('无法确定构建产物：请设置 QAS_SMOKE_BUNDLE 或先执行 npm run build');
    process.exit(2);
  }
  bundlePath = path.join(assetsDir, candidates[0]);
}
const bundle = readFileSync(bundlePath, 'utf8');

const errors = [];
const warnings = [];

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5005/',
  runScripts: 'outside-only',
  pretendToBeVisual: true
});
const { window } = dom;
window.console.error = (...args) => errors.push(args.map(String).join(' '));
window.console.warn = (...args) => warnings.push(args.map(String).join(' '));
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const jqObj = () => ({
  on() { return this; }, tooltip() { return this; }, collapse() { return this; },
  hasClass() { return false; }, addClass() { return this; }, removeClass() { return this; },
  length: 0
});
window.$ = window.jQuery = () => jqObj();
window.EventSource = class {
  constructor() {}
  addEventListener() {}
  close() {}
};
window.pinyinPro = { pinyin: (s) => String(s || '') };
window.sortFileByName = (f) => [String((f && f.file_name) || f || '')];

// axios 桩：记录 /overview_transfer_stats 的请求次数，返回固定统计与登录用户
const statsCalls = [];
const byUrl = {
  '/data': {
    success: true,
    data: {
      webui: { username: '测试用户' },
      tasklist: [],
      execution_mode: 'manual'
    }
  },
  '/overview_transfer_stats': {
    success: true,
    data: { today_count: 3, today_size: 1024, total_count: 10, total_size: 2048 }
  }
};
window.axios = {
  async get(url) {
    if (String(url).includes('/overview_transfer_stats')) statsCalls.push(url);
    const hit = Object.keys(byUrl).find(k => String(url).includes(k));
    return { data: hit ? byUrl[hit] : { success: false, message: 'stub' } };
  },
  async post() { return { data: { success: false, message: 'stub' } }; },
  async put() { return { data: { success: false, message: 'stub' } }; },
  async delete() { return { data: { success: false, message: 'stub' } }; }
};

// 挂载应用
try {
  window.eval('"use strict";\n' + bundle);
} catch (e) {
  console.error('bundle 执行失败:', e);
  process.exit(1);
}
await new Promise(r => setTimeout(r, 150));

const app = window.__QAS_APP__;
if (!app) {
  console.error('FAIL: __QAS_APP__ 未挂载');
  process.exit(1);
}

let failed = false;
const check = (cond, label) => {
  console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  if (!cond) failed = true;
};

// 1) 首屏（activeTab 默认为 overview）问候语立即生成
const g = app.overviewGreeting;
check(!!g.text, `首屏问候语非空（当前: "${g.text}"）`);
check(!!g.emoji && !!g.dateText, '问候语 emoji 与日期非空');
check(!!g.period, '问候语时段 key 已设置');

// 2) 首屏即请求转存统计，且数据生效
check(statsCalls.length >= 1, `首屏已请求 /overview_transfer_stats（次数: ${statsCalls.length}）`);
check(app.overviewTransferStats.today_count === 3, '今日转存统计已生效（today_count=3）');

// 3) DOM 渲染：问候语文本不以孤立逗号开头，且包含用户名
const el = window.document.querySelector('.overview-greeting-text');
check(!!el, 'DOM 存在 .overview-greeting-text');
if (el) {
  const text = el.textContent || '';
  check(text.startsWith(g.text), `问候语文本以问候语开头（text: "${text}"）`);
  check(!text.startsWith('，'), '问候语文本不以孤立逗号开头');
  check(text.includes('测试用户'), '问候语文本包含用户名');
}

// 4) 保持原有行为：切走再切回总览仍会重新加载统计
const before = statsCalls.length;
app.changeTab('history');
await new Promise(r => setTimeout(r, 30));
app.changeTab('overview');
await new Promise(r => setTimeout(r, 50));
check(statsCalls.length > before, `切回总览重新加载统计（${before} -> ${statsCalls.length}）`);

// 清理定时器，避免 Node 进程不退出
try {
  app.stopRuntimeLogPolling();
  app.stopTasklistAutoWatch();
  app.stopCalendarAutoWatch();
  if (app._overviewGreetingTimer) {
    clearInterval(app._overviewGreetingTimer);
    app._overviewGreetingTimer = null;
  }
} catch (e) {}

if (failed) {
  console.error('OVERVIEW FIRST-LOAD TEST FAILED');
  process.exit(1);
}
console.log('OVERVIEW FIRST-LOAD TEST PASSED');
process.exit(0);
