// 历史页/文件整理页渲染回归测试：模拟真实记录数据，捕获渲染错误。
// 覆盖转存记录表格与文件整理表格中的行渲染方法调用（如 isMobileDevice），
// 防止此类方法被误删后导致整页白屏（刷新后因 activeTab 持久化仍会白屏）。
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
const jq = () => ({
  on() { return this; }, tooltip() { return this; }, collapse() { return this; },
  hasClass() { return false; }, addClass() { return this; }, removeClass() { return this; },
  length: 0
});
window.$ = window.jQuery = () => jq();
window.EventSource = class { constructor() {} addEventListener() {} close() {} };
window.pinyinPro = { pinyin: (s) => String(s || '') };
window.sortFileByName = (f) => [String((f && f.file_name) || f || '')];
// 模拟“用户刷新时仍停留在历史页”
window.localStorage.setItem('quarkAutoSave_activeTab', 'history');

const pad = n => String(n).padStart(2, '0');
const today = new Date();
const todayStr = `${today.getFullYear()}-${pad(today.getMonth() + 1)}-${pad(today.getDate())}`;

const records = [];
for (let i = 0; i < 18; i++) {
  const ts = Math.floor(Date.now() / 1000) - i * 86400;
  records.push({
    id: i + 1,
    task_name: '剧集 - 驯龙高手',
    original_name: '驯龙高手 S01E0' + (i + 1) + ' [超长原始文件名测试截断展开逻辑 副标题 制作组 分辨率 4K 高码率 收藏版].mkv',
    renamed_to: '驯龙高手 - S01E0' + (i + 1) + ' [超长转存文件名测试截断展开逻辑 副标题 制作组 分辨率 4K 高码率 收藏版].mkv',
    file_size: 4294967296,
    duration: '42:00',
    resolution: '4K',
    transfer_time: ts,
    transfer_time_readable: `${todayStr} 10:00:00`,
    modify_date: ts,
    modify_date_readable: `${todayStr} 09:00:00`,
    file_size_readable: '4.00 GB',
    file_id: 'fid' + i,
    file_type: 'mkv',
    save_path: '/media/剧集/驯龙高手'
  });
}

const files = [];
for (let i = 0; i < 8; i++) {
  files.push({
    fid: 'f' + i,
    file_name: '驯龙高手 S01E0' + (i + 1) + ' [超长文件名测试截断展开逻辑 副标题 制作组 分辨率 4K 高码率].mkv',
    dir: false,
    size: 4294967296,
    updated_at: Math.floor(Date.now() / 1000),
    file_type: 'mkv'
  });
}

const cfg = {
  tasklist: [], cookie: [], push_config: {}, media_servers: {}, magic_regex: {},
  episode_patterns: [], tv_show_keywords: [], task_settings: {}, button_display: {},
  source: {}, webui: {}, file_performance: {}, performance: {}, execution_mode: 'manual'
};

const byUrl = {
  '/data': { success: true, data: cfg },
  '/history_records': {
    success: true,
    data: {
      records,
      pagination: { total_records: 18, total_pages: 2, current_page: 1, page_size: 15 },
      all_task_names: ['剧集 - 驯龙高手']
    }
  },
  '/file_list': { success: true, data: { list: files, total: 8, paths: [] } },
  '/overview_transfer_stats': { success: true, data: {} },
  '/task_latest_info': { success: true, data: { latest_files: {}, latest_records: {} } },
  '/accounts_detail': { success: true, data: [] }
};
window.axios = {
  get: async (u) => {
    const hit = Object.keys(byUrl).find(k => String(u).includes(k));
    return { data: hit ? byUrl[hit] : { success: false, data: {} } };
  },
  post: async () => ({ data: { success: false, message: 'stub' } }),
  put: async () => ({ data: { success: false, message: 'stub' } }),
  delete: async () => ({ data: { success: false, message: 'stub' } })
};

try {
  window.eval('"use strict";\n' + bundle);
} catch (e) {
  console.error('bundle 执行失败:', e);
  process.exit(1);
}
await new Promise(r => setTimeout(r, 1200));

const app = window.__QAS_APP__;
if (!app) {
  console.error('FAIL: __QAS_APP__ 未挂载');
  process.exit(1);
}

let failed = false;
const appEl = window.document.querySelector('#app');
console.log('activeTab:', app.activeTab, '| #app 子节点数:', appEl ? appEl.children.length : -1);

const historyRows = window.document.querySelectorAll('.selectable-records tbody tr').length;
console.log('历史页表格行数:', historyRows, '(期望 18)');
if (historyRows !== 18) failed = true;

try {
  app.changeTab('filemanager');
  await new Promise(r => setTimeout(r, 500));
  const fileRows = window.document.querySelectorAll('.selectable-files tbody tr').length;
  console.log('文件整理页表格行数:', fileRows, '(期望 8)');
  if (fileRows !== 8) failed = true;
} catch (e) {
  errors.push('切换 filemanager 失败: ' + (e.stack || e.message));
  failed = true;
}

for (const e of errors.slice(0, 20)) {
  console.log('ERROR:', e.slice(0, 500));
  failed = true;
}
for (const w of warnings.filter(w => w.includes('Vue') || w.includes('[Vue')).slice(0, 20)) {
  console.log('WARN:', w.slice(0, 300));
}

console.log(failed ? 'DIAGNOSE HISTORY FAILED' : 'DIAGNOSE HISTORY PASSED');
process.exit(failed ? 1 : 0);
