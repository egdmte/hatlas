/* Hatlas contributions on the site (api/hatlas_api.py behind /api/): the temporary name, the forms on stop and
   line pages, and what the community confirmed. Used by js/pages.js (durak, hat, dogrula and sorunlar.html).

   No account: the first suggestion or vote asks the API for a temporary name ("~2026-48213") and a random token,
   kept in this browser (localStorage) and sent as X-Hatlas-Token; no cookies. A suggestion goes live once three
   people on different connections say "doğru" (user, 2026-11-18).
   Everything from the API is put on the page as text; links from reports are https only and open with
   rel="noopener nofollow ugc". The words are in copy/tr.toml ([suggest] and [verify]).
   "Güncelle" (2026-11-19): a stop that was removed, a line's new route drawn on the page's map, a new stop placed on a
   city's map. pages.js hands over its map with setMap(); drawings are kept as [lon, lat] rounded to ~1 m. */
(function () {
  'use strict';

  const { t } = window.hatlasCopy;
  const API = 'api';
  const KEY = 'hatlas.contributor';

  /* ---------- Helpers (same look as js/pages.js) ---------- */
  function el(tag, cls, ...kids) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    for (const k of kids) if (k != null && k !== false) e.append(k);
    return e;
  }
  function link(href, cls, ...kids) {
    const a = el('a', cls, ...kids);
    a.href = href;
    return a;
  }
  const BTN = 'inline-flex h-10 items-center justify-center rounded-lg px-4 text-sm font-semibold aria-pressed:ring-2 aria-pressed:ring-link';
  const PRIMARY = `${BTN} bg-accent text-white hover:bg-accent-hover disabled:bg-overlay disabled:text-ink-3`;
  const SOFT = `${BTN} bg-soft text-soft-ink hover:bg-[#16306e]`;
  const FIELD = 'rounded-lg border border-line bg-base px-3.5 text-ink placeholder:text-ink-3 focus:border-link focus:outline-none';
  const FORM = 'flex flex-col gap-4 rounded-lg bg-overlay p-5';
  // A section of the side panel, as sec() in js/pages.js
  const SEC = 'mx-6 md:mx-8';
  const H2 = 'text-xl';
  const MONTHS = t('common.months').split(',').map((m) => m.trim());
  const day = (iso) => (iso ? `${Number(iso.slice(8, 10))} ${MONTHS[Number(iso.slice(5, 7)) - 1]} ${iso.slice(0, 4)}` : '');
  // "20 Kasım 14:05", in the visitor's own time
  const whenText = (iso) => new Date(iso).toLocaleString('tr-TR', { day: 'numeric', month: 'long', hour: '2-digit', minute: '2-digit' });

  const FACTS = [
    ['staff', t('suggest.fact_staff'), 'staff.svg'], ['stepfree', t('suggest.fact_stepfree'), 'elevator.svg'],
    ['sidewalk', t('suggest.fact_sidewalk'), 'sidewalk.svg'], ['shelter', t('suggest.fact_shelter'), 'shelter.svg'],
  ];
  const FACT_VALUE = { yes: t('suggest.fact_yes'), no: t('suggest.fact_no') };
  const factText = (fact, value) => t('suggest.fact_value', { fact, value });
  const REPORT_TYPES = [['works', t('suggest.report_works')], ['announcement', t('suggest.report_announcement')],
    ['not_running', t('suggest.report_not_running')], ['other', t('suggest.report_other')]];
  const reportType = (x) => (REPORT_TYPES.find(([k]) => k === x) || [x, t('suggest.report_fallback')])[1];
  const UPDATE = { removed: t('suggest.update_removed'), route: t('suggest.update_route'), newstop: t('suggest.update_newstop') };
  const ORANGE = '#f5a524';   // the community's drawings on the map (proposals and published changes)
  const agencyOf = (opId) => opId.slice(opId.indexOf('-') + 1);
  const fold = (x) => x.replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase();
  const ERRORS = {
    'slow down': t('suggest.error_slow'),
    'too many suggestions today': t('suggest.error_suggestions'),
    'too many votes today': t('suggest.error_votes'),
    'not on your own suggestion': t('suggest.error_own'),
    'not open': t('suggest.error_closed'),
  };
  const say = (e) => ERRORS[e && e.message] || t('suggest.error');

  /* ---------- The API ---------- */
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY) || 'null'); } catch (e) { return null; } },
    set(v) { try { localStorage.setItem(KEY, JSON.stringify(v)); } catch (e) { /* private mode: name lasts this page only */ } },
  };
  let me = store.get();

  async function call(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (me && me.token) headers['X-Hatlas-Token'] = me.token;
    const r = await fetch(`${API}/${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: 'no-store' });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || String(r.status));
    return data;
  }
  async function hello() {
    if (me && me.token) return me;
    const r = await call('POST', 'hello', {});
    me = { name: r.name, token: r.token };
    store.set(me);
    return me;
  }
  const api = {
    me: () => me,
    hello,
    stop: (city, id) => call('GET', `stop/${encodeURIComponent(city)}/${encodeURIComponent(id)}`),
    line: (city, key) => call('GET', `line/${encodeURIComponent(city)}/${encodeURIComponent(key)}`),
    open: (params) => call('GET', `open?${new URLSearchParams(params)}`),
    mine: () => call('GET', 'mine'),
    reports: (params) => call('GET', `reports?${new URLSearchParams(params || {})}`),
    city: (city) => call('GET', `city/${encodeURIComponent(city)}`),
    suggestion: (id) => call('GET', `suggestion/${encodeURIComponent(id)}`),
    async suggest(s) { await hello(); return call('POST', 'suggest', s); },
    async vote(id, vote) { await hello(); return call('POST', `vote/${id}`, { vote }); },
    withdraw: (id) => call('POST', `withdraw/${id}`, {}),
  };

  /* ---------- Pieces ---------- */
  function consent() {
    return el('p', 'text-xs leading-relaxed text-ink-3',
      t('suggest.consent_before'), me ? t('suggest.consent_named', { name: me.name }) : t('suggest.consent_new'), t('suggest.consent_after'),
      link('gizlilik.html', 'text-link hover:underline', t('suggest.what_we_keep')));
  }
  function done(box, text) {
    box.textContent = '';
    box.append(el('div', 'flex flex-col gap-2 rounded-lg bg-soft p-5 text-sm text-soft-ink',
      el('strong', 'text-ink', t('suggest.received')), text,
      link('dogrula.html', 'w-fit font-medium text-link hover:underline', t('suggest.see_others'))));
  }
  function failed(box, e) {
    let p = box.querySelector('[data-error]');
    if (!p) { p = el('p', 'text-sm text-crit'); p.dataset.error = ''; box.append(p); }
    p.textContent = say(e);
  }
  // A message under a form (a check that failed before sending)
  function problem(form, text) {
    failed(form, {});
    form.querySelector('[data-error]').textContent = text;
  }
  function safeUrl(u) {
    try { const x = new URL(u); return x.protocol === 'https:' ? x.href : null; } catch (e) { return null; }
  }
  function sourceLink(src) {
    const s = src && safeUrl(src);
    const a = s ? link(s, 'text-link hover:underline', t('suggest.source')) : null;
    if (a) { a.target = '_blank'; a.rel = 'noopener nofollow ugc'; }
    return a;
  }
  function reportItem(r) {
    const a = sourceLink(r.source);
    return el('li', 'flex flex-col gap-1.5 py-4',
      el('span', 'text-xs font-semibold uppercase tracking-wide text-warn', r.kind && r.kind !== 'report' ? UPDATE[r.kind] : reportType(r.type)),
      el('p', null, r.kind === 'newstop' ? `“${r.name}”${r.text ? ` · ${r.text}` : ''}` : r.text),
      el('p', 'text-xs text-ink-3', r.since ? t('suggest.confirmed_on', { date: day(r.since) }) : '', a ? ' · ' : '', a));
  }
  // A small toggle row of buttons; each opens its own form under it (one at a time).
  function toggles(defs) {
    const row = el('div', 'flex flex-wrap gap-2');
    const slot = el('div', 'mt-4');
    for (const [label, make, key] of defs) {
      const b = el('button', SOFT, label);
      b.type = 'button';
      if (key) b.dataset.form = key;
      b.addEventListener('click', () => {
        const open = b.getAttribute('aria-expanded') === 'true';
        for (const x of row.children) x.setAttribute('aria-expanded', 'false');
        if (slot.firstChild) slot.firstChild.dispatchEvent(new Event('closeform'));
        slot.textContent = '';
        if (!open) { b.setAttribute('aria-expanded', 'true'); slot.append(make()); }
      });
      b.setAttribute('aria-expanded', 'false');
      row.append(b);
    }
    return el('div', null, row, slot);
  }

  // Arriving from the map's picking mode (katki.html → Düzenle / Bildir): durak.html#duzenle scrolls to the forms,
  // #bildir also opens the report form. Only the block that is visible (the stop page's open side) reacts.
  // #guncelle opens the page's update form (a line's route, a stop's "Kaldırıldı", a city's new stop).
  function jumpTo(section) {
    const h = location.hash;
    if (h !== '#duzenle' && h !== '#bildir' && h !== '#guncelle') return;
    // After the page has put the block in place (setTimeout, not requestAnimationFrame: that waits while the tab is hidden)
    setTimeout(() => {
      if (!section.offsetParent) return;
      const keys = h === '#bildir' ? ['report'] : h === '#guncelle' ? ['route', 'removed', 'newstop'] : [];
      const b = keys.map((k) => section.querySelector(`[data-form="${k}"]`)).find(Boolean);
      if (b && b.getAttribute('aria-expanded') !== 'true') b.click();
      section.scrollIntoView({ block: 'start' });   // instant: a line page can be thousands of pixels long
    }, 0);
  }

  /* ---------- The page's map (pages.js: setMap) ---------- */
  // Drawings wait for the map's first 'load' (isStyleLoaded() can be false again later while sources load).
  let pageMap = null;
  let mapReady = false;
  const mapQueue = [];
  function setMap(map) {
    pageMap = map;
    if (!map) return;
    map.once('load', () => {
      mapReady = true;
      while (mapQueue.length) mapQueue.shift()(map);
    });
  }
  function withMap(fn) {
    if (mapReady) fn(pageMap); else mapQueue.push(fn);
  }
  const fc = (features) => ({ type: 'FeatureCollection', features });
  const lineF = (pts) => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: pts } });
  const pointF = (p, props) => ({ type: 'Feature', properties: props || {}, geometry: { type: 'Point', coordinates: p } });
  // One drawing on the map (a route and/or points), dashed orange; set again to change it, null to take it off.
  function drawing(id, data) {
    withMap((map) => {
      if (!data) {
        for (const l of [`${id}-line`, `${id}-pt`]) if (map.getLayer(l)) map.removeLayer(l);
        if (map.getSource(id)) map.removeSource(id);
        return;
      }
      if (map.getSource(id)) { map.getSource(id).setData(data); return; }
      // What you are drawing now ('draft'): a solid line and white points with an orange ring, so it stands apart
      // from the confirmed changes and proposals (dashed orange, orange points).
      const draft = id === 'draft';
      map.addSource(id, { type: 'geojson', data });
      map.addLayer({ id: `${id}-line`, type: 'line', source: id, filter: ['==', ['geometry-type'], 'LineString'],
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: draft ? { 'line-color': ORANGE, 'line-width': 3 } : { 'line-color': ORANGE, 'line-width': 4, 'line-dasharray': [1.5, 1.2] } });
      map.addLayer({ id: `${id}-pt`, type: 'circle', source: id, filter: ['==', ['geometry-type'], 'Point'],
        paint: draft ? { 'circle-radius': 6, 'circle-color': '#ffffff', 'circle-stroke-width': 3, 'circle-stroke-color': ORANGE }
          : { 'circle-radius': 5, 'circle-color': ORANGE, 'circle-stroke-width': 2, 'circle-stroke-color': '#ffffff' } });
    });
  }
  function fit(points) {
    withMap((map) => {
      if (points.length === 1) { map.easeTo({ center: points[0], zoom: Math.max(map.getZoom(), 15), duration: 500 }); return; }
      const b = new maplibregl.LngLatBounds(points[0], points[0]);
      for (const p of points) b.extend(p);
      map.fitBounds(b, { padding: 60, maxZoom: 16, duration: 500 });
    });
  }
  // Clicks on the map while a form is open: each click gives [lon, lat] to onPoint. Returns the way to stop.
  function picking(onPoint) {
    let on = true;
    const click = (e) => { if (on) onPoint([Math.round(e.lngLat.lng * 1e5) / 1e5, Math.round(e.lngLat.lat * 1e5) / 1e5]); };
    // Clicks work before the map has loaded, so they don't wait for it (only drawings do)
    const attach = (map) => { if (!on) return; map.on('click', click); map.getCanvas().style.cursor = 'crosshair'; };
    if (pageMap) attach(pageMap); else withMap(attach);
    return () => {
      on = false;
      if (pageMap) { pageMap.off('click', click); pageMap.getCanvas().style.cursor = ''; }
    };
  }
  const mapHint = () => el('p', 'text-sm text-ink-2',
    el('span', 'md:hidden', t('suggest.map_hint_phone')), t('suggest.map_hint'));
  const labelled = (label, field) => el('label', 'flex flex-col gap-2 text-sm', el('span', 'text-ink-2', label), field);
  function textField(label, placeholder, required) {
    const x = el('textarea', `${FIELD} py-2.5`);
    x.rows = 3; x.required = required; x.minLength = required ? 10 : 0; x.maxLength = 500; x.placeholder = placeholder;
    return [x, labelled(label, x)];
  }
  function sourceField() {
    const src = el('input', `${FIELD} h-11`);
    src.type = 'url'; src.placeholder = t('suggest.source_placeholder'); src.maxLength = 300;
    return [src, labelled(t('suggest.source_label'), src)];
  }
  // Text (when given) and an https source, or an error shown on the form (returns null).
  function textAndSource(form, text, src, required) {
    const out = {};
    const x = text.value.trim();
    if (required || x) {
      if (x.length < 10) { problem(form, t('suggest.too_short', { n: 10 })); return null; }
      out.text = x;
    }
    if (src.value.trim()) {
      if (!safeUrl(src.value.trim())) { problem(form, t('suggest.https_only')); return null; }
      out.source = src.value.trim();
    }
    return out;
  }
  const sendButton = () => { const b = el('button', PRIMARY, t('suggest.send')); b.type = 'submit'; return b; };

  // Güncelle on a stop: it was taken away.
  function removedForm(city, sid) {
    const form = el('form', FORM);
    const [text, textLabel] = textField(t('suggest.removed_what'), t('suggest.removed_placeholder'), true);
    const [src, srcLabel] = sourceField();
    const send = sendButton();
    form.append(el('p', 'text-sm text-ink-2', t('suggest.removed_intro')), textLabel, srcLabel, consent(), send);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = textAndSource(form, text, src, true);
      if (!payload) return;
      send.disabled = true;
      try {
        await api.suggest({ kind: 'removed', city: city.id, targetType: 'stop', target: sid, payload });
        done(form, t('suggest.removed_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  // Güncelle on a line: the new route, clicked point by point on the page's map.
  const MAX_POINTS = 300;   // as in api/hatlas_api.py
  function routeForm(city, key) {
    const form = el('form', FORM);
    const pts = [];
    const count = el('p', 'text-sm font-medium');
    const undo = el('button', `${BTN} h-9 bg-base text-ink hover:bg-raised`, t('suggest.undo'));
    const clear = el('button', `${BTN} h-9 text-ink-2 hover:text-ink`, t('suggest.clear'));
    undo.type = 'button'; clear.type = 'button';
    const redraw = () => {
      drawing('draft', fc([...(pts.length > 1 ? [lineF(pts)] : []), ...pts.map((p) => pointF(p))]));
      count.textContent = pts.length ? t('suggest.points', { n: pts.length }) : t('suggest.no_points');
      undo.disabled = clear.disabled = !pts.length;
    };
    const stop = picking((p) => { if (pts.length < MAX_POINTS) { pts.push(p); redraw(); } });
    undo.addEventListener('click', () => { pts.pop(); redraw(); });
    clear.addEventListener('click', () => { pts.length = 0; redraw(); });
    const [text, textLabel] = textField(t('suggest.route_what'), t('suggest.route_placeholder'), true);
    const [src, srcLabel] = sourceField();
    const send = sendButton();
    form.append(
      el('p', 'text-sm text-ink-2', t('suggest.route_intro')),
      mapHint(), count, el('div', 'flex gap-2', undo, clear), textLabel, srcLabel, consent(), send);
    redraw();
    const close = () => { stop(); drawing('draft', null); };
    form.addEventListener('closeform', close);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (pts.length < 2) { problem(form, t('suggest.route_two_points')); return; }
      const payload = textAndSource(form, text, src, true);
      if (!payload) return;
      send.disabled = true;
      try {
        await api.suggest({ kind: 'route', city: city.id, targetType: 'line', target: key, payload: { points: pts.slice(), ...payload } });
        close();
        done(form, t('suggest.route_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  // Güncelle on a city: a stop the feed doesn't have, placed on the city's map.
  function linesFrom(city, textValue) {
    const keys = [];
    const unknown = [];
    for (const n of textValue.split(/[,;\s]+/).filter(Boolean)) {
      const hits = city.lineList.filter((l) => fold(l.line) === fold(n));
      if (!hits.length) unknown.push(n);
      for (const l of hits) keys.push(`${agencyOf(l.operator)}|${l.line}`);
    }
    return { keys: [...new Set(keys)], unknown };
  }
  function newStopForm(city) {
    const form = el('form', FORM);
    let point = null;
    const placeNote = el('p', 'text-sm font-medium', t('suggest.place_none'));
    const stop = picking((p) => {
      point = p;
      drawing('draft', fc([pointF(p)]));
      placeNote.textContent = t('suggest.place_set');
    });
    const name = el('input', `${FIELD} h-11`);
    name.required = true; name.minLength = 2; name.maxLength = 80; name.autocomplete = 'off'; name.placeholder = t('suggest.newstop_name_placeholder');
    const lines = el('input', `${FIELD} h-11`);
    lines.autocomplete = 'off'; lines.placeholder = t('suggest.newstop_lines_placeholder');
    const [text, textLabel] = textField(t('suggest.newstop_note'), t('suggest.newstop_note_placeholder'), false);
    const send = sendButton();
    form.append(
      el('p', 'text-sm text-ink-2', t('suggest.newstop_intro')), mapHint(), placeNote,
      labelled(t('suggest.newstop_name'), name),
      labelled(t('suggest.newstop_lines'), lines),
      textLabel, consent(), send);
    const close = () => { stop(); drawing('draft', null); };
    form.addEventListener('closeform', close);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!point) { problem(form, t('suggest.newstop_place')); return; }
      const l = linesFrom(city, lines.value);
      if (l.unknown.length) { problem(form, t('suggest.newstop_unknown_lines', { lines: l.unknown.join(', ') })); return; }
      if (l.keys.length > 30) { problem(form, t('suggest.newstop_too_many')); return; }
      const extra = textAndSource(form, text, { value: '' }, false);
      if (!extra) return;
      send.disabled = true;
      try {
        await api.suggest({ kind: 'newstop', city: city.id, targetType: 'city', target: city.id,
          payload: { name: name.value, point, lines: l.keys, ...extra } });
        close();
        done(form, t('suggest.newstop_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  // A suggestion opened from "Bu doğru mu?" (?oneri=<id>): drawn on the page's map, with what it says.
  function proposalBox(city) {
    const id = new URLSearchParams(location.search).get('oneri');
    const box = el('section', `${SEC} flex flex-col gap-2 rounded-lg border border-warn/40 bg-warn/10 p-5 text-sm`);
    box.hidden = true;
    if (!id || !/^\d+$/.test(id)) return box;
    api.suggestion(id).then((sg) => {
      if (sg.city !== city.id) return;
      const p = sg.payload;
      const pts = sg.kind === 'route' ? p.points : sg.kind === 'newstop' ? [p.point] : null;
      if (pts) { drawing('proposal', fc([...(pts.length > 1 ? [lineF(pts)] : []), ...pts.map((x) => pointF(x))])); fit(pts); }
      box.append(
        el('strong', 'text-ink', sg.status === 'live' ? t('suggest.proposal_live') : t('suggest.proposal_open')),
        el('p', null, describe(sg)),
        sg.status === 'open' ? link(`dogrula.html?${new URLSearchParams({ sehir: sg.city, hedef: sg.target })}`, 'w-fit font-medium text-link hover:underline', t('suggest.proposal_vote')) : null);
      box.hidden = false;
      box.scrollIntoView({ block: 'start' });   // a line page is long: the voter came for this note
    }).catch(() => {});
    return box;
  }

  /* ---------- Forms ---------- */
  function accessForm(city, sid) {
    const form = el('form', FORM);
    form.append(el('p', 'text-sm text-ink-2', t('suggest.access_intro')));
    for (const [key, name] of FACTS) {
      // The fact's name above its three choices: side by side they don't fit the panel.
      const group = el('fieldset', 'flex flex-wrap items-center gap-x-5 gap-y-1.5 text-sm', el('legend', 'mb-1.5 font-medium', name));
      for (const [value, label] of [['yes', t('suggest.choice_yes')], ['no', t('suggest.choice_no')], ['', t('suggest.choice_unsure')]]) {
        const input = el('input', 'size-4 accent-accent');
        input.type = 'radio'; input.name = key; input.value = value; input.checked = value === '';
        group.append(el('label', 'flex cursor-pointer items-center gap-2', input, label));
      }
      form.append(group);
    }
    const send = sendButton();
    form.append(consent(), send);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const facts = {};
      for (const [key] of FACTS) { const v = form.elements[key].value; if (v) facts[key] = v; }
      if (!Object.keys(facts).length) { problem(form, t('suggest.access_none')); return; }
      send.disabled = true;
      try {
        await api.suggest({ kind: 'access', city: city.id, targetType: 'stop', target: sid, payload: { facts } });
        done(form, t('suggest.access_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  function nameForm(city, sid, current) {
    const form = el('form', FORM);
    const input = el('input', `${FIELD} h-11`);
    input.name = 'name'; input.required = true; input.minLength = 2; input.maxLength = 80; input.value = current || '';
    input.autocomplete = 'off';
    form.append(labelled(t('suggest.name_label'), input));
    const send = sendButton();
    form.append(consent(), send);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (input.value.trim() === (current || '').trim()) { problem(form, t('suggest.name_same')); return; }
      send.disabled = true;
      try {
        await api.suggest({ kind: 'name', city: city.id, targetType: 'stop', target: sid, payload: { name: input.value } });
        done(form, t('suggest.name_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  function reportForm(city, targetType, target) {
    const form = el('form', FORM);
    const type = el('select', `${FIELD} h-11`);
    type.name = 'type';
    for (const [k, label] of REPORT_TYPES) { const o = el('option', null, label); o.value = k; type.append(o); }
    const text = el('textarea', `${FIELD} py-2.5`);
    text.name = 'text'; text.rows = 3; text.required = true; text.minLength = 10; text.maxLength = 500;
    text.placeholder = targetType === 'line' ? t('suggest.report_placeholder_line') : t('suggest.report_placeholder_stop');
    const src = el('input', `${FIELD} h-11`);
    src.name = 'source'; src.type = 'url'; src.placeholder = t('suggest.source_placeholder'); src.maxLength = 300;
    form.append(labelled(t('suggest.report_type'), type), labelled(t('suggest.report_what'), text), labelled(t('suggest.source_label'), src));
    const send = sendButton();
    form.append(consent(), send);
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const payload = { type: type.value, text: text.value };
      if (src.value.trim()) {
        if (!safeUrl(src.value.trim())) { problem(form, t('suggest.https_only')); return; }
        payload.source = src.value.trim();
      }
      send.disabled = true;
      try {
        await api.suggest({ kind: 'report', city: city.id, targetType, target, payload });
        done(form, t('suggest.report_done'));
      } catch (err) { send.disabled = false; failed(form, err); }
    });
    return form;
  }

  /* ---------- Blocks for the pages ---------- */
  const waitingLink = (params) => link(`dogrula.html?${new URLSearchParams(params)}`, 'font-medium text-link hover:underline', t('suggest.verify_link'));
  const listSection = (title, ...kids) => el('section', SEC, el('h2', `mb-2 ${H2}`, title), ...kids);

  // A stop side: accessibility (feed: unknown; the community's answers where confirmed), the confirmed name,
  // reports, how much waits for votes, and the forms. `onName(name)` lets the page show a confirmed name.
  function stopBlock(city, sid, feedName, pill, onName) {
    const pills = el('div', 'grid gap-2.5');
    const drawFacts = (facts) => {
      pills.textContent = '';
      for (const [key, name, icon] of FACTS) {
        const f = facts[key];
        pills.append(f ? pill('ok', factText(name, FACT_VALUE[f.value]), `assets/icons/${icon}`)
          : pill('none', factText(name, t('suggest.fact_unknown')), `assets/icons/${icon}`));
      }
    };
    drawFacts({});
    const factNote = el('p', 'mt-4 text-sm text-ink-3', t('suggest.facts_none'));
    const reports = el('ul', 'divide-y divide-overlay');
    const reportsSec = listSection(t('suggest.reports'), reports);
    reportsSec.hidden = true;
    const waiting = el('p', 'text-sm text-ink-3');
    waiting.hidden = true;
    const forms = el('section', `${SEC} flex scroll-mt-6 flex-col gap-4`,
      el('h2', H2, t('suggest.stop_forms')),
      waiting,
      toggles([
        [t('suggest.button_access'), () => accessForm(city, sid), 'access'],
        [t('suggest.button_name'), () => nameForm(city, sid, feedName), 'name'],
        [t('suggest.button_report'), () => reportForm(city, 'stop', sid), 'report'],
        [t('suggest.button_removed'), () => removedForm(city, sid), 'removed'],
      ]));
    const removed = el('section', `${SEC} flex flex-col gap-2 rounded-lg border border-crit/40 bg-crit/10 p-5 text-sm`);
    removed.hidden = true;
    const out = el('div', 'flex flex-col gap-10',
      removed,
      el('section', SEC, el('h2', `mb-4 ${H2}`, t('suggest.access')), pills, factNote),
      reportsSec,
      forms);
    jumpTo(forms);
    api.stop(city.id, sid).then((v) => {
      if (Object.keys(v.facts).length) { drawFacts(v.facts); factNote.textContent = t('suggest.facts_some'); }
      if (v.name && onName) onName(v.name.value);
      if (v.removed) {
        const a = sourceLink(v.removed.source);
        removed.append(el('strong', 'text-ink', t('suggest.removed_box')), el('p', null, v.removed.text || ''),
          el('p', 'text-xs text-ink-3', t('suggest.confirmed_on', { date: day(v.removed.since) }), a ? ' · ' : '', a));
        removed.hidden = false;
      }
      if (v.reports.length) { reports.append(...v.reports.map(reportItem)); reportsSec.hidden = false; }
      if (v.waiting) {
        waiting.append(t('suggest.stop_waiting', { n: v.waiting }), waitingLink({ sehir: city.id, hedef: sid }));
        waiting.hidden = false;
      }
    }).catch(() => { /* the API is down: the page still shows the feed's data */ });
    return out;
  }

  // A line: confirmed reports and the report form.
  function lineBlock(city, key) {
    const reports = el('ul', 'divide-y divide-overlay');
    const reportsSec = listSection(t('suggest.reports'), reports);
    reportsSec.hidden = true;
    const waiting = el('p', 'text-sm text-ink-3');
    waiting.hidden = true;
    const routes = el('ul', 'divide-y divide-overlay');
    const routesSec = listSection(t('suggest.routes'), el('p', 'text-sm text-ink-3', t('suggest.routes_note')), routes);
    routesSec.hidden = true;
    const prop = proposalBox(city);
    api.line(city.id, key).then((v) => {
      if (v.reports.length) { reports.append(...v.reports.map(reportItem)); reportsSec.hidden = false; }
      if (v.routes && v.routes.length) {
        drawing('routes', fc(v.routes.map((r) => lineF(r.points))));
        for (const r of v.routes) {
          const li = reportItem({ ...r, kind: 'route' });
          const b = el('button', 'w-fit text-sm text-link hover:underline', t('suggest.show_on_map'));
          b.type = 'button';
          b.addEventListener('click', () => fit(r.points));
          li.append(b);
          routes.append(li);
        }
        routesSec.hidden = false;
      }
      if (v.waiting) {
        waiting.append(t('suggest.line_waiting', { n: v.waiting }), waitingLink({ sehir: city.id, hedef: key }));
        waiting.hidden = false;
      }
    }).catch(() => {});
    const forms = el('section', `${SEC} flex scroll-mt-6 flex-col gap-4`, el('h2', H2, t('suggest.line_forms')), waiting,
      toggles([[t('suggest.button_report'), () => reportForm(city, 'line', key), 'report'], [t('suggest.button_route'), () => routeForm(city, key), 'route']]));
    jumpTo(forms);
    return el('div', 'flex flex-col gap-10', prop, routesSec, reportsSec, forms);
  }

  // A city: the stops the community added (list + map), and the new-stop form.
  function cityBlock(city) {
    const list = el('ul', 'divide-y divide-overlay');
    const sec = listSection(t('suggest.new_stops'), el('p', 'text-sm text-ink-3', t('suggest.new_stops_note')), list);
    sec.hidden = true;
    const waitingP = el('p', 'text-sm text-ink-3');
    waitingP.hidden = true;
    const prop = proposalBox(city);
    api.city(city.id).then((v) => {
      if (v.newStops.length) {
        drawing('newstops', fc(v.newStops.map((x) => pointF(x.point))));
        for (const x of v.newStops) {
          const lines = x.lines.map((k) => k.slice(k.indexOf('|') + 1));
          const b = el('button', 'w-fit text-left text-link hover:underline', x.name);
          b.type = 'button';
          b.addEventListener('click', () => fit([x.point]));
          list.append(el('li', 'flex flex-col gap-1 py-4', b,
            el('p', 'text-sm text-ink-3', [lines.length ? lines.join(', ') : t('suggest.no_lines_given'), t('suggest.confirmed_on', { date: day(x.since) })].join(' · ')),
            x.text ? el('p', 'text-sm', x.text) : null));
        }
        sec.hidden = false;
      }
      if (v.waiting) {
        waitingP.append(t('suggest.city_waiting', { n: v.waiting }), waitingLink({ sehir: city.id, hedef: city.id }));
        waitingP.hidden = false;
      }
    }).catch(() => {});
    const forms = el('section', `${SEC} flex scroll-mt-6 flex-col gap-4`, el('h2', H2, t('suggest.city_forms')), waitingP,
      toggles([[t('suggest.button_newstop'), () => newStopForm(city), 'newstop']]));
    jumpTo(forms);
    return el('div', 'flex flex-col gap-10', prop, sec, forms);
  }

  /* ---------- "Bu doğru mu?" (dogrula.html) ---------- */
  function describe(s) {
    const p = s.payload;
    if (s.kind === 'access') return Object.entries(p.facts).map(([k, v]) => factText((FACTS.find(([f]) => f === k) || [k, k])[1], FACT_VALUE[v])).join(' · ');
    if (s.kind === 'name') return t('suggest.describe_name', { name: p.name });
    if (s.kind === 'removed') return t('suggest.describe_removed', { text: p.text });
    if (s.kind === 'route') return t('suggest.describe_route', { n: p.points.length, text: p.text });
    if (s.kind === 'newstop') {
      const lines = (p.lines || []).map((k) => k.slice(k.indexOf('|') + 1));
      return `${t('suggest.describe_newstop', { name: p.name })}${lines.length ? ` · ${lines.join(', ')}` : ''}${p.text ? ` · ${p.text}` : ''}`;
    }
    return t('suggest.describe_report', { type: reportType(p.type), text: p.text });
  }
  const KIND = { access: t('verify.kind_access'), name: t('verify.kind_name'), report: t('verify.kind_report'),
    removed: t('verify.kind_update'), route: t('verify.kind_update'), newstop: t('verify.kind_update') };
  // Where to see a drawing before voting on it.
  function mapLink(s) {
    if (s.kind === 'route') {
      const [aid, line] = [s.target.split('|')[0], s.target.split('|')[1]];
      return `hat.html?${new URLSearchParams({ sehir: s.city, isletmeci: aid, hat: line, oneri: s.id })}`;
    }
    if (s.kind === 'newstop') return `sehir.html?${new URLSearchParams({ id: s.city, oneri: s.id })}`;
    return null;
  }
  function where(s) {
    const a = s.about || {};
    if (s.targetType === 'city') {
      return el('p', 'text-sm text-ink-3', link(`sehir.html?${new URLSearchParams({ id: s.city })}`, 'text-link hover:underline', a.city || s.city));
    }
    const target = s.targetType === 'stop'
      ? link(`durak.html?${new URLSearchParams({ sehir: s.city, id: s.target })}`, 'text-link hover:underline', a.name || t('line.stop_fallback', { id: s.target }))
      : link(`hat.html?${new URLSearchParams({ sehir: s.city, isletmeci: s.target.split('|')[0], hat: s.target.split('|')[1] })}`, 'text-link hover:underline',
        `${a.line || s.target.split('|')[1]} · ${a.name || ''}`);
    return el('p', 'text-sm text-ink-3', target, ` · ${a.city || s.city}`);
  }
  function voteCard(s) {
    const src = s.payload.source && safeUrl(s.payload.source);
    const srcLink = src ? link(src, 'w-fit text-sm text-link hover:underline', t('verify.see_source')) : null;
    if (srcLink) { srcLink.target = '_blank'; srcLink.rel = 'noopener nofollow ugc'; }
    const ml = mapLink(s);
    const seeMap = ml ? link(ml, 'w-fit text-sm font-medium text-link hover:underline', t('verify.see_map')) : null;
    const count = el('p', 'text-sm text-ink-3');
    // x: the suggestion as the API gives it. Enough votes but still within its first day: when it goes live.
    const showCount = (x) => {
      const v = x.votes;
      count.textContent = x.ready ? t('verify.ready', { when: whenText(x.publishAt) })
        : v.yes || v.no ? t('verify.counted', { yes: v.yes, no: v.no, needed: Math.max(0, s.needed - v.yes) }) : t('verify.first', { needed: s.needed });
    };
    showCount(s);
    const buttons = el('div', 'flex flex-wrap gap-2');
    const msg = el('p', 'text-sm');
    for (const [v, label, cls] of [['yes', t('verify.yes'), PRIMARY], ['no', t('verify.no'), `${BTN} bg-overlay text-ink hover:bg-raised`], ['unsure', t('verify.unsure'), `${BTN} text-ink-2 hover:text-ink`]]) {
      const b = el('button', cls, label);
      b.type = 'button';
      if (s.myVote === v) b.setAttribute('aria-pressed', 'true');
      b.addEventListener('click', async () => {
        for (const x of buttons.children) x.disabled = true;
        try {
          const r = await api.vote(s.id, v);
          showCount(r);
          msg.className = 'text-sm text-ok';
          msg.textContent = r.status === 'live' ? t('verify.thanks_live') : r.status === 'rejected' ? t('verify.thanks_rejected') : t('verify.thanks');
          for (const x of buttons.children) { x.disabled = r.status !== 'open'; x.removeAttribute('aria-pressed'); }
          b.setAttribute('aria-pressed', 'true');
        } catch (e) {
          for (const x of buttons.children) x.disabled = false;
          msg.className = 'text-sm text-crit';
          msg.textContent = say(e);
        }
      });
      buttons.append(b);
    }
    return el('li', 'flex flex-col gap-3 rounded-xl bg-panel p-6 md:p-8',
      el('span', 'text-xs font-semibold uppercase tracking-wide text-ink-3', t('verify.card_meta', { kind: KIND[s.kind], by: s.by, date: day(s.created) })),
      where(s), el('p', 'text-lg text-ink', describe(s)), seeMap, srcLink, count, el('div', 'pt-1', buttons), msg);
  }
  const STATUS = { open: [t('verify.status_open'), 'bg-overlay text-ink-2'], live: [t('verify.status_live'), 'bg-ok/15 text-ok'],
    rejected: [t('verify.status_rejected'), 'bg-crit/15 text-crit'], withdrawn: [t('verify.status_withdrawn'), 'bg-overlay text-ink-3'],
    removed: [t('verify.status_removed'), 'bg-overlay text-ink-3'] };
  function mineRow(s) {
    const [label, cls] = STATUS[s.status] || [s.status, 'bg-overlay text-ink-2'];
    const row = el('li', 'flex flex-col gap-2 py-5',
      el('div', 'flex items-center gap-3', el('span', `rounded-full px-3 py-0.5 text-xs font-medium ${cls}`, label),
        el('span', 'text-xs text-ink-3', t('verify.mine_meta', { kind: KIND[s.kind], date: day(s.created), yes: s.votes.yes, needed: s.needed }))),
      where(s), el('p', 'text-[15px]', describe(s)));
    if (s.status === 'open' || s.status === 'live') {
      const b = el('button', 'w-fit text-sm text-link hover:underline', t('verify.withdraw'));
      b.type = 'button';
      b.addEventListener('click', async () => {
        b.disabled = true;
        try { await api.withdraw(s.id); row.replaceWith(mineRow({ ...s, status: 'withdrawn' })); } catch (e) { b.disabled = false; }
      });
      row.append(b);
    }
    return row;
  }
  // Fills dogrula.html: what waits for votes (optionally for one city or one stop/line), then your own suggestions.
  async function verifyPage(box, params) {
    const list = el('ul', 'flex flex-col gap-5');
    const empty = el('p', 'text-ink-3', t('verify.empty'));
    empty.hidden = true;
    const mine = el('ul', 'divide-y divide-overlay border-y border-overlay');
    const mineSec = el('section', 'flex flex-col gap-4', el('h2', 'text-2xl font-medium', t('verify.mine')), mine);
    mineSec.hidden = true;
    box.append(list, empty, mineSec);
    try {
      const q = {};
      if (params.sehir) q.city = params.sehir;
      if (params.hedef) q.target = params.hedef;
      const r = await api.open(q);
      list.append(...r.items.map(voteCard));
      empty.hidden = r.items.length > 0;
    } catch (e) {
      empty.textContent = t('verify.failed');
      empty.hidden = false;
    }
    if (me && me.token) {
      try {
        const r = await api.mine();
        if (r.items.length) { mine.append(...r.items.map(mineRow)); mineSec.hidden = false; }
      } catch (e) { /* fine without */ }
    }
  }

  // "Sorunlar" (sorunlar.html): the newest published reports from every city, each with where it is.
  async function reportsBlock(box) {
    const list = el('ul', 'divide-y divide-overlay');
    const empty = el('p', 'text-ink-3', t('suggest.reports_empty'));
    box.append(list, empty);
    try {
      const r = await api.reports({ limit: 50 });
      for (const it of r.items) {
        const li = reportItem(it);
        li.append(where(it));
        list.append(li);
      }
      empty.hidden = r.items.length > 0;
    } catch (e) {
      empty.textContent = t('suggest.reports_failed');
    }
  }

  window.hatlasContrib = { api, setMap, stopBlock, lineBlock, cityBlock, verifyPage, reportsBlock };
})();
