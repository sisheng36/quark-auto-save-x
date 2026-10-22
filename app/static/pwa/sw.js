/* 夸克自动转存 · PWA Service Worker
 *
 * 由 Flask 在 /sw.js 提供，注入以下占位符：
 *   __CACHE_VERSION__   应用版本号 + PWA schema 版本（发版自动升级缓存）
 *   __PRECACHE_URLS__   预缓存清单（JSON 数组）
 *   __OFFLINE_URL__     离线兜底页地址
 *
 * 缓存策略：
 *   - /static/* 静态资源：命中缓存立即返回并后台刷新（stale-while-revalidate）
 *   - 页面导航：network-first，失败回退「已缓存的页面外壳」，再失败回退离线页
 *   - 其余同源 GET：network-first，失败回退「最近一次成功响应」（离线只读回退）
 *   - POST/PUT/DELETE、SSE、跨域请求：一律放行，不缓存、不排队、不离线重放
 */

const CACHE_VERSION = '__CACHE_VERSION__';
const PRECACHE_URLS = __PRECACHE_URLS__;
const OFFLINE_URL = '__OFFLINE_URL__';

const PRECACHE = 'qas-precache-' + CACHE_VERSION;
const PAGE_CACHE = 'qas-page-' + CACHE_VERSION;
const API_CACHE = 'qas-api-' + CACHE_VERSION;

// 运行时缓存条目上限，超出后按最旧条目淘汰
const RUNTIME_MAX_ENTRIES = 200;

// 不做缓存的二进制/图片接口：体积大且离线价值低，避免挤占运行时缓存配额
const EXCLUDED_PREFIXES = ['/cache/images/', '/api/proxy/douban-image'];

/* ---------------- 安装 / 激活 ---------------- */

self.addEventListener('install', (event) => {
  event.waitUntil(precache());
  // 不调用 skipWaiting()：新版本先进入 waiting，用户点「刷新」后才接管
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    await cleanupOldCaches();
    await self.clients.claim();
  })());
});

async function precache() {
  const cache = await caches.open(PRECACHE);
  for (const url of PRECACHE_URLS || []) {
    try {
      // cache:'reload' 绕过浏览器 HTTP 缓存，避免预缓存到被强缓存的旧版本资源
      const response = await fetch(new Request(url, { cache: 'reload', credentials: 'same-origin' }));
      if (response && response.ok) {
        await cache.put(url, response);
      }
    } catch (e) {
      // 单个资源失败不影响整体安装，运行时仍可按需补缓存
    }
  }
}

async function cleanupOldCaches() {
  const prefixes = ['qas-precache-', 'qas-page-', 'qas-api-'];
  try {
    const names = await caches.keys();
    for (const name of names) {
      if (!prefixes.some((p) => name.indexOf(p) === 0)) continue;
      if (name === PRECACHE || name === PAGE_CACHE || name === API_CACHE) continue;
      await caches.delete(name);
    }
  } catch (e) {
    // 忽略：清理失败不影响新版本工作
  }
}

/* ---------------- 页面与前端通信 ---------------- */

self.addEventListener('message', (event) => {
  const data = event.data || {};
  if (data.type === 'SKIP_WAITING') {
    self.skipWaiting();
    return;
  }
  if (data.type === 'CLEAR_API_CACHE') {
    if (event.waitUntil) event.waitUntil(clearApiCaches());
    else clearApiCaches();
  }
});

// 清除业务数据缓存（登出 / 认证失败时调用），静态应用壳保留
async function clearApiCaches() {
  try {
    const names = await caches.keys();
    for (const name of names) {
      if (name.indexOf('qas-api-') === 0) {
        await caches.delete(name);
      }
    }
  } catch (e) {
    // 忽略
  }
}

/* ---------------- 请求拦截 ---------------- */

self.addEventListener('fetch', (event) => {
  const request = event.request;

  // 写操作永不缓存、永不离线重放
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch (e) {
    return;
  }

  // 跨域请求交给浏览器自行处理
  if (url.origin !== self.location.origin) return;

  // 明确要求不走缓存的请求（如前端连通性探测）：直接交给网络，
  // 离线时必须真实失败，否则前端会误判为「在线」
  if (request.cache === 'no-store') return;

  // SSE 长连接：绝不能被缓存或拦截
  if (isStreamRequest(request, url)) return;

  // 退出登录：先清理业务缓存，再放行跳转
  if (url.pathname === '/logout') {
    event.waitUntil(clearApiCaches());
    return;
  }

  if (isStaticAsset(url)) {
    event.respondWith(handleStatic(request, url));
    return;
  }

  if (request.mode === 'navigate') {
    event.respondWith(handleNavigation(request));
    return;
  }

  if (isCacheable(request, url)) {
    event.respondWith(handleApi(request));
  }
});

function isStreamRequest(request, url) {
  if (url.pathname === '/api/calendar/stream') return true;
  const accept = request.headers.get('accept') || '';
  return accept.indexOf('text/event-stream') !== -1;
}

function isStaticAsset(url) {
  return url.pathname.indexOf('/static/') === 0 || url.pathname === '/favicon.ico';
}

function isCacheable(request, url) {
  for (const prefix of EXCLUDED_PREFIXES) {
    if (url.pathname.indexOf(prefix) === 0) return false;
  }
  // 分段请求（断点续传）不缓存：只缓存完整响应
  if (request.headers.get('range')) return false;
  return true;
}

/* ---------------- 三种策略 ---------------- */

// 静态资源：命中即返回并后台刷新；网络失败时回退到预缓存条目
async function handleStatic(request, url) {
  const cache = await caches.open(PRECACHE);
  const cached = await cache.match(request.url);
  if (cached) {
    revalidate(cache, request);
    return cached;
  }
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      cache.put(request.url, response.clone());
    }
    return response;
  } catch (e) {
    // 精确 URL 未命中时，退回按 pathname 预缓存的同名资源
    const fallback = await cache.match(url.pathname);
    if (fallback) return fallback;
    throw e;
  }
}

// 页面导航：network-first，离线时回退已缓存的页面外壳，最后回退离线页
async function handleNavigation(request) {
  const cache = await caches.open(PAGE_CACHE);
  try {
    const response = await fetch(request);
    if (response && response.ok && response.type === 'basic') {
      cache.put(request.url, response.clone());
      trimCache(cache, RUNTIME_MAX_ENTRIES);
    }
    return response;
  } catch (e) {
    const cached = await cache.match(request.url);
    if (cached) return markFromCache(cached);
    const offline = await caches.match(OFFLINE_URL);
    if (offline) return offline;
    return new Response('当前处于离线状态，且没有可用的本地缓存。', {
      status: 503,
      headers: { 'Content-Type': 'text/plain; charset=utf-8' }
    });
  }
}

// 业务数据 GET：network-first，离线时回退最近一次成功响应
async function handleApi(request) {
  const cache = await caches.open(API_CACHE);
  try {
    const response = await fetch(request);
    // 认证失败：清掉业务缓存，避免把未授权内容留在设备上
    if (response && (response.status === 401 || response.status === 403)) {
      await clearApiCaches();
      return response;
    }
    if (response && response.ok && response.type === 'basic') {
      cache.put(request.url, response.clone());
      trimCache(cache, RUNTIME_MAX_ENTRIES);
    }
    return response;
  } catch (e) {
    const cached = await cache.match(request.url);
    if (cached) return markFromCache(cached);
    return new Response(JSON.stringify({ success: false, message: '离线状态：暂无缓存数据' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json; charset=utf-8' }
    });
  }
}

/* ---------------- 工具函数 ---------------- */

// 后台刷新静态资源（失败静默）
function revalidate(cache, request) {
  fetch(request)
    .then((response) => {
      if (response && response.ok && response.type === 'basic') {
        return cache.put(request.url, response.clone());
      }
    })
    .catch(() => {});
}

// 给离线回退的响应打标记，便于前端区分「真实数据」与「缓存数据」
async function markFromCache(response) {
  try {
    if (!response || response.status === 204 || response.status === 304 || response.status < 200) {
      return response;
    }
    const headers = new Headers(response.headers);
    headers.set('X-QAS-From-Cache', '1');
    const body = await response.clone().arrayBuffer();
    return new Response(body, {
      status: response.status,
      statusText: response.statusText,
      headers: headers
    });
  } catch (e) {
    return response;
  }
}

// 缓存条目过多时按插入顺序淘汰最旧条目
async function trimCache(cache, max) {
  try {
    const keys = await cache.keys();
    if (keys.length <= max) return;
    for (let i = 0; i < keys.length - max; i++) {
      await cache.delete(keys[i]);
    }
  } catch (e) {
    // 忽略
  }
}
