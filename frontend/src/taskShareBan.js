// 任务列表「失败任务」筛选：纯函数实现，便于 Node 单测（不依赖 Vue 响应式）。
//
// 口径必须与总览页「待处理」一致（app/utils/overview_task_stats.py）：
//   - 任务存在分享失效标记 shareurl_ban（或总览接口返回的 failed_tasks 映射）
//   - 且转存尚未完成（电影有任一转存记录即完成；剧集转存数达总集数才完成）
//   - 网络/服务端临时错误不计入（可恢复，下个周期会自动重试）
// 这样「待处理」角标上的数字与筛选结果完全相同。

export const FAILED_TASK_FILTER_VALUE = 'failed';

// 可恢复错误：与 overview_task_stats.is_recoverable_share_error 保持同一口径
export const RECOVERABLE_SHARE_ERROR_TERMS = [
  'inner error',
  'request error',
  '网络错误',
  '服务端错误',
  '临时错误'
];

// 已知失效文案（格式化后）：命中即视为需要用户处理的失效链接
export const KNOWN_FORMATTED_BANS = [
  '该分享已失效，不可访问',
  '该分享已过期，无法访问',
  '该分享已被删除，无法访问',
  '该分享已被取消，无法访问',
  '分享不存在'
];

// 原始报错关键词（未格式化时需要映射为上述文案）
export const RAW_BAN_TERMS = [
  '分享者用户封禁链接查看受限',
  '文件涉及违规内容',
  '分享地址已失效',
  '分享地址已过期',
  '文件不存在',
  '好友已取消了分享',
  '文件已被分享者删除',
  '文件夹为空'
];

export function isRecoverableShareError(message) {
  if (!message) return false;
  const text = String(message);
  return RECOVERABLE_SHARE_ERROR_TERMS.some(term => text.includes(term));
}

export function isShareBanMessage(message) {
  if (!message) return false;
  const text = String(message).trim();
  if (!text) return false;
  if (isRecoverableShareError(text)) return false;
  if (KNOWN_FORMATTED_BANS.some(term => text === term || text.includes(term))) return true;
  return RAW_BAN_TERMS.some(term => text.includes(term));
}

export function taskDisplayName(task) {
  if (!task) return '';
  return String(task.taskname || task.task_name || '').trim();
}

export function isMovieTask(task, calendarTask) {
  if (!task) return false;
  const match = (task.calendar_info && task.calendar_info.match) || task.match || {};
  if (match.media_type === 'movie') return true;
  let contentType = task.content_type
    || (task.calendar_info && task.calendar_info.extracted && task.calendar_info.extracted.content_type)
    || '';
  if (!contentType && calendarTask) {
    if (calendarTask.match && calendarTask.match.media_type === 'movie') return true;
    contentType = calendarTask.content_type || '';
  }
  if (contentType === 'movie') return true;
  if (!contentType || contentType === 'other') {
    // 未配置类型时退回路径猜测，与前端 isMovieTask 口径一致
    const pathLower = String(task.savepath || '').toLowerCase();
    return ['电影', '影片', 'movie', 'film'].some(keyword => pathLower.includes(keyword));
  }
  return false;
}

export function normalizeSeasonCounts(counts) {
  if (!counts) return null;
  const num = v => {
    const n = Number(v);
    return Number.isFinite(n) ? n : 0;
  };
  const total = num(counts.total !== undefined ? counts.total : counts.total_count);
  const transferred = num(
    counts.transferred !== undefined ? counts.transferred : counts.transferred_count
  );
  return { total, transferred };
}

export function isTaskTransferComplete(task, calendarTask, seasonCounts) {
  if (!task) return false;
  if (isMovieTask(task, calendarTask)) {
    return !!seasonCounts && seasonCounts.transferred >= 1;
  }
  return !!seasonCounts && seasonCounts.total > 0 && seasonCounts.transferred >= seasonCounts.total;
}

/**
 * 判定单个任务是否「分享失效且待用户处理」。
 * @param {object} task 任务配置
 * @param {object} options
 * @param {string} options.banMessage 分享失效文案（可选，默认取 task.shareurl_ban）
 * @param {object} options.calendarTask 日历任务（可选，用于类型/集数）
 * @param {object} options.seasonCounts 已归一化的 {total, transferred}（可选）
 */
export function isTaskShareBanPending(task, options) {
  try {
    const opts = options || {};
    if (!task) return false;
    if (!taskDisplayName(task)) return false;
    const ban = opts.banMessage !== undefined ? opts.banMessage : task.shareurl_ban;
    if (!isShareBanMessage(ban)) return false;
    const counts = opts.seasonCounts !== undefined
      ? opts.seasonCounts
      : normalizeSeasonCounts(task.season_counts);
    return !isTaskTransferComplete(task, opts.calendarTask, counts);
  } catch (e) {
    return false;
  }
}

/**
 * 按任务名归集「待处理」任务名，供筛选与角标使用。
 * @param {Array} tasklist 任务列表
 * @param {object} options
 * @param {object} options.banByTaskName 任务名 -> 失效文案（来自总览接口 failed_tasks）
 * @param {object} options.seasonCountsByTaskName 任务名 -> 已归一化集数
 * @param {function} options.getCalendarTask 任务名 -> 日历任务
 * @returns {{names: Set<string>, count: number}}
 */
export function collectFailedTaskNames(tasklist, options) {
  const opts = options || {};
  const banByTaskName = opts.banByTaskName || {};
  const seasonCountsByTaskName = opts.seasonCountsByTaskName || {};
  const getCalendarTask = typeof opts.getCalendarTask === 'function' ? opts.getCalendarTask : () => null;
  const names = new Set();
  (Array.isArray(tasklist) ? tasklist : []).forEach(task => {
    const name = taskDisplayName(task);
    if (!name) return;
    const banMessage = Object.prototype.hasOwnProperty.call(banByTaskName, name)
      ? banByTaskName[name]
      : task.shareurl_ban;
    const calendarTask = getCalendarTask(name) || null;
    const counts = Object.prototype.hasOwnProperty.call(seasonCountsByTaskName, name)
      ? seasonCountsByTaskName[name]
      : normalizeSeasonCounts(task.season_counts);
    if (isTaskShareBanPending(task, { banMessage, calendarTask, seasonCounts: counts })) {
      names.add(name);
    }
  });
  return { names, count: names.size };
}
