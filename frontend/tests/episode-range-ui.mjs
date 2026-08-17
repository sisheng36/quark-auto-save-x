// 「集数范围」功能前端回归测试：
// 断言任务列表表单与新建任务表单都包含起始/结束集数输入框，
// 且 newTask / createTask.taskData 初始化包含 episode_start / episode_end 字段，
// 防止字段被误删或模板丢失导致功能失效。
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

let html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
html = html.replace('[[ frontend_scripts | safe ]]', '');
html = html.replace('version: "[[ version ]]"', 'version: "dev"');
html = html.replace('plugin_flags: "[[ plugin_flags ]]"', 'plugin_flags: ""');

let failed = false;
const check = (cond, label) => {
  console.log((cond ? 'PASS' : 'FAIL') + ': ' + label);
  if (!cond) failed = true;
};

// 1) 模板断言：任务列表表单与新建任务表单各有一对集数范围输入框
check(html.includes('v-model="task.episode_start"'), '任务列表表单存在 episode_start 输入框');
check(html.includes('v-model="task.episode_end"'), '任务列表表单存在 episode_end 输入框');
check(html.includes('v-model="createTask.taskData.episode_start"'), '新建任务表单存在 episode_start 输入框');
check(html.includes('v-model="createTask.taskData.episode_end"'), '新建任务表单存在 episode_end 输入框');
check(html.includes('起始集（可选）') && html.includes('结束集（可选）'), '输入框占位提示存在');

// 2) 挂载应用，断言数据初始化
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

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5005/',
  runScripts: 'outside-only',
  pretendToBeVisual: true
});
const { window } = dom;
window.console.error = () => {};
window.console.warn = () => {};
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
window.axios = {
  async get() { return { data: { success: false, message: 'stub' } }; },
  async post() { return { data: { success: false, message: 'stub' } }; },
  async put() { return { data: { success: false, message: 'stub' } }; },
  async delete() { return { data: { success: false, message: 'stub' } }; }
};

try {
  window.eval('"use strict";\n' + bundle);
} catch (e) {
  console.error('bundle 执行失败:', e);
  process.exit(1);
}
await new Promise(r => setTimeout(r, 150));

const app = window.__QAS_APP__;
check(!!app, '应用已挂载');
if (app) {
  check(app.newTask.episode_start === '', 'newTask.episode_start 初始化为空串');
  check(app.newTask.episode_end === '', 'newTask.episode_end 初始化为空串');
  check(app.createTask.taskData.episode_start === '', 'createTask.taskData.episode_start 初始化为空串');
  check(app.createTask.taskData.episode_end === '', 'createTask.taskData.episode_end 初始化为空串');
}

try {
  if (app) {
    app.stopRuntimeLogPolling();
    app.stopTasklistAutoWatch();
    app.stopCalendarAutoWatch();
    if (app._overviewGreetingTimer) {
      clearInterval(app._overviewGreetingTimer);
      app._overviewGreetingTimer = null;
    }
  }
} catch (e) {}

if (failed) {
  console.error('EPISODE RANGE UI TEST FAILED');
  process.exit(1);
}
console.log('EPISODE RANGE UI TEST PASSED');
process.exit(0);
