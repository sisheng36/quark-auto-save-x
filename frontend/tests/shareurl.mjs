// 资源搜索点击分享：链接不得把当前页带走；getShareurl 不得因空链/大写 ID 抛错（Vue 3 白屏根因）。
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { resolveShareurl, formatSuggestionShareId } from '../src/shareurl.js';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const html = readFileSync(path.join(root, 'app/templates/index.html'), 'utf8');

const failures = [];
function assert(cond, msg) {
  if (!cond) failures.push(msg);
}

assert(
  !/:href="suggestion\.shareurl"/.test(html),
  '搜索结果不得再用 :href="suggestion.shareurl"，点击会离开当前页'
);
assert(
  (html.match(/formatSuggestionShareId\(suggestion\)/g) || []).length >= 2,
  '创建任务与任务列表两处搜索下拉都应展示分享 ID 文本'
);

assert(resolveShareurl('') === '', '空链接应返回空串');
assert(resolveShareurl(null) === '', 'null 链接应返回空串');
assert(resolveShareurl(undefined) === '', 'undefined 链接应返回空串');

const mixedId = 'https://pan.quark.cn/s/AbC123xyz';
assert(
  resolveShareurl(mixedId) === mixedId,
  '无 path 时应返回根分享地址，且兼容大写 ID'
);
assert(
  resolveShareurl(mixedId, {}) === mixedId,
  '空 path 对象应视为根目录'
);
assert(
  resolveShareurl(mixedId, { fid: '0', name: '/' }) === mixedId,
  'fid=0 应回到根分享地址'
);
assert(
  resolveShareurl(mixedId, { fid: 0, name: '/' }) === mixedId,
  'fid 数字 0 应回到根分享地址'
);

const nested = resolveShareurl(mixedId, { fid: 'fidABC', name: '第1季' });
assert(
  nested === `${mixedId}#/list/share/fidABC-第1季`,
  `进入子目录应追加 hash 路径，实际: ${nested}`
);

const alreadyNested = resolveShareurl(nested, { fid: 'fidDEF', name: '第2季' });
assert(
  alreadyNested === `${nested}/fidDEF-第2季`,
  `已有 hash 路径时应追加子目录，实际: ${alreadyNested}`
);

assert(
  resolveShareurl(nested, { fid: 'fidABC', name: '第1季' }) === nested,
  '同一 fid 应截回该层路径'
);

try {
  resolveShareurl('not-a-share-url', { fid: '0' });
} catch (e) {
  failures.push(`非法链接不应抛错: ${e.message}`);
}

assert(
  formatSuggestionShareId('https://pan.quark.cn/s/AbC123#/list/share/x') === 'AbC123',
  '展示用分享 ID 应去掉域名与 hash'
);
assert(formatSuggestionShareId(null) === '', '空 suggestion 展示应为空串');

// Vue 3 运行时编译用 Proxy + with(_ctx)：document / window / $ 会被当成实例属性变成 undefined，渲染即白屏
const appHtml = html.slice(html.indexOf('<div id="app">'));
assert(
  !/document\./.test(appHtml),
  '#app 模板不得使用 document.，Vue 3 会读成 undefined 并卸掉整页'
);
assert(
  !/window\./.test(appHtml),
  '#app 模板不得使用 window.，Vue 3 会读成 undefined'
);
assert(
  !/\$\(['"]/.test(appHtml),
  '#app 模板不得使用 $()，Vue 3 会读成 undefined'
);
assert(
  /fileSelect\.modalType/.test(appHtml),
  '文件夹选择框类型应读 fileSelect.modalType，而不是 DOM'
);
assert(
  /hideFileSelectModal\(\)/.test(appHtml),
  '关闭文件夹选择框应走 hideFileSelectModal()'
);

// 复现 Vue 3 运行时编译 Proxy：非全局白名单标识符会被 has() 认领，get 得到 undefined
const vueLikeHas = new Function(
  'key',
  'const allowed = "Infinity,undefined,NaN,Math,Number,Date,Array,Object,Boolean,String,JSON,console,Error,Symbol";' +
  'return key[0] !== "_" && allowed.split(",").indexOf(key) === -1;'
);
assert(vueLikeHas('document') === true, 'Vue 3 运行时 Proxy 会认领 document');
assert(vueLikeHas('window') === true, 'Vue 3 运行时 Proxy 会认领 window');
assert(vueLikeHas('$') === true, 'Vue 3 运行时 Proxy 会认领 $');
assert(vueLikeHas('fileSelect') === true, '组件数据 fileSelect 应由 Proxy 认领');
const readThroughProxy = new Function(
  'ctx',
  'const proxy = new Proxy(ctx, { has(_, key) { return typeof key === "string" && key[0] !== "_" && "Infinity,undefined,NaN,Math,JSON,Object,String".split(",").indexOf(key) === -1; }, get(t, k) { return t[k]; } });' +
  'with (proxy) { return typeof document; }'
);
assert(
  readThroughProxy({ fileSelect: { modalType: 'source' } }) === 'undefined',
  '模板里写 document 时，Vue 3 Proxy 会把它变成 undefined'
);
assert(
  readThroughProxy({ document: { getElementById() { return {}; } } }) === 'object',
  '只有把 document 放到实例上才读得到'
);

if (failures.length) {
  console.error('shareurl 回归失败:');
  for (const f of failures) console.error(' -', f);
  process.exit(1);
}
console.log('shareurl 回归通过');
