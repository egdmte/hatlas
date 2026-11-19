/* Shared by every Hatlas page: a short message at the bottom ("toast"), and "Yakında" for anything
   marked data-soon (parts that aren't built yet). window.hatlasToast(text) shows a message. */
(function () {
  'use strict';
  let box = null;
  let timer = 0;
  function toast(text) {
    if (!box) {
      box = document.createElement('div');
      box.className = 'fixed bottom-8 left-1/2 z-50 -translate-x-1/2 rounded-lg border border-line bg-raised px-4 py-2.5 text-[15px] text-ink-2';
      box.setAttribute('role', 'status');
      box.setAttribute('aria-live', 'polite');
      document.body.append(box);
    }
    box.textContent = text;
    box.hidden = false;
    clearTimeout(timer);
    timer = setTimeout(() => { box.hidden = true; }, 2200);
  }
  window.hatlasToast = toast;
  document.addEventListener('click', (e) => {
    const soon = e.target.closest('[data-soon]');
    if (soon) { e.preventDefault(); toast(window.hatlasCopy ? window.hatlasCopy.t('common.soon') : '…'); }
  });
})();
