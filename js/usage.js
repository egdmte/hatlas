/* Opt-in usage statistics (user, 2026-11-19; the "Hatlas’ı iyileştirmemize yardımcı ol." card from the first
   Figma main page). Loaded on every page.

   Nothing is sent until the visitor taps "İzin ver" on the main page's card (or turns it on in gizlilik.html).
   The choice is kept in this browser only (localStorage "hatlas.usage": "yes", "no" or "later:<ms>").
   "Daha sonra" asks again after LATER_DAYS. A browser that sends Global Privacy Control is never asked and never counted.

   What is sent (POST api/usage, one small JSON per event, no token, no cookie, no id):
     view          which page was opened, and which city / operator / line / stop it shows
     map           a city, operator, line or stop picked on the main page's map
     download      a data file opened from the site (data/*.json, *.geojson)
     search_empty  a search on the main page that found nothing (what was typed, once typing stops)
     nearby        "Yakınımdaki hatlar" was used (never the location)
   The API checks each one against the site's own data and only adds one to a count for that day
   (api/hatlas_api.py, post_usage). window.hatlasUsage.track(event, fields) is used by js/app.js. */
(function () {
  'use strict';

  const KEY = 'hatlas.usage';
  const LATER_DAYS = 30;
  const GPC = navigator.globalPrivacyControl === true;
  const PAGES = {
    '': 'home', 'index.html': 'home', 'sehir.html': 'city', 'isletme.html': 'operator', 'hat.html': 'line',
    'durak.html': 'stop', 'katalog.html': 'catalog', 'sorunlar.html': 'issues', 'dogrula.html': 'verify',
    'katki.html': 'contribute', 'gizlilik.html': 'privacy', 'fotograf-kurallari.html': 'photo-rules',
  };
  const PAGE = PAGES[location.pathname.split('/').pop()] || null;
  // The words are in copy/tr.toml [usage]; js/copy.js may be missing on a page that forgot it, so never fail here.
  const t = (key) => (window.hatlasCopy ? window.hatlasCopy.t(key) : '');

  function choice() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function remember(v) { try { localStorage.setItem(KEY, v); } catch (e) { /* private mode: asked again next time */ } }
  // With Global Privacy Control the card never asks; only an explicit "on" on gizlilik.html counts (copy: usage.state_gpc)
  const allowed = () => choice() === 'yes';

  function send(event, fields) {
    if (!allowed() || !PAGE) return;
    const body = JSON.stringify({ event, page: PAGE, ...fields });
    try {
      fetch('api/usage', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body,
        keepalive: true, cache: 'no-store', credentials: 'omit' }).catch(() => {});
    } catch (e) { /* never in the visitor's way */ }
  }

  // What the page itself shows, from its address (the same parameters js/pages.js reads).
  function pageView() {
    const p = new URLSearchParams(location.search);
    if (PAGE === 'city') return { city: p.get('id'), kind: 'city' };
    if (PAGE === 'operator') return { city: p.get('sehir'), kind: 'operator', target: p.get('id') };
    if (PAGE === 'line') return { city: p.get('sehir'), kind: 'line', target: `${p.get('isletmeci')}|${p.get('hat')}` };
    if (PAGE === 'stop') return { city: p.get('sehir'), kind: 'stop', target: p.get('id') };
    return {};
  }
  let viewed = false;
  function countView() {
    if (viewed || !allowed()) return;
    viewed = true;
    send('view', pageView());
  }

  // Downloads: any link to one of the site's data files.
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]');
    if (!a) return;
    let u;
    try { u = new URL(a.href, location.href); } catch (err) { return; }
    const m = u.origin === location.origin && u.pathname.match(/\/data\/([a-z0-9-]+\.(?:geojson|json))$/);
    if (m) send('download', { kind: 'file', target: m[1] });
  });

  /* ---------- The card on the main page, and the switch on gizlilik.html ---------- */
  function setUp() {
    const card = document.getElementById('usageCard');
    if (card && !GPC) {
      const c = choice();
      const later = c && c.startsWith('later:') ? Number(c.slice(6)) : 0;
      card.hidden = !(c === null || (later && Date.now() - later > LATER_DAYS * 86400000));
      document.getElementById('usageAllow').addEventListener('click', () => {
        remember('yes');
        card.hidden = true;
        countView();
        if (window.hatlasToast) window.hatlasToast(t('usage.thanks'));
      });
      document.getElementById('usageLater').addEventListener('click', () => {
        remember(`later:${Date.now()}`);
        card.hidden = true;
      });
    }

    const sw = document.getElementById('usageSwitch');
    if (sw) {
      const state = document.getElementById('usageState');
      const show = () => {
        const on = allowed();
        sw.setAttribute('aria-checked', String(on));
        state.textContent = on ? t('usage.state_on') : GPC ? t('usage.state_gpc') : t('usage.state_off');
      };
      sw.addEventListener('click', () => { remember(allowed() ? 'no' : 'yes'); show(); countView(); });
      show();
    }
    countView();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', setUp);
  else setUp();

  window.hatlasUsage = { track: send, allowed };
})();
