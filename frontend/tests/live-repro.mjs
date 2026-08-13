// 用真实后端数据在本地复现页面：登录后抓取的 /data、/api/calendar/tasks 等
// 通过 axios 桩回放给应用，检查各标签页渲染与 Vue 错误/警告。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const live = JSON.parse(readFileSync(process.env.QAS_LIVE_DATA, 'utf8'));

let html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
html = html.replace('[[ frontend_scripts | safe ]]', '');
html = html.replace('version: "[[ version ]]"', 'version: "dev"');
html = html.replace('plugin_flags: "[[ plugin_flags ]]"', 'plugin_flags: ""');

const bundle = readFileSync(process.env.QAS_SMOKE_BUNDLE, 'utf8');
const errors = [];
const warnings = [];

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5005/',
  runScripts: 'outside-only',
  pretendToBeVisual: true
});
const { window } = dom;
window.console.error = (...a) => errors.push(a.map(String).join(' '));
window.console.warn = (...a) => warnings.push(a.map(String).join(' '));
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const jq = () => ({
  on() { return this; }, tooltip() { return this; }, collapse() { return this; },
  hasClass() { return false; }, addClass() { return this; }, removeClass() { return this; },
  length: 0
});
window.$ = window.jQuery = () => jq();

const byUrl = {
  '/data': live.data,
  '/api/calendar/tasks': live.calendar_tasks,
  '/task_latest_info': live.latest,
  '/overview_transfer_stats': live.overview
};
const axiosStub = async (url) => {
  const hit = Object.keys(byUrl).find(k => String(url).includes(k));
  return { data: hit ? byUrl[hit] : { success: false, data: {} } };
};
window.axios = {
  get: (u) => axiosStub(u),
  post: (u) => axiosStub(u),
  put: (u) => axiosStub(u),
  delete: (u) => axiosStub(u)
};
window.EventSource = class {
  constructor() {}
  addEventListener() {}
  close() {}
};
window.pinyinPro = { pinyin: (s) => String(s || '') };
window.sortFileByName = (f) => [String((f && f.file_name) || f || '')];

try {
  window.eval('"use strict";\n' + bundle);
} catch (e) {
  console.error('bundle 执行失败:', e);
  process.exit(1);
}
await new Promise(r => setTimeout(r, 150));

const app = window.__QAS_APP__;
if (!app) { console.error('FAIL: 应用未挂载'); process.exit(1); }

const tabs = ['overview', 'tasklist', 'discovery', 'calendar', 'history', 'filemanager', 'config', 'runlogs'];
for (const tab of tabs) {
  try {
    app.activeTab = tab;
    await new Promise(r => setTimeout(r, 40));
    const count = window.document.querySelector('#app').children.length;
    console.log('标签页', tab, '渲染正常, #app 子节点:', count);
  } catch (e) {
    errors.push(`切换 ${tab} 失败: ${e.stack || e.message}`);
  }
}

try {
  app.stopRuntimeLogPolling();
  app.stopTasklistAutoWatch();
  app.stopCalendarAutoWatch();
} catch (e) {}

const vueErrors = errors.filter(e =>
  !e.includes('jsdom') &&
  !e.includes('not implemented') &&
  !e.includes('获取') &&
  !e.includes('加载')
);
const vueWarnings = warnings.filter(w => w.includes('Vue') || w.includes('[Vue'));
console.log('Vue 相关 error 数:', vueErrors.length);
console.log('Vue 警告数:', vueWarnings.length);
for (const w of vueWarnings.slice(0, 15)) console.log('  warn:', w.slice(0, 260));
for (const e of vueErrors.slice(0, 15)) console.log('  error:', e.slice(0, 300));
if (vueErrors.length > 0) { console.error('LIVE REPRO FAILED'); process.exit(1); }
console.log('LIVE REPRO PASSED（未发现 Vue 渲染错误）');
process.exit(0);
