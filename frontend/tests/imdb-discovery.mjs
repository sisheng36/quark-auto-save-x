// 影视发现页 IMDb 补全回归：确认加载时会请求豆瓣 IMDb 缓存接口，
// 并把 IMDb 回填到卡片、随后带着 imdb_id 去查 Emby 入库状态。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { JSDOM } from 'jsdom';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
let html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');
html = html.replace('[[ frontend_scripts | safe ]]', '');
html = html.replace('version: "[[ version ]]"', 'version: "dev"');
html = html.replace('plugin_flags: "[[ plugin_flags ]]"', 'plugin_flags: ""');

const bundlePath = process.env.QAS_SMOKE_BUNDLE;
if (!bundlePath) {
  console.error('请设置 QAS_SMOKE_BUNDLE 指向构建产物');
  process.exit(2);
}
const bundle = readFileSync(bundlePath, 'utf8');

const dom = new JSDOM(html, {
  url: 'http://127.0.0.1:5005/',
  runScripts: 'outside-only',
  pretendToBeVisual: true
});
const { window } = dom;
const errors = [];
window.console.error = (...a) => errors.push(a.map(String).join(' '));
window.console.warn = () => {};
window.matchMedia = () => ({ matches: false, addEventListener() {}, removeEventListener() {} });
const jqObj = () => ({ on() { return this; }, tooltip() { return this; }, collapse() { return this; },
  hasClass() { return false; }, addClass() { return this; }, removeClass() { return this; }, length: 0 });
window.$ = window.jQuery = () => jqObj();
window.EventSource = class { constructor() {} addEventListener() {} close() {} };
window.pinyinPro = { pinyin: (s) => String(s || '') };
window.sortFileByName = (f) => [String((f && f.file_name) || f || '')];

// 记录请求，用于断言调用顺序与载荷
const calls = [];
window.axios = {
  get: async (url, cfg) => { calls.push({ method: 'get', url, cfg }); return { data: { success: false } }; },
  post: async (url, body) => {
    calls.push({ method: 'post', url, body });
    if (url === '/api/douban/imdb_map') {
      const map = {};
      for (const it of body.items) {
        // 1292052 有 IMDb；999999 豆瓣没有
        map[it.id] = it.id === '1292052'
          ? { imdb_id: 'tt0111161', status: 'ok', cached: true }
          : { imdb_id: '', status: 'missing', cached: true };
      }
      return { data: { success: true, data: { imdb_map: map } } };
    }
    if (url === '/api/emby/check_items') {
      const statusMap = {};
      for (const it of body.items) {
        statusMap['title-' + it.title + '-' + (it.year || '')] = it.imdb_id === 'tt0111161'
          ? { in_library: true, seasons: '', matched_name: 'The Shawshank Redemption', match_by: 'imdb' }
          : { in_library: false, seasons: '', matched_name: '' };
      }
      return { data: { success: true, data: { status_map: statusMap, configured: true } } };
    }
    return { data: { success: false } };
  },
  put: async () => ({ data: { success: false } }),
  delete: async () => ({ data: { success: false } })
};

window.eval('"use strict";\n' + bundle);
await new Promise(r => setTimeout(r, 100));

const app = window.__QAS_APP__;
if (!app) { console.error('FAIL: __QAS_APP__ 未挂载'); process.exit(1); }

let failed = 0;
const check = (name, actual, expected) => {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  console.log((ok ? '  ✅ ' : '  ❌ ') + name + (ok ? '' : `: 期望 ${JSON.stringify(expected)}, 实际 ${JSON.stringify(actual)}`));
  if (!ok) failed++;
};

app.discovery.items = [
  { id: '1292052', title: '肖申克的救赎', year: '1994', content_type: 'movie', pic: {} },
  { id: '999999', title: '查无此片', year: '2020', content_type: 'movie', pic: {} },
  { id: 'tmdb-movie-603', title: '黑客帝国', year: '1999', tmdb_id: 603, media_type: 'movie', content_type: 'movie', pic: {} }
];
app.discovery.discoveryRequestId = 7;

await app.checkEmbyStatus(7, 'discovery');

const imdbCall = calls.find(c => c.url === '/api/douban/imdb_map');
check('调用了豆瓣 IMDb 接口', !!imdbCall, true);
check('只请求没有 TMDB/IMDb 的豆瓣卡', imdbCall.body.items.map(i => i.id), ['1292052', '999999']);
check('请求带 is_tv 标记', imdbCall.body.items.map(i => i.is_tv), [false, false]);

const embyCall = calls.find(c => c.url === '/api/emby/check_items');
check('随后查询 Emby 入库', !!embyCall, true);
check('载荷带上回填的 imdb_id',
  embyCall.body.items.map(i => i.imdb_id || ''),
  ['tt0111161', '', '']);

check('卡片回填 imdb_id', app.discovery.items[0].imdb_id, 'tt0111161');
check('豆瓣无 IMDb 的卡片保持空', app.discovery.items[1].imdb_id, undefined);
check('入库状态已加载', app.embyStatusLoaded, true);
check('IMDb 命中显示已入库', app.getEmbyStatus(app.discovery.items[0]).in_library, true);
check('未命中显示未入库', app.getEmbyStatus(app.discovery.items[1]).in_library, false);
check('tooltip 标注 IMDb 匹配', app.getEmbyStatusTooltip(app.discovery.items[0]), '已在 Emby 入库（IMDb 匹配）');
check('tooltip 说明豆瓣无 IMDb', app.getEmbyStatusTooltip(app.discovery.items[1]),
  '未在 Emby 入库（豆瓣无 IMDb，按名称比对）');

// 已带 imdb_id 的卡片不应重复请求
calls.length = 0;
app.discovery.items = [{ id: '1292052', title: '肖申克的救赎', year: '1994',
  content_type: 'movie', imdb_id: 'tt0111161', pic: {} }];
app.discovery.discoveryRequestId = 8;
await app.checkEmbyStatus(8, 'discovery');
check('已有 imdb_id 时不重复拉豆瓣', calls.some(c => c.url === '/api/douban/imdb_map'), false);
check('直接查 Emby', calls.some(c => c.url === '/api/emby/check_items'), true);

try { app.stopRuntimeLogPolling(); app.stopTasklistAutoWatch(); app.stopCalendarAutoWatch(); } catch (e) {}

if (errors.length) {
  console.error('运行时错误:', errors.slice(0, 5));
  failed++;
}
console.log(failed ? `IMDB DISCOVERY TEST FAILED (${failed})` : 'IMDB DISCOVERY TEST PASSED');
process.exit(failed ? 1 : 0);
