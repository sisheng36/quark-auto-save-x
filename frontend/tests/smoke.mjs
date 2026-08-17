// Vue 3 迁移冒烟测试：用 jsdom 挂载真实 Flask 模板 + 开发版构建产物，
// 捕获运行时错误与 Vue 警告。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');

// 1) 读取 Flask 模板并做最小化 Jinja 替换
let html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
html = html.replace('[[ frontend_scripts | safe ]]', '');
html = html.replace('version: "[[ version ]]"', 'version: "dev"');
html = html.replace('plugin_flags: "[[ plugin_flags ]]"', 'plugin_flags: ""');

// 0) 移动端侧边栏开关回归检查：模板必须包含能打开 #sidebarMenu 抽屉的按钮
const toggleBtn = html.match(/<button[^>]*data-target="#sidebarMenu"[^>]*>[\s\S]*?<\/button>/);
if (!toggleBtn) {
  console.error('FAIL: 未找到移动端侧边栏开关按钮（data-target="#sidebarMenu"）');
  process.exit(1);
}
if (!/d-md-none/.test(toggleBtn[0])) {
  console.error('FAIL: 侧边栏开关按钮缺少 d-md-none（桌面端不应显示）');
  process.exit(1);
}
if (!/<i class="bi bi-[a-z0-9-]+"/.test(toggleBtn[0])) {
  console.error('FAIL: 侧边栏开关按钮缺少图标元素（<i class="bi ...">）');
  process.exit(1);
}
console.log('移动端侧边栏开关按钮: 存在（d-md-none + data-target="#sidebarMenu" + 图标元素）');

// 0.1) iOS 添加到主屏幕图标回归检查：必须声明 apple-touch-icon（180x180 PNG）
const iconLink = html.match(/<link[^>]*rel="apple-touch-icon"[^>]*>/);
if (!iconLink || !/href="\.\/static\/images\/apple-touch-icon\.png"/.test(iconLink[0])) {
  console.error('FAIL: 缺少 apple-touch-icon 链接（./static/images/apple-touch-icon.png）');
  process.exit(1);
}
console.log('apple-touch-icon 链接: 存在（180x180 PNG）');

// 2) 开发版构建产物（含 Vue 警告，便于发现问题）
const bundlePath = process.env.QAS_SMOKE_BUNDLE;
if (!bundlePath) {
  console.error('请设置 QAS_SMOKE_BUNDLE 指向开发版构建产物');
  process.exit(2);
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

window.console.error = (...args) => { errors.push(args.map(String).join(' ')); };
window.console.warn = (...args) => { warnings.push(args.map(String).join(' ')); };

// 3) 浏览器全局桩
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const jqObj = () => ({
  on() { return this; }, tooltip() { return this; }, collapse() { return this; },
  hasClass() { return false; }, addClass() { return this; }, removeClass() { return this; },
  length: 0
});
window.$ = window.jQuery = () => jqObj();
window.axios = {
  get: async () => ({ data: { success: false, message: 'smoke' } }),
  post: async () => ({ data: { success: false, message: 'smoke' } }),
  put: async () => ({ data: { success: false, message: 'smoke' } }),
  delete: async () => ({ data: { success: false, message: 'smoke' } })
};
window.EventSource = class {
  constructor() {}
  addEventListener() {}
  close() {}
};
window.pinyinPro = { pinyin: (s) => String(s || '') };
window.sortFileByName = (f) => [String((f && f.file_name) || f || '')];

// 4) 执行构建产物（单 chunk 无 import，可直接 eval）
try {
  // 显式严格模式：与浏览器 ES 模块语义一致，能暴露“隐式全局变量赋值”类错误
  window.eval('"use strict";\n' + bundle);
} catch (e) {
  console.error('bundle 执行失败:', e);
  process.exit(1);
}

await new Promise(r => setTimeout(r, 100));

// 5) 断言
const app = window.__QAS_APP__;
if (!app) {
  console.error('FAIL: __QAS_APP__ 未挂载');
  process.exit(1);
}
const appEl = window.document.querySelector('#app');
const rendered = appEl && appEl.children.length > 0;
console.log('app 实例:', !!app, '| 已渲染节点数:', appEl ? appEl.children.length : -1);

// 依次切换全部标签页，覆盖各页面模板的运行时编译与渲染
const tabs = ['overview', 'tasklist', 'discovery', 'calendar', 'history', 'filemanager', 'config', 'runlogs'];
for (const tab of tabs) {
  try {
    app.activeTab = tab;
    await new Promise(r => setTimeout(r, 20));
    console.log('标签页', tab, '渲染正常');
  } catch (e) {
    errors.push(`切换 ${tab} 失败: ${e.message}`);
  }
}

// 清理 runlogs/tasklist/calendar 的轮询定时器，避免 Node 进程不退出
try {
  app.stopRuntimeLogPolling();
  app.stopTasklistAutoWatch();
  app.stopCalendarAutoWatch();
  app._overviewGreetingTimer && clearInterval(app._overviewGreetingTimer);
} catch (e) {}

const vueErrors = errors.filter(e =>
  !e.includes('jsdom') &&
  !e.includes('not implemented') &&
  !e.includes('smoke') // 测试环境无后端，axios 桩导致的预期日志
);
const vueWarnings = warnings.filter(w => w.includes('Vue') || w.includes('[Vue'));
console.log('console.error 数:', vueErrors.length);
console.log('Vue 警告数:', vueWarnings.length);
for (const w of vueWarnings.slice(0, 12)) console.log('  warn:', w.slice(0, 220));
for (const e of vueErrors.slice(0, 12)) console.log('  error:', e.slice(0, 220));

if (!rendered || vueErrors.length > 0) {
  console.error('SMOKE TEST FAILED');
  process.exit(1);
}
console.log('SMOKE TEST PASSED');
process.exit(0);
