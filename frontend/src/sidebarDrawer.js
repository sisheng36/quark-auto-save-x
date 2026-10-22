// 移动端侧边栏抽屉：左缘箭头手柄 + 触摸手势。
// 点击开合由模板上的 Bootstrap data-api 负责；本模块只做状态同步、
// 把手柄贴到抽屉右缘，以及识别“右滑展开 / 左滑收起”。

const MOBILE_MEDIA_QUERY = '(max-width: 767.98px)';
const AXIS_LOCK_PX = 8;
const SWIPE_THRESHOLD_PX = 42;
const CLICK_SUPPRESS_MS = 500;

export function initSidebarDrawer() {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return () => {};
  }

  const sidebar = document.getElementById('sidebarMenu');
  const handle = document.querySelector('.mobile-sidebar-toggle');
  if (!sidebar || !handle) {
    return () => {};
  }

  const $ = window.jQuery || window.$;
  const hasJQuery = typeof $ === 'function';
  const mobileQuery = typeof window.matchMedia === 'function'
    ? window.matchMedia(MOBILE_MEDIA_QUERY)
    : null;

  let open = sidebar.classList.contains('show');
  let suppressClick = false;
  let suppressTimer = 0;
  let gesture = null;

  function isMobile() {
    if (mobileQuery) return mobileQuery.matches;
    return window.innerWidth <= 767.98;
  }

  function syncState(nextOpen) {
    open = Boolean(nextOpen);
    handle.classList.toggle('is-open', open);
    handle.setAttribute('aria-label', open ? '收起侧边栏菜单' : '展开侧边栏菜单');
  }

  function isTransitioning() {
    return sidebar.classList.contains('collapsing');
  }

  function openDrawer() {
    if (!isMobile() || open || isTransitioning()) return;
    if (hasJQuery && typeof $(sidebar).collapse === 'function') {
      $(sidebar).collapse('show');
      return;
    }
    handle.click();
  }

  function closeDrawer() {
    if (!isMobile() || !open || isTransitioning()) return;
    if (hasJQuery && typeof $(sidebar).collapse === 'function') {
      $(sidebar).collapse('hide');
      return;
    }
    handle.click();
  }

  // Bootstrap 的打开阶段只有 .collapsing、没有 .show；在 show.bs 时给抽屉
  // 加上 .is-opening，让 CSS 立刻从 -105% 滑向 0，而不是等 .show 出现后再滑。
  function onShow() {
    sidebar.classList.add('is-opening');
    syncState(true);
  }
  function onShown() {
    sidebar.classList.remove('is-opening');
    syncState(true);
  }
  function onHide() {
    sidebar.classList.remove('is-opening');
    syncState(false);
  }
  function onHidden() {
    sidebar.classList.remove('is-opening');
    syncState(false);
  }

  if (hasJQuery && typeof $(sidebar).on === 'function') {
    $(sidebar)
      .on('show.bs.collapse.qasDrawer', onShow)
      .on('shown.bs.collapse.qasDrawer', onShown)
      .on('hide.bs.collapse.qasDrawer', onHide)
      .on('hidden.bs.collapse.qasDrawer', onHidden);
  }
  // Bootstrap 4 自定义事件依赖 jQuery；没有 jQuery 时只保留 CSS 过渡。

  function markSuppressClick() {
    suppressClick = true;
    clearTimeout(suppressTimer);
    suppressTimer = window.setTimeout(() => {
      suppressClick = false;
      suppressTimer = 0;
    }, CLICK_SUPPRESS_MS);
  }

  function resetSuppressClick() {
    suppressClick = false;
    if (suppressTimer) {
      clearTimeout(suppressTimer);
      suppressTimer = 0;
    }
  }

  // 滑动手势结束后浏览器仍可能补发一次 click；在捕获阶段吞掉它，
  // 避免“滑开抽屉后又被 click 关回去”或误触导航链接。
  function onSuppressClick(event) {
    if (!suppressClick) return;
    suppressClick = false;
    event.preventDefault();
    event.stopPropagation();
  }

  function beginGesture(target, event) {
    if (!isMobile() || event.touches.length !== 1) return;
    if (target === 'sidebar' && !open) return;
    resetSuppressClick();
    const touch = event.touches[0];
    gesture = {
      target,
      startX: touch.clientX,
      startY: touch.clientY,
      lastX: touch.clientX,
      lastY: touch.clientY,
      axis: null
    };
  }

  function moveGesture(event) {
    if (!gesture || event.touches.length !== 1) return;
    const touch = event.touches[0];
    const dx = touch.clientX - gesture.startX;
    const dy = touch.clientY - gesture.startY;
    if (gesture.axis === null) {
      if (Math.abs(dx) < AXIS_LOCK_PX && Math.abs(dy) < AXIS_LOCK_PX) return;
      if (Math.abs(dx) > Math.abs(dy) * 1.15) {
        gesture.axis = 'x';
      } else {
        gesture.axis = 'y';
        return;
      }
    }
    if (gesture.axis !== 'x') return;
    gesture.lastX = touch.clientX;
    gesture.lastY = touch.clientY;
    if (event.cancelable) event.preventDefault();
  }

  function endGesture(event) {
    if (!gesture) return;
    const current = gesture;
    gesture = null;

    const touch = event.changedTouches && event.changedTouches[0];
    const endX = touch ? touch.clientX : current.lastX;
    const endY = touch ? touch.clientY : current.lastY;
    const dx = endX - current.startX;
    const dy = endY - current.startY;

    // 快速轻扫可能来不及触发 touchmove，这里用起止点再判定一次方向。
    if (current.axis === null) {
      if (Math.abs(dx) < SWIPE_THRESHOLD_PX || Math.abs(dx) <= Math.abs(dy) * 1.15) {
        return;
      }
      current.axis = 'x';
    }
    if (current.axis !== 'x') return;

    if (event.cancelable) event.preventDefault();
    markSuppressClick();
    if (Math.abs(dx) < SWIPE_THRESHOLD_PX) return;

    if (dx > 0) {
      // 手柄上向右滑：展开；抽屉面板上向右滑不做任何事。
      if (current.target === 'handle') openDrawer();
    } else {
      closeDrawer();
    }
  }

  function cancelGesture() {
    gesture = null;
  }

  function onHandleTouchStart(event) { beginGesture('handle', event); }
  function onHandleTouchMove(event) { moveGesture(event); }
  function onHandleTouchEnd(event) { endGesture(event); }
  function onSidebarTouchStart(event) { beginGesture('sidebar', event); }

  handle.addEventListener('touchstart', onHandleTouchStart, { passive: true });
  handle.addEventListener('touchmove', onHandleTouchMove, { passive: false });
  handle.addEventListener('touchend', onHandleTouchEnd, { passive: false });
  handle.addEventListener('touchcancel', cancelGesture, { passive: true });
  sidebar.addEventListener('touchstart', onSidebarTouchStart, { passive: true });
  sidebar.addEventListener('touchmove', onHandleTouchMove, { passive: false });
  sidebar.addEventListener('touchend', onHandleTouchEnd, { passive: false });
  sidebar.addEventListener('touchcancel', cancelGesture, { passive: true });
  handle.addEventListener('click', onSuppressClick, true);
  sidebar.addEventListener('click', onSuppressClick, true);

  syncState(open);

  return function cleanup() {
    clearTimeout(suppressTimer);
    suppressTimer = 0;
    gesture = null;
    if (hasJQuery && typeof $(sidebar).off === 'function') {
      $(sidebar).off('.qasDrawer');
    }
    handle.removeEventListener('touchstart', onHandleTouchStart);
    handle.removeEventListener('touchmove', onHandleTouchMove);
    handle.removeEventListener('touchend', onHandleTouchEnd);
    handle.removeEventListener('touchcancel', cancelGesture);
    sidebar.removeEventListener('touchstart', onSidebarTouchStart);
    sidebar.removeEventListener('touchmove', onHandleTouchMove);
    sidebar.removeEventListener('touchend', onHandleTouchEnd);
    sidebar.removeEventListener('touchcancel', cancelGesture);
    handle.removeEventListener('click', onSuppressClick, true);
    sidebar.removeEventListener('click', onSuppressClick, true);
    handle.classList.remove('is-open');
    sidebar.classList.remove('is-opening');
  };
}
