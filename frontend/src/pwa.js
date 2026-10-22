/**
 * PWA 控制模块：Service Worker 注册、安装提示、离线状态、版本更新。
 *
 * 注意：本模块刻意不引入 Vue —— 应用使用的是 vue/dist/vue.esm-bundler.js，
 * 再引入一份 'vue' 会产生第二个实例，导致响应式追踪失效。
 * 状态以普通对象形式通过回调交给 Vue 组件保存。
 */

// Service Worker 脚本地址（由 Flask 在站点根路径提供，作用域覆盖整站）
const SW_PATH = '/sw.js';
// 安装提示的忽略状态：7 天内不再展示
const DISMISS_KEY = 'quarkAutoSave_pwa_install_dismissed_at';
// 已安装标记：安装完成后不再提示
const INSTALLED_KEY = 'quarkAutoSave_pwa_installed';
const DISMISS_TTL_MS = 7 * 24 * 60 * 60 * 1000;

let deferredPrompt = null;
let registration = null;
let reloading = false;
let onlineOverride = null;
const listeners = [];

// 连通性探测地址：体积小、公开可访问，且不会被 Service Worker 用缓存兜底
const PROBE_URL = '/manifest.webmanifest';

/* ---------------- 基础能力探测 ---------------- */

// 是否以独立应用（standalone）方式运行
function isStandaloneMode() {
  try {
    if (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) return true;
    if (window.matchMedia && window.matchMedia('(display-mode: fullscreen)').matches) return true;
    if (window.navigator.standalone === true) return true;
  } catch (e) {
    // 忽略：老浏览器不支持时按非独立模式处理
  }
  return false;
}

// 是否为 iOS / iPadOS（iPadOS 13+ 的 UA 伪装成 Mac，用触摸点数区分）
function isIOSDevice() {
  try {
    const ua = navigator.userAgent || '';
    if (/iPad|iPhone|iPod/.test(ua)) return true;
    if (navigator.platform === 'MacIntel' && (navigator.maxTouchPoints || 0) > 1) return true;
  } catch (e) {
    // 忽略
  }
  return false;
}

function readInstalled() {
  try {
    return localStorage.getItem(INSTALLED_KEY) === '1';
  } catch (e) {
    return false;
  }
}

function writeInstalled() {
  try {
    localStorage.setItem(INSTALLED_KEY, '1');
  } catch (e) {
    // 忽略：隐私模式下写入可能失败
  }
}

// 读取忽略状态（超过 7 天自动失效）
function readDismissed() {
  try {
    const ts = parseInt(localStorage.getItem(DISMISS_KEY) || '0', 10);
    if (!ts) return false;
    if (Date.now() - ts > DISMISS_TTL_MS) {
      localStorage.removeItem(DISMISS_KEY);
      return false;
    }
    return true;
  } catch (e) {
    return false;
  }
}

function writeDismissed() {
  try {
    localStorage.setItem(DISMISS_KEY, String(Date.now()));
  } catch (e) {
    // 忽略
  }
}

/* ---------------- 状态 ---------------- */

function buildState() {
  const installed = readInstalled();
  const dismissed = readDismissed();
  const isStandalone = isStandaloneMode();
  const isIOS = isIOSDevice();
  // navigator.onLine 在「应用打开时就已经断网」的场景下可能仍为 true，
  // 因此以连通性探测结果为准（探不到时退回 navigator.onLine）。
  const isOnline = onlineOverride !== null ? onlineOverride : navigator.onLine !== false;
  const canInstall = !!deferredPrompt;
  const updateReady = !!(registration && registration.waiting);
  return {
    // 原始状态
    canInstall: canInstall,
    isIOS: isIOS,
    isStandalone: isStandalone,
    isOnline: isOnline,
    updateReady: updateReady,
    installed: installed,
    dismissed: dismissed,
    // 派生状态（模板直接使用）
    showInstallHint: canInstall && !installed && !dismissed,
    showIosHint: isIOS && !isStandalone && !installed && !dismissed,
    showOffline: !isOnline,
    showUpdate: updateReady
  };
}

function notify() {
  const state = buildState();
  for (const listener of listeners) {
    try {
      listener(state);
    } catch (e) {
      // 单个订阅者异常不影响其它订阅者
    }
  }
}

export function getPwaState() {
  return buildState();
}

/* ---------------- 事件处理 ---------------- */

function onBeforeInstallPrompt(event) {
  // 阻止默认行为，改由应用内的「安装应用」按钮触发
  event.preventDefault();
  deferredPrompt = event;
  notify();
}

function onAppInstalled() {
  deferredPrompt = null;
  writeInstalled();
  notify();
}

function onOnline() {
  // 网络恢复：再探测一次确认真的连通
  probeConnectivity();
}

function onOffline() {
  setOnline(false);
}

// 设置在线状态（null 表示交回 navigator.onLine 判断）
function setOnline(value) {
  if (onlineOverride === value) return;
  onlineOverride = value;
  notify();
}

// 连通性探测：navigator.onLine 只反映网卡状态，
// 「应用打开时就没网」时它仍可能为 true，必须实际请求一次才能确认。
function probeConnectivity() {
  try {
    if (navigator.onLine === false) {
      setOnline(false);
      return;
    }
    fetch(PROBE_URL, { method: 'GET', cache: 'no-store', credentials: 'same-origin' })
      .then((response) => {
        setOnline(!!response);
      })
      .catch(() => {
        setOnline(false);
      });
  } catch (e) {
    setOnline(false);
  }
}

function onVisibilityChange() {
  // 回到前台时复核一次网络状态
  if (document.visibilityState === 'visible') {
    probeConnectivity();
  }
}

function onControllerChange() {
  // 新版 Service Worker 接管后刷新页面，让前端拿到新的资源
  if (reloading) return;
  reloading = true;
  try {
    window.location.reload();
  } catch (e) {
    // 忽略
  }
}

/* ---------------- 注册 ---------------- */

// 仅生产构建注册：开发模式（vite dev / FRONTEND_DEV=1）不注册，避免调试受干扰
function shouldRegister() {
  try {
    if (typeof navigator === 'undefined' || !('serviceWorker' in navigator)) return false;
    if (!import.meta.env || !import.meta.env.PROD) return false;
    return true;
  } catch (e) {
    return false;
  }
}

function registerServiceWorker() {
  const config = window.__QAS_CONFIG__ || {};
  const version = encodeURIComponent(config.version || 'dev');
  navigator.serviceWorker
    .register(SW_PATH + '?v=' + version, { scope: '/', updateViaCache: 'none' })
    .then((reg) => {
      registration = reg;
      // 已存在待接管的新版本
      if (reg.waiting) {
        notify();
      }
      // 发现新版本：安装完成后进入 waiting，等待用户确认刷新
      if (reg.addEventListener) {
        reg.addEventListener('updatefound', () => {
          const worker = reg.installing;
          if (!worker) return;
          worker.addEventListener('statechange', () => {
            if (worker.state === 'installed' && navigator.serviceWorker.controller) {
              notify();
            }
          });
        });
      }
      // 定期检查更新（每小时一次，回到前台时也会触发）
      try {
        setInterval(() => {
          reg.update().catch(() => {});
        }, 60 * 60 * 1000);
      } catch (e) {
        // 忽略
      }
    })
    .catch(() => {
      // 非安全上下文（如 http 局域网地址）或浏览器不支持时静默跳过
    });
}

/**
 * 初始化 PWA：注册 Service Worker 并把状态变化回调给调用方。
 * @param {(state: object) => void} onState 状态变化回调
 * @returns {{ destroy: () => void }}
 */
export function initPwa(onState) {
  if (typeof onState === 'function') {
    listeners.push(onState);
  }
  window.addEventListener('beforeinstallprompt', onBeforeInstallPrompt);
  window.addEventListener('appinstalled', onAppInstalled);
  window.addEventListener('online', onOnline);
  window.addEventListener('offline', onOffline);
  document.addEventListener('visibilitychange', onVisibilityChange);
  if (navigator.serviceWorker && navigator.serviceWorker.addEventListener) {
    navigator.serviceWorker.addEventListener('controllerchange', onControllerChange);
  }
  notify();
  // 首屏探测一次真实连通性（离线打开时 navigator.onLine 可能仍是 true）
  probeConnectivity();

  if (shouldRegister()) {
    registerServiceWorker();
  }

  return {
    destroy() {
      const idx = listeners.indexOf(onState);
      if (idx !== -1) listeners.splice(idx, 1);
      window.removeEventListener('beforeinstallprompt', onBeforeInstallPrompt);
      window.removeEventListener('appinstalled', onAppInstalled);
      window.removeEventListener('online', onOnline);
      window.removeEventListener('offline', onOffline);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      if (navigator.serviceWorker && navigator.serviceWorker.removeEventListener) {
        navigator.serviceWorker.removeEventListener('controllerchange', onControllerChange);
      }
    }
  };
}

/* ---------------- 对外操作 ---------------- */

/**
 * 触发安装（需用户手势）。iOS 不支持该 API，需引导「分享 → 添加到主屏幕」。
 */
export async function installApp() {
  if (!deferredPrompt) return false;
  try {
    deferredPrompt.prompt();
    const choice = await deferredPrompt.userChoice;
    deferredPrompt = null;
    notify();
    return choice && choice.outcome === 'accepted';
  } catch (e) {
    deferredPrompt = null;
    notify();
    return false;
  }
}

/**
 * 应用更新：通知待接管的 Service Worker 立即激活，随后由 controllerchange 触发刷新。
 */
export function applyUpdate() {
  try {
    if (!registration) return false;
    const waiting = registration.waiting;
    if (waiting) {
      waiting.postMessage({ type: 'SKIP_WAITING' });
      return true;
    }
    // 尚无 waiting 版本时主动检查一次
    if (registration.update) {
      registration.update().catch(() => {});
    }
  } catch (e) {
    // 忽略
  }
  return false;
}

/**
 * 清除业务数据缓存（退出登录时调用），静态应用壳保留。
 */
export async function clearRuntimeCaches() {
  try {
    if ('caches' in window) {
      const names = await caches.keys();
      for (const name of names) {
        if (name.indexOf('qas-api-') === 0) {
          await caches.delete(name);
        }
      }
    }
  } catch (e) {
    // 忽略
  }
  // 同时通知 Service Worker 清理，覆盖其它标签页
  try {
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistration) {
      const reg = await navigator.serviceWorker.getRegistration();
      if (reg && reg.active) {
        reg.active.postMessage({ type: 'CLEAR_API_CACHE' });
      }
    }
  } catch (e) {
    // 忽略
  }
}

/**
 * 记住「安装应用」提示已被关闭（7 天内不再展示）。
 */
export function dismissInstallHint() {
  writeDismissed();
  notify();
}
