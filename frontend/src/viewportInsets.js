const MAX_BROWSER_BOTTOM_INSET = 160;
const NON_TEXT_INPUT_TYPES = new Set(['button', 'checkbox', 'color', 'file', 'image', 'radio', 'reset', 'submit']);

function isEditingText(element) {
  if (!element) return false;
  if (element.isContentEditable) return true;

  const tagName = String(element.tagName || '').toLowerCase();
  if (tagName === 'textarea' || tagName === 'select') return true;
  return tagName === 'input' && !NON_TEXT_INPUT_TYPES.has(String(element.type || 'text').toLowerCase());
}

function isStandalone(win) {
  try {
    return Boolean(
      win.navigator.standalone ||
      win.matchMedia('(display-mode: standalone)').matches ||
      win.matchMedia('(display-mode: fullscreen)').matches
    );
  } catch (error) {
    return false;
  }
}

export function installViewportBottomInset(win = window, doc = document) {
  const viewport = win.visualViewport;
  if (!viewport) return () => {};

  const root = doc.documentElement;
  let previousInset = null;
  const update = () => {
    const scale = Number(viewport.scale) || 1;
    const rawInset = win.innerHeight - viewport.offsetTop - viewport.height;
    const inset = isStandalone(win) || Math.abs(scale - 1) > 0.02 || isEditingText(doc.activeElement) ||
      rawInset <= 0 || rawInset > MAX_BROWSER_BOTTOM_INSET
      ? 0
      : Math.round(rawInset);

    if (inset === previousInset) return;
    previousInset = inset;
    root.style.setProperty('--browser-bottom-inset', `${inset}px`);
  };

  viewport.addEventListener('resize', update, { passive: true });
  viewport.addEventListener('scroll', update, { passive: true });
  win.addEventListener('resize', update, { passive: true });
  doc.addEventListener('focusin', update);
  doc.addEventListener('focusout', update);
  update();

  return () => {
    viewport.removeEventListener('resize', update);
    viewport.removeEventListener('scroll', update);
    win.removeEventListener('resize', update);
    doc.removeEventListener('focusin', update);
    doc.removeEventListener('focusout', update);
  };
}
