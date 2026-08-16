// 夸克分享链接路径解析。独立模块便于单测，避免 Vue 3 严格模式下 match 失败抛错卸掉整页。

export function resolveShareurl(shareurl, path = {}) {
  const url = shareurl == null ? '' : String(shareurl);
  if (!url) return '';

  const fid = path && path.fid;
  const isRoot = fid == null || fid === '' || fid == 0 || String(fid) === '0';
  if (isRoot) {
    const match = url.match(/.*s\/[a-zA-Z0-9]+/);
    return match ? match[0] : url;
  }

  const fidStr = String(fid);
  if (url.includes(fidStr)) {
    const match = url.match(new RegExp(`.*/${fidStr}[^/]*`));
    return match ? match[0] : url;
  }
  if (url.includes('#/list/share')) {
    return `${url}/${fidStr}-${path.name || ''}`;
  }
  return `${url}#/list/share/${fidStr}-${path.name || ''}`;
}

export function formatSuggestionShareId(shareurl) {
  const url = shareurl == null ? '' : String(shareurl);
  return url.replace(/^https?:\/\/pan\.(quark|qoark)\.cn\/s\//i, '').split('#')[0];
}
