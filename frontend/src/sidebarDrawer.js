// 移动端侧边栏抽屉：左缘箭头手柄 + 触摸手势。
// 点击开合由模板上的 Bootstrap data-api 负责；本模块只做状态同步、
// 把手柄贴到抽屉右缘、识别“右滑展开 / 左滑收起”，以及手柄拖拽跟手：
// 轴锁定后抽屉与手柄的内联 transform 逐帧跟随手指，松手按位置与速度
// 吸附到开或关，动画从中途位置无缝续接到 Bootstrap collapse 的终态。

const MOBILE_MEDIA_QUERY = '(max-width: 767.98px)';
const AXIS_LOCK_PX = 8;
const SWIPE_THRESHOLD_PX = 42;
const CLICK_SUPPRESS_MS = 500;
const FLICK_VELOCITY_PX_PER_MS = 0.55;

export function initSidebarDrawer() {
  if (typeof document === 'undefined' || typeof window === 'undefined') {
    return () => {};
  }

  const sidebar = document.getElementById('sidebarMenu');
  const handle = document.querySelector('.mobile-sidebar-toggle');
  const backdrop = document.querySelector('.sidebar-backdrop');
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
  let drag = null;

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
  // 加上 .is-opening，让 CSS 立刻从 -100% 滑向 0，而不是等 .show 出现后再滑。
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

  /* ---------- 手柄拖拽跟手 ---------- */

  // 抽屉与手柄共用同一行程 W（= min(78vw, 300px)）：抽屉从 -W 滑到 0，
  // 手柄从 -1px 滑到 W-1px，与 CSS 类定义的终态严格一致，松手清内联后
  // 过渡能精确接续。遮罩透明度随展开比例渐显。
  function applyDrag(fraction) {
    const x = fraction * drag.width - 1;
    sidebar.style.transform = 'translateX(' + ((fraction - 1) * drag.width).toFixed(2) + 'px)';
    handle.style.transform = 'translate3d(' + x.toFixed(2) + 'px, -50%, 0)';
    if (backdrop) backdrop.style.opacity = fraction.toFixed(3);
  }

  function startDrag(startX) {
    // Bootstrap 动画进行中不接管：open 标记与实际视觉位置对不上，
    // 退回“松手看总位移”的阈值手势（与旧版行为一致）。
    if (isTransitioning()) return;
    const width = sidebar.getBoundingClientRect().width;
    if (!(width > 0)) return;
    drag = {
      width,
      fromOpen: open,
      fraction: open ? 1 : 0,
      startX,
      lastX: startX,
      lastT: 0,
      velocity: 0
    };
    // 先把内联样式钉在当前视觉位置、再加类关过渡；顺序反了的话，
    // 关过渡的那一次 recalc 会直接跳到类定义的终态。
    applyDrag(drag.fraction);
    sidebar.classList.add('is-dragging');
    handle.classList.add('is-dragging');
  }

  function updateDrag(x, timeStamp) {
    const base = drag.fromOpen ? 1 : 0;
    drag.fraction = Math.max(0, Math.min(1, base + (x - drag.startX) / drag.width));
    // 合成事件里相邻 timeStamp 可能相同，只在时间前进时刷新速度
    if (drag.lastT && timeStamp > drag.lastT) {
      drag.velocity = (x - drag.lastX) / (timeStamp - drag.lastT);
    }
    drag.lastX = x;
    drag.lastT = timeStamp;
    applyDrag(drag.fraction);
  }

  function clearDragStyles() {
    sidebar.classList.remove('is-dragging');
    handle.classList.remove('is-dragging');
    sidebar.style.transform = '';
    handle.style.transform = '';
    if (backdrop) backdrop.style.opacity = '';
  }

  // 松手吸附：过半程、或朝该方向快速轻扫，就吸附过去；否则弹回。
  // 释放顺序是关键——同一同步任务内：先摘 is-dragging（恢复过渡，
  // Bootstrap 读过渡时长也正确）→ 再走 collapse show/hide（类变更与
  // show/hide.bs 事件全部同步完成，手柄 is-open 即刻就位）→ 最后清内联。
  // 浏览器只做一次 recalc，过渡便从拖拽位置平滑续接到终态。
  function endDrag() {
    const current = drag;
    drag = null;
    const wantOpen = (current.fraction >= 0.5 && current.velocity > -FLICK_VELOCITY_PX_PER_MS)
      || current.velocity > FLICK_VELOCITY_PX_PER_MS;
    sidebar.classList.remove('is-dragging');
    handle.classList.remove('is-dragging');
    if (wantOpen !== current.fromOpen) {
      if (wantOpen) openDrawer();
      else closeDrawer();
    }
    sidebar.style.transform = '';
    handle.style.transform = '';
    if (backdrop) backdrop.style.opacity = '';
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
    // 手柄：轴锁定后进入跟手拖拽（isTransitioning 时 startDrag 自行让位）
    if (gesture.target === 'handle' && !drag) startDrag(gesture.startX);
    if (drag && gesture.target === 'handle') updateDrag(touch.clientX, event.timeStamp);
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

    // 手柄跟手路径：按松手时的位置与速度吸附，不看总位移阈值
    // （拖过半程再拽回来的场景，总位移会误判方向）。
    if (drag && current.target === 'handle') {
      endDrag();
      return;
    }

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
    if (drag) {
      drag = null;
      // 来电/系统手势抢占等中断：带过渡弹回当前状态
      clearDragStyles();
    }
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
    drag = null;
    clearDragStyles();
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
