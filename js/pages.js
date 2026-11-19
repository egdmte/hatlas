/* Hatlas detail pages, in the playground's look (playground/city|operator|line|station.html):
     sehir.html?id=kocaeli                          a city
     isletme.html?sehir=kocaeli&id=78               an operator (GTFS agency id)
     hat.html?sehir=kocaeli&isletmeci=78&hat=440    a line
     durak.html?sehir=kocaeli&id=30262              a stop (both sides of the road, one tab each)
     katalog.html, sorunlar.html                    every feed; the known problems in them
   Everything comes from data/ (tools/build_catalog.py) and is put on the page as text, never as HTML.
   The words are in copy/tr.toml (t('city.health') reads [city] health; js/copy.js is generated from it).
   The classes are Tailwind; css/pages.css is built from css/pages.src.css (`npm run css`).
   Spacing (2026-11-19, the volunteer hub's scale): the panel's sections are 40 px apart, 24/32 px from its edges. */
(function () {
  'use strict';

  const { t, rich } = window.hatlasCopy;
  const page = document.body.dataset.page;
  const q = new URLSearchParams(location.search);
  const panel = document.getElementById('panel');

  /* ---------- Small helpers ---------- */
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
  function img(src, size, cls) {
    const i = el('img', cls);
    i.src = src; i.width = size; i.height = size; i.alt = '';
    return i;
  }
  const num = (n) => Number(n).toLocaleString('tr-TR');
  // Minutes since midnight; trips after midnight are past 24:00 in GTFS (27:38 = 03:38).
  const time = (m) => (m == null ? '—' : `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`);
  const MONTHS = t('common.months').split(',').map((m) => m.trim());
  function validityText(v) {
    if (!v) return t('common.unknown');
    const [a, b] = v.map((d) => ({ y: d.slice(0, 4), m: MONTHS[Number(d.slice(4, 6)) - 1], d: Number(d.slice(6, 8)) }));
    return a.y === b.y ? `${a.d} ${a.m} – ${b.d} ${b.m} ${b.y}` : `${a.d} ${a.m} ${a.y} – ${b.d} ${b.m} ${b.y}`;
  }
  function ymd(d) {
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
  }
  const trUpper = (s) => s.replace(/i/g, 'İ').replace(/ı/g, 'I').toUpperCase();
  const fold = (s) => s.replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase();
  const byLine = (a, b) => a.localeCompare(b, 'tr', { numeric: true });
  const pageTitle = (name) => { document.title = t('common.title', { name }); };
  // "Gebze - İstasyon - Darıca - Kentönü" -> "Kentönü". Same rule as destination() in tools/build_catalog.py.
  function destination(h) {
    const parts = (h || '').split('-').map((x) => x.trim()).filter(Boolean);
    return parts.length ? parts[parts.length - 1] : h || '';
  }
  // Which data/times-<city>/<n>.json holds a stop. Same sum as bucket_of() in tools/build_catalog.py.
  function bucketOf(id, n) {
    let h = 0;
    for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) % 2147483647;
    return h % n;
  }
  // The suffix after a percentage, read out in Turkish: %99’u, %95’i, %100’ü, %50’si.
  function pctSuffix(n) {
    const ones = ['', 'i', 'si', 'ü', 'ü', 'i', 'sı', 'si', 'i', 'u'];
    const tens = ['', 'u', 'si', 'u', 'ı', 'si', 'ı', 'i', 'i', 'ı'];
    if (n % 10) return ones[n % 10];
    if (n % 100) return tens[(n % 100) / 10];
    return n ? 'ü' : 'ı';
  }
  const getJSON = (url) => fetch(url).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });

  const url = {
    city: (c) => `sehir.html?${new URLSearchParams({ id: c.id })}`,
    operator: (c, aid) => `isletme.html?${new URLSearchParams({ sehir: c.id, id: aid })}`,
    line: (c, aid, line) => `hat.html?${new URLSearchParams({ sehir: c.id, isletmeci: aid, hat: line })}`,
    stop: (c, id) => `durak.html?${new URLSearchParams({ sehir: c.id, id })}`,
  };
  const agencyOf = (opId) => opId.slice(opId.indexOf('-') + 1);

  /* ---------- Pieces, with the playground's classes ---------- */
  const CHIP = 'inline-flex min-w-11 justify-center bg-white text-black py-1 px-2.5 font-semibold rounded-full';
  const chip = (text, href) => (href ? link(href, `${CHIP} hover:bg-white/80`, text) : el('span', CHIP, text));
  const PILL = { ok: 'bg-ok/15 text-ok', warn: 'bg-warn/15 text-warn', crit: 'bg-crit/15 text-crit', none: 'bg-overlay text-ink-2' };
  function pill(kind, text, icon) {
    return el('span', `inline-flex w-fit items-center gap-2 py-1.5 px-3.5 rounded-full text-[15px] ${PILL[kind]}`, icon ? img(icon, 16, 'opacity-80') : null, text);
  }
  const stat = (value, label) => el('div', 'rounded-lg bg-overlay px-4 py-3.5', el('p', 'text-2xl font-semibold', value), el('p', 'text-sm text-ink-3', label));
  // A section of the side panel (the panel itself puts 40 px between them)
  const sec = (extra, ...kids) => el('section', extra ? `mx-6 md:mx-8 ${extra}` : 'mx-6 md:mx-8', ...kids);
  const h2 = (text, count) => el('h2', 'mb-4 text-xl', text, count != null ? ' ' : null, count != null ? el('span', 'text-ink-3', num(count)) : null);
  const note = (...kids) => el('p', 'mt-4 text-sm text-ink-3', ...kids);
  // An operator's logo, or the first two letters of its name in a grey circle.
  const MARK = { 28: 'size-7 text-xs', 32: 'size-8 text-xs', 64: 'size-16 text-xl' };
  function operatorMark(op, size) {
    if (op && op.logo) return img(op.logo, size, `${MARK[size].split(' ')[0]} shrink-0 rounded-full bg-white`);
    const letters = trUpper(((op && op.name) || '?').replace(/[^\p{L}]/gu, '').slice(0, 2));
    return el('span', `flex ${MARK[size]} shrink-0 items-center justify-center rounded-full bg-overlay font-semibold text-ink-2`, letters);
  }
  function dataSection(catalog, city, rows) {
    const s = city.source || catalog.source;
    const src = el('dd');
    if (s && /^https:\/\//.test(s.url || '')) src.append(link(s.url, 'text-link hover:underline', s.name));
    else src.append(s ? s.name : t('common.unknown'));
    src.append(` (${city.source ? s.licence : t('common.kentkart_licence')})`);
    const dl = el('dl', 'grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-[15px]',
      el('dt', 'text-ink-3', t('data.source')), src,
      el('dt', 'text-ink-3', t('data.validity')), el('dd', null, validityText(city.validity)));
    for (const [k, v, cls] of rows) dl.append(el('dt', 'text-ink-3', k), el('dd', cls || null, v));
    return sec(null, h2(t('data.title')), dl);
  }
  // A page's heading block, the first thing in the panel
  const head = (...kids) => el('div', 'mx-6 mt-10 flex flex-col gap-3 md:mx-8', ...kids);

  // Tabs: <div role=tablist data-tabs=group> buttons with data-tab; panels with data-panel + data-tabs-for.
  const onTab = {};
  function tabs(group, items, selected) {
    const list = el('div', 'flex gap-1 rounded-lg bg-overlay p-1');
    list.setAttribute('role', 'tablist');
    list.dataset.tabs = group;
    for (const it of items) {
      const b = el('button', 'flex-1 rounded-md px-3 py-2 text-sm font-medium text-ink-2 aria-selected:bg-raised aria-selected:text-ink', it.label);
      b.type = 'button';
      b.setAttribute('role', 'tab');
      b.dataset.tab = it.id;
      b.title = it.label;
      b.setAttribute('aria-selected', String(it.id === selected));
      list.append(b);
    }
    return el('div', 'mx-6 md:mx-8', list);
  }
  function tabPanel(group, id, selected, ...kids) {
    const d = el('div', 'flex flex-col gap-10', ...kids);
    d.dataset.panel = id;
    d.dataset.tabsFor = group;
    d.hidden = id !== selected;
    return d;
  }
  document.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-tab]');
    const list = tab && tab.closest('[data-tabs]');
    if (!list) return;
    const group = list.dataset.tabs;
    for (const b of list.querySelectorAll('[data-tab]')) b.setAttribute('aria-selected', String(b === tab));
    for (const p of document.querySelectorAll(`[data-tabs-for="${group}"]`)) p.hidden = p.dataset.panel !== tab.dataset.tab;
    if (onTab[group]) onTab[group](tab.dataset.tab);
  });

  function show(...kids) {
    panel.textContent = '';
    panel.append(...kids.filter((k) => k != null && k !== false));
  }
  function notFound(what) {
    document.title = t('common.not_found_title');
    show(head(
      el('h1', 'text-2xl font-medium', t('common.not_found', { what })),
      el('p', 'text-ink-2', t('common.not_found_text')),
      link('./', 'text-link hover:underline', t('common.not_found_back'))));
  }

  /* ---------- The map (as playground/map.js; the site's base map and colours) ---------- */
  const STYLE = 'https://tiles.openfreemap.org/styles/dark';
  const LAND = '#111419';
  const WATER = '#27303a';
  function creditFor(city) {
    const s = city.source;
    const esc = (x) => String(x).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
    const label = esc(t('common.map_credit'));
    if (!s || !/^https:\/\//.test(s.url || '')) return `${label} <a href="https://github.com/Egezenn/kk-gtfs" target="_blank" rel="noopener">kk-gtfs</a> (${esc(t('common.kentkart_licence'))})`;
    return `${label} <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> (${esc(s.licence)})`;
  }
  // opts: { bounds } or { stop: [lon, lat] }; { line, agency } limit the drawn lines.
  function showMap(city, opts) {
    const box = document.getElementById('map');
    if (!window.maplibregl) { box.textContent = t('common.map_failed'); return null; }
    const view = opts.stop ? { center: opts.stop, zoom: 15 } : { bounds: opts.bounds || city.bounds, fitBoundsOptions: { padding: 48 } };
    const map = new maplibregl.Map({ container: box, style: STYLE, ...view,
      attributionControl: { compact: true }, dragRotate: false, pitchWithRotate: false });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('styleimagemissing', (e) => {   // the base style names a few icons its sprite lacks
      if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
    });
    map.on('load', () => {
      for (const layer of map.getStyle().layers) {
        try {
          if (layer.type === 'background') map.setPaintProperty(layer.id, 'background-color', LAND);
          else if (layer.type === 'fill' && /water/.test(layer.id)) map.setPaintProperty(layer.id, 'fill-color', WATER);
          else if (layer.type === 'symbol' && layer.layout && layer.layout['text-field']) {
            map.setLayoutProperty(layer.id, 'text-field', ['coalesce', ['get', 'name:tr'], ['get', 'name']]);
          }
        } catch (err) { /* a layer without that property */ }
      }
      if (city.linesFile) {
        getJSON(city.linesFile).then((geo) => {
          const f = [];
          if (opts.line) f.push(['==', ['get', 'line'], opts.line]);
          if (opts.agency) f.push(['==', ['get', 'agency'], opts.agency]);
          map.addSource('lines', { type: 'geojson', data: geo, attribution: creditFor(city) });
          map.addLayer({ id: 'lines', type: 'line', source: 'lines',
            ...(f.length ? { filter: f.length === 1 ? f[0] : ['all', ...f] } : {}),
            layout: { 'line-join': 'round', 'line-cap': 'round' },
            paint: { 'line-color': ['get', 'color'], 'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.7, 12, 1.8, 15, 3.2], 'line-opacity': 0.85 } },
          map.getLayer('stop') ? 'stop' : undefined);
        }).catch(() => {});
      }
      if (opts.stop) {
        map.addSource('stop', { type: 'geojson', data: point(opts.stop) });
        map.addLayer({ id: 'stop', type: 'circle', source: 'stop',
          paint: { 'circle-radius': 7.5, 'circle-color': '#ffffff', 'circle-stroke-width': 5, 'circle-stroke-color': 'rgba(255,255,255,.3)' } });
      }
    });
    return map;
  }
  const point = (c) => ({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: c } });
  // js/contrib.js draws the community's changes (routes, new stops) and takes clicks for its forms on this map.
  const giveMap = (map) => { if (window.hatlasContrib) window.hatlasContrib.setMap(map); return map; };
  function moveStop(map, c) {
    if (!map) return;
    const src = map.getSource('stop');
    if (src) src.setData(point(c));
    map.easeTo({ center: c, duration: 400 });
  }

  /* ---------- City ---------- */
  const MODES = [[3, 'city.mode_bus'], [11, 'city.mode_trolleybus'], [0, 'city.mode_tram'], [1, 'city.mode_metro'], [2, 'city.mode_train'],
    [7, 'city.mode_funicular'], [5, 'city.mode_cable'], [6, 'city.mode_cable'], [12, 'city.mode_monorail'], [4, 'city.mode_ferry']];
  const MODE_TEXT = {
    'city.mode_bus': t('city.mode_bus'), 'city.mode_trolleybus': t('city.mode_trolleybus'), 'city.mode_tram': t('city.mode_tram'),
    'city.mode_metro': t('city.mode_metro'), 'city.mode_train': t('city.mode_train'), 'city.mode_funicular': t('city.mode_funicular'),
    'city.mode_cable': t('city.mode_cable'), 'city.mode_monorail': t('city.mode_monorail'), 'city.mode_ferry': t('city.mode_ferry'),
  };
  function listText(items) {
    return items.length < 2 ? items.join('') : `${items.slice(0, -1).join(', ')} ${t('common.and')} ${items[items.length - 1]}`;
  }
  function renderCity(catalog, city) {
    pageTitle(city.name);
    const types = new Set(city.lineList.map((l) => l.type));
    const modes = [...new Set(MODES.filter(([n]) => types.has(n)).map(([, k]) => MODE_TEXT[k]))];

    const checks = [];
    const soon = new Date();
    soon.setDate(soon.getDate() + 30);   // as ENDING_DAYS in js/app.js
    if (!city.validity) checks.push(['none', t('city.no_validity')]);
    else if (city.validity[1] < ymd(new Date())) checks.push(['crit', t('city.expired')]);
    else if (city.validity[1] <= ymd(soon)) checks.push(['warn', t('city.ending')]);
    else checks.push(['ok', t('city.current')]);
    if (city.lines) {
      const pct = Math.floor(100 * (1 - city.brokenLines / city.lines));
      checks.push([pct >= 95 ? 'ok' : 'warn', t('city.drawings_ok', { pct, suffix: pctSuffix(pct) })]);
    }
    // Lines without a route drawing in the feed, drawn straight from stop to stop (İstanbul: a few of İETT's).
    if (city.stopDrawnLines) checks.push(['none', t('city.stop_drawn', { n: num(city.stopDrawnLines) })]);
    checks.push(city.detailFile ? ['ok', t('city.has_times')] : ['warn', t('city.no_times')]);
    checks.push(['none', t('city.no_access')]);
    if (city.operators.some((o) => /(^|\s)test(\s|$)/.test(fold(o.name)))) checks.push(['warn', t('city.test_operator')]);

    const ops = el('ul', 'divide-y divide-overlay');
    for (const o of city.operators) {
      ops.append(el('li', 'flex items-center gap-3 py-3', operatorMark(o, 32),
        el('span', 'min-w-0 flex-1 truncate', link(url.operator(city, agencyOf(o.id)), 'text-link hover:underline', o.name)),
        el('span', 'shrink-0 text-sm text-ink-3', t('city.operator_lines', { n: num(o.lines) }))));
    }
    show(
      head(
        el('h1', 'text-3xl font-medium', t('city.heading', { plate: city.plate, name: city.name })),
        modes.length ? el('p', 'text-ink-2', t('city.operators_modes', { n: num(city.operators.length), modes: listText(modes) })) : null),
      sec(null, el('div', 'grid grid-cols-2 gap-3',
        stat(num(city.lines), t('city.stat_lines')), stat(num(city.stops), t('city.stat_stops')),
        city.weekdayTrips != null ? stat(num(city.weekdayTrips), t('city.stat_trips')) : null,
        stat(num(city.brokenLines), t('city.stat_broken')))),
      sec(null, h2(t('city.health')), el('div', 'grid gap-2.5', ...checks.map(([k, x]) => pill(k, x)))),
      city.operators.length ? sec(null, h2(t('city.operators'), city.operators.length), ops) : null,
      // The stops the community added, and "Yeni durak ekle" (js/contrib.js)
      window.hatlasContrib && city.lines ? window.hatlasContrib.cityBlock(city) : null,
      dataSection(catalog, city, [[t('data.note'), (city.source || catalog.source).note || '']]),
    );
    giveMap(showMap(city, {}));
  }

  /* ---------- Operator ---------- */
  function renderOperator(catalog, city, aid) {
    const op = city.operators.find((o) => o.id === `${city.id}-${aid}`);
    if (!op) { notFound(t('operator.what')); return; }
    pageTitle(op.name);
    const lines = city.lineList.filter((l) => l.operator === op.id).sort((a, b) => byLine(a.line, b.line));
    const share = city.lines ? Math.round((100 * lines.length) / city.lines) : 0;
    const list = el('ul', 'divide-y divide-overlay');
    for (const l of lines) {
      list.append(el('li', 'flex items-center gap-3 py-3', chip(l.line, url.line(city, aid, l.line)),
        el('span', 'min-w-0 flex-1 truncate', l.name)));
    }
    show(
      head(operatorMark(op, 64),
        el('h1', 'mt-1 text-3xl font-medium', op.name),
        el('p', 'text-ink-2', t('operator.kind'), link(url.city(city), 'hover:underline', city.name))),
      sec(null, el('div', 'grid grid-cols-3 gap-3',
        stat(num(lines.length), t('operator.stat_lines')),
        stat(op.stops != null ? num(op.stops) : '—', t('operator.stat_stops')),
        stat(op.weekdayTrips != null ? num(op.weekdayTrips) : '—', t('operator.stat_trips'))),
        share && share < 100 ? note(t('operator.share', { city: city.name, n: share })) : null),
      sec(null, h2(t('operator.contact')), el('div', 'grid gap-2.5',
        pill('none', t('operator.no_web')), pill('none', t('operator.no_phone')), pill('none', t('operator.no_fares'))),
        note(t('operator.contact_note'))),
      sec(null, h2(t('operator.lines'), lines.length), list),
      dataSection(catalog, city, [[t('operator.gtfs_code'), aid, 'tabular-nums']]),
    );
    showMap(city, { agency: aid });
  }

  /* ---------- Line ---------- */
  const DAY_NAMES = [['wd', t('line.day_weekday')], ['sa', t('line.day_saturday')], ['su', t('line.day_sunday')]];
  function renderLine(catalog, city, aid, lineNo, detail, stopsData) {
    const entry = city.lineList.find((l) => l.line === lineNo && l.operator === `${city.id}-${aid}`);
    if (!entry) { notFound(t('line.what')); return; }
    pageTitle(`${lineNo} ${entry.name}`);
    const op = city.operators.find((o) => o.id === entry.operator);
    const top = head(
      el('div', 'flex items-center gap-3', el('span', 'inline-flex min-w-14 justify-center rounded-full bg-white px-3 py-1.5 text-xl font-bold text-black', lineNo)),
      // "Yavuz Selim-Gebze-Farabi Dh." reads as "Yavuz Selim – Gebze – Farabi Dh." in the title.
      el('h1', 'mt-2 text-3xl leading-tight font-medium', entry.name.replace(/\s*-+\s*/g, ' – ')),
      op ? link(url.operator(city, aid), 'flex w-fit items-center gap-2 text-ink-2 hover:text-ink', operatorMark(op, 28), op.name) : null);
    const data = dataSection(catalog, city, [[t('data.hatlas_id'), `TR_${city.plate}_${lineNo}`, 'font-mono text-xs leading-6']]);
    const d = detail && detail.lines[`${aid}|${lineNo}`];
    // Confirmed reports and the report form (js/contrib.js).
    const extra = window.hatlasContrib ? window.hatlasContrib.lineBlock(city, `${aid}|${lineNo}`) : null;
    if (!d || !stopsData) {
      show(top, sec(null, note(t('line.no_detail'))), extra, data);
      giveMap(showMap(city, { bounds: entry.bounds, line: lineNo, agency: aid }));
      return;
    }
    // "+N hat": how many other lines stop there (transfers).
    const linesAt = new Map();
    for (const ids of Object.values(stopsData.lines)) for (const s of new Set(ids)) linesAt.set(s, (linesAt.get(s) || 0) + 1);
    const dirs = d.dirs.map((x, i) => ({ ...x, id: `dir${i}`,
      label: destination(x.h) || (stopsData.stops[x.stops[x.stops.length - 1]] || [])[2] || t('line.direction', { n: i + 1 }) }));
    const panels = dirs.map((x) => {
      const rows = DAY_NAMES.filter(([k]) => x.t[k]).map(([k, name]) => el('tr', 'border-t border-overlay',
        el('td', 'py-2.5 pr-4 text-ink-2', name), el('td', 'tabular-nums', time(x.t[k][0])), el('td', 'tabular-nums', time(x.t[k][1])),
        el('td', 'text-right text-ink-3 tabular-nums', num(x.t[k][2]))));
      const stops = el('ol', 'relative before:absolute before:left-[8px] before:top-4 before:bottom-4 before:w-0.5 before:bg-line-strong');
      x.stops.forEach((sid, i) => {
        const s = stopsData.stops[sid];
        const end = i === 0 || i === x.stops.length - 1;
        const more = (linesAt.get(sid) || 1) - 1;
        stops.append(el('li', 'relative flex items-center gap-3 py-2 pl-7',
          el('span', end ? 'absolute left-[3px] top-1/2 -translate-y-1/2 rounded-full size-3.5 bg-white'
            : 'absolute left-[3px] top-1/2 -translate-y-1/2 rounded-full size-3 border-2 border-white bg-panel'),
          s ? link(url.stop(city, sid), 'min-w-0 truncate hover:underline', s[2]) : el('span', 'min-w-0 truncate text-ink-3', t('line.stop_fallback', { id: sid })),
          more > 0 ? el('span', 'ml-auto shrink-0 rounded-full bg-overlay px-2.5 py-0.5 text-xs text-ink-2', t('line.more_lines', { n: more })) : null));
      });
      return tabPanel('dir', x.id, dirs[0].id,
        sec(null, el('div', 'grid grid-cols-2 gap-3', stat(num(x.stops.length), t('line.stat_stops')), stat(num(x.t.wd ? x.t.wd[2] : 0), t('line.stat_trips')))),
        rows.length ? sec(null, h2(t('line.first_last')),
          el('table', 'w-full text-[15px]',
            el('thead', 'text-left text-sm text-ink-3', el('tr', null, el('th', 'pb-2 font-normal', t('line.col_day')), el('th', 'pb-2 font-normal', t('line.col_first')),
              el('th', 'pb-2 font-normal', t('line.col_last')), el('th', 'pb-2 text-right font-normal', t('line.col_trips')))),
            el('tbody', null, ...rows)),
          note(t('line.times_note'))) : null,
        sec(null, h2(t('line.stops')), stops));
    });
    show(top, dirs.length > 1 ? tabs('dir', dirs, dirs[0].id) : null, ...panels, extra, data);
    giveMap(showMap(city, { bounds: entry.bounds, line: lineNo, agency: aid }));
  }

  /* ---------- Stop ---------- */
  const STOP_TYPES = [[4, t('stop.type_ferry')], [1, t('stop.type_metro')], [2, t('stop.type_train')], [0, t('stop.type_tram')], [7, t('stop.type_funicular')]];
  const SIDE_RADIUS_M = 400;   // stops with the same name this close are the two sides of one stop
  function metres(a, b) {
    const k = Math.cos((a[1] * Math.PI) / 180) * 111320;
    return Math.hypot((a[0] - b[0]) * k, (a[1] - b[1]) * 110540);
  }
  function renderStop(catalog, city, id, stopsData) {
    const s = stopsData.stops[id];
    if (!s) { notFound(t('stop.what')); return Promise.resolve(); }
    pageTitle(s[2]);
    const sides = Object.entries(stopsData.stops)
      .filter(([sid, o]) => o[2] === s[2] && metres(o, s) <= SIDE_RADIUS_M)
      .map(([sid]) => sid).sort(byLine);
    const n = city.timesBuckets || 0;
    const files = n ? [...new Set(sides.map((sid) => bucketOf(sid, n)))] : [];
    return Promise.all(files.map((b) => getJSON(`data/times-${city.id}/${b}.json`).catch(() => ({}))))
      .then((parts) => {
        const times = Object.assign({}, ...parts);
        drawStop(catalog, city, id, s, sides, times, stopsData);
      });
  }
  function drawStop(catalog, city, id, s, sides, times, stopsData) {
    const lineInfo = (key) => {
      const [aid, line] = [key.slice(0, key.indexOf('|')), key.slice(key.indexOf('|') + 1)];
      return { aid, line, entry: city.lineList.find((l) => l.line === line && l.operator === `${city.id}-${aid}`),
        op: city.operators.find((o) => o.id === `${city.id}-${aid}`) };
    };
    const keysAt = (sid) => Object.keys(stopsData.lines).filter((k) => stopsData.lines[k].includes(sid));
    const types = new Set();
    const side = sides.map((sid, i) => {
      const rows = (times[sid] || []).slice().sort((a, b) => byLine(lineInfo(a[0]).line, lineInfo(b[0]).line) || a[1].localeCompare(b[1], 'tr'));
      const keys = [...new Set(rows.length ? rows.map((r) => r[0]) : keysAt(sid))].sort((a, b) => byLine(lineInfo(a).line, lineInfo(b).line));
      keys.forEach((k) => { const e = lineInfo(k).entry; if (e) types.add(e.type); });
      // The side is named after where most of its lines go (then most trips): Mezbahane Üstü 2 is
      // "Gebze yönü" (501B, 501E, 502S), not "M.paşa Cami" (two busy lines).
      const toward = new Map();
      for (const r of rows) {
        const x = toward.get(r[1]) || [0, 0];
        toward.set(r[1], [x[0] + 1, x[1] + r[5]]);
      }
      const top = [...toward].sort((a, b) => b[1][0] - a[1][0] || b[1][1] - a[1][1])[0];
      return { sid, id: `side${i}`, label: top ? t('stop.side_toward', { n: i + 1, to: top[0] }) : t('stop.side_n', { n: i + 1 }), rows, keys };
    });
    const typeName = (STOP_TYPES.find(([x]) => types.has(x)) || [0, t('stop.type_bus')])[1];
    // A name the community confirmed replaces the title; the feed's name stays underneath.
    const title = el('h1', 'text-3xl font-medium', s[2]);
    const feedName = el('p', 'text-sm text-ink-3');
    feedName.hidden = true;
    const confirmedName = (name) => {
      if (!name || name === s[2]) return;
      title.textContent = name;
      pageTitle(name);
      feedName.textContent = t('stop.feed_name', { name: s[2] });
      feedName.hidden = false;
    };
    const lineChip = (k) => { const x = lineInfo(k); return chip(x.line, x.entry ? url.line(city, x.aid, x.line) : null); };
    const selected = `side${sides.indexOf(id)}`;
    const panels = side.map((x) => {
      const anyTime = x.rows.some((r) => r[3] != null);
      const list = el('ul', 'divide-y divide-overlay');
      for (const r of x.rows) {
        const info = lineInfo(r[0]);
        const day = r[2] === 'sa' ? t('stop.only_saturday') : r[2] === 'su' ? t('stop.only_sunday') : '';
        list.append(el('li', 'flex items-center gap-3 py-3', lineChip(r[0]),
          el('div', 'min-w-0 flex-1', el('p', 'truncate', r[1]), el('p', 'truncate text-sm text-ink-3', info.op ? info.op.name : '')),
          el('div', 'text-right text-sm', r[3] != null ? el('p', 'tabular-nums', `${time(r[3])} – ${time(r[4])}`) : null,
            el('p', 'text-ink-3', t('stop.trips', { n: num(r[5]) }) + day))));
      }
      // Accessibility, a confirmed name, reports and the suggestion forms belong to one side of the road
      // (one side can have a shelter, the other not): js/contrib.js, inside each side's tab.
      const extra = window.hatlasContrib
        ? window.hatlasContrib.stopBlock(city, x.sid, stopsData.stops[x.sid][2], pill, x.sid === id ? confirmedName : null)
        : null;
      return tabPanel('side', x.id, selected,
        sec(null, h2(t('stop.lines')), el('div', 'flex flex-wrap gap-2', ...x.keys.map(lineChip))),
        x.rows.length ? sec(null, el('h2', 'text-xl', t('stop.first_last')),
          el('p', 'mt-1 mb-3 text-sm text-ink-3', anyTime ? t('stop.times_note') : t('stop.counts_note')),
          list) : sec(null, note(t('stop.no_times'))),
        extra);
    });
    const firstLine = side[0] && side[0].keys[0] ? lineInfo(side[0].keys[0]).line : '0';
    show(
      // Photos need an account; until sign-in exists this opens the photo rules.
      link('fotograf-kurallari.html', 'mx-6 mt-6 flex h-55 shrink-0 rounded-lg bg-overlay text-center text-ink-3 hover:text-ink md:mx-8',
        el('p', 'm-auto px-6', t('stop.photo'))),
      el('div', 'mx-6 flex flex-col gap-2 md:mx-8', title, feedName,
        el('p', 'text-ink-2', `${typeName} · `, link(url.city(city), 'hover:underline', city.name))),
      side.length > 1 ? tabs('side', side, selected) : null,
      ...panels,
      dataSection(catalog, city, [
        [t('stop.stop_code'), sides.join(' · '), 'tabular-nums'],
        [t('data.hatlas_id'), `TR_${city.plate}_${firstLine}_${id}`, 'font-mono text-xs leading-6'],
      ]),
      downloadSection(catalog, city, id, s, side, lineInfo, `TR_${city.plate}_${firstLine}_${id}`),
    );
    const map = giveMap(showMap(city, { stop: [s[0], s[1]] }));
    onTab.side = (tab) => {
      const sid = side.find((x) => x.id === tab).sid;
      const o = stopsData.stops[sid];
      moveStop(map, [o[0], o[1]]);
    };
  }

  // "Ulaşım verisi olarak indir" (was in the map's stop panel, Figma "Desktop - 6"): the stop as JSON, made
  // in the browser, then the licence with the attribution to copy.
  function downloadSection(catalog, city, id, s, side, lineInfo, devId) {
    const card = el('div', 'mt-4 flex flex-col gap-3 rounded-lg bg-overlay p-5 text-sm text-ink-2 [&_strong]:text-ink',
      img('assets/cc-by-sa.png', 96, 'h-[34px] w-24 rounded'),
      el('p', null, t('stop.download_started')),
      el('p', null, rich('stop.download_licence')),
      el('p', 'text-ink', `“${t('stop.attribution')}”`),
      el('p', null, t('stop.download_others')));
    card.querySelector('img').height = 34;
    card.setAttribute('role', 'status');
    card.hidden = true;
    const btn = el('button', 'inline-flex h-11 w-full items-center justify-center rounded-lg bg-accent px-4 text-[15px] font-semibold text-white hover:bg-accent-hover', t('stop.download'));
    btn.type = 'button';
    btn.addEventListener('click', () => {
      const keys = [...new Set(side.flatMap((x) => x.keys))];
      const data = {
        id: devId,
        name: s[2],
        city: city.name,
        plate: city.plate,
        gtfs_stop_ids: side.map((x) => x.sid),
        coordinates: { lon: s[0], lat: s[1] },
        lines: keys.map((k) => { const x = lineInfo(k); return { line: x.line, name: x.entry ? x.entry.name : null, operator: x.op ? x.op.name : null }; }),
        accessibility: { staff: 'unknown', stepfree: 'unknown', sidewalk: 'unknown', shelter: 'unknown' },
        source: city.source || catalog.source || null,
        licence: t('stop.download_file_licence'),
        attribution: t('stop.attribution'),
        downloaded: new Date().toISOString().slice(0, 10),
      };
      const blob = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const a = el('a');
      a.href = blob;
      a.download = `hatlas-${devId}.json`;
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(blob), 1000);
      card.hidden = false;
    });
    return sec(null, btn, card);
  }

  /* ---------- Veri kataloğu (katalog.html) and Sorunlar (sorunlar.html): whole pages, no map ---------- */
  const ENDING_DAYS = 30;   // as in js/app.js and the city page
  function daysLeft(v) {
    const end = new Date(Number(v.slice(0, 4)), Number(v.slice(4, 6)) - 1, Number(v.slice(6, 8)));
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    return Math.round((end - today) / 864e5);
  }
  function feedState(city) {
    if (!city.lines) return ['none', t('catalog.state_no_lines')];
    if (!city.validity) return ['none', t('catalog.state_no_date')];
    const d = daysLeft(city.validity[1]);
    if (d < 0) return ['crit', t('catalog.state_expired')];
    if (d <= ENDING_DAYS) return ['warn', d === 0 ? t('catalog.state_today') : t('catalog.state_days', { n: d })];
    return ['ok', t('catalog.state_ok')];
  }
  const sourceOf = (catalog, city) => city.source || catalog.source;
  function outLink(href, text) {
    const a = link(href, 'text-link hover:underline', text);
    a.rel = 'noopener';
    return a;
  }
  function fileLink(href, text) {
    const a = link(href, 'text-link hover:underline', text);
    a.download = '';
    return a;
  }
  const PROSE_LINKS = '[&_a]:text-link [&_a:hover]:underline';
  const pageHead = (title, text) => el('section', 'flex flex-col gap-4',
    el('h1', 'text-3xl font-medium md:text-4xl', title), el('p', 'max-w-[680px] text-lg text-ink-2', text));
  const block = (...kids) => el('section', 'flex flex-col gap-5', ...kids);
  const h2p = (text, count) => el('h2', 'text-2xl font-medium', text, count != null ? ' ' : null, count != null ? el('span', 'text-ink-3', num(count)) : null);

  function renderCatalog(catalog, status) {
    const cities = catalog.cities;
    const sum = (k) => cities.reduce((a, c) => a + (c[k] || 0), 0);
    const updated = status && status.updated ? new Date(status.updated) : null;

    const filter = el('input', 'h-11 w-full rounded-lg border border-line bg-base px-4 text-[15px] text-ink placeholder:text-ink-3 focus:border-link focus:outline-none md:max-w-xs');
    filter.type = 'search';
    filter.placeholder = t('catalog.filter');
    filter.setAttribute('aria-label', t('catalog.filter'));
    const list = el('ul', 'divide-y divide-overlay border-y border-overlay');
    const none = el('p', `text-ink-3 ${PROSE_LINKS}`, rich('catalog.none'));
    none.hidden = true;

    for (const c of cities) {
      const s = sourceOf(catalog, c);
      const [kind, label] = feedState(c);
      const files = el('p', 'flex flex-wrap gap-x-4 gap-y-1 text-sm');
      if (c.linesFile) files.append(fileLink(c.linesFile, t('catalog.lines_file')));
      if (c.stopsFile) files.append(fileLink(c.stopsFile, t('catalog.stops_file')));
      if (s && /^https:\/\//.test(s.url || '')) files.append(outLink(s.url, t('catalog.source_link')));
      const li = el('li', 'grid gap-3 py-6 md:grid-cols-[minmax(0,1fr)_13rem_minmax(0,17rem)] md:items-center md:gap-8',
        el('div', 'min-w-0',
          link(url.city(c), 'font-medium text-link hover:underline', t('city.heading', { plate: c.plate, name: c.name })),
          el('p', 'text-sm text-ink-3', t('catalog.row_place', { province: c.province, source: s ? s.name : t('common.unknown') }))),
        el('div', 'text-sm',
          el('p', null, t('catalog.row_size', { lines: num(c.lines), stops: num(c.stops) })),
          el('p', 'text-ink-3', validityText(c.validity))),
        el('div', 'flex flex-col gap-2', pill(kind, label), files));
      li.dataset.q = fold(`${c.name} ${c.province} ${c.plate}`);
      list.append(li);
    }
    filter.addEventListener('input', () => {
      const f = fold(filter.value.trim());
      let shown = 0;
      for (const li of list.children) {
        li.hidden = !!f && !li.dataset.q.includes(f);
        if (!li.hidden) shown++;
      }
      none.hidden = shown > 0;
    });

    // Every source once, with its licence, its note and the cities it covers
    const seen = new Map();
    for (const c of cities) {
      const s = sourceOf(catalog, c);
      if (!s) continue;
      if (!seen.has(s.name)) seen.set(s.name, { s, names: [] });
      seen.get(s.name).names.push(c.name);
    }
    const sources = el('ul', 'grid gap-4 md:grid-cols-2');
    for (const { s, names } of seen.values()) {
      sources.append(el('li', 'flex flex-col gap-2 rounded-xl bg-panel p-6 text-[15px]',
        el('p', 'font-medium', /^https:\/\//.test(s.url || '') ? outLink(s.url, s.name) : s.name, ` · ${s.licence}`),
        s.note ? el('p', 'text-ink-2', s.note) : null,
        el('p', 'text-ink-3', names.length > 3 ? t('catalog.n_cities', { n: num(names.length) }) : listText(names))));
    }

    show(
      pageHead(t('catalog.title'), t('catalog.intro')),
      el('div', 'grid grid-cols-2 gap-4 md:grid-cols-4',
        stat(num(cities.length), t('catalog.stat_feeds')), stat(num(sum('lines')), t('catalog.stat_lines')),
        stat(num(sum('stops')), t('catalog.stat_stops')), stat(num(sum('weekdayTrips')), t('catalog.stat_trips'))),
      block(
        el('div', 'flex flex-col gap-4 md:flex-row md:items-center md:justify-between', h2p(t('catalog.feeds'), cities.length), filter),
        list, none,
        updated ? el('p', 'text-sm text-ink-3', t('catalog.updated', { date: `${updated.getDate()} ${MONTHS[updated.getMonth()]} ${updated.getFullYear()}` })) : null),
      block(h2p(t('catalog.sources')), sources),
      block(h2p(t('catalog.developers')),
        el('p', 'max-w-[680px] text-ink-2', `${t('catalog.developers_before')} `, fileLink('data/catalog.json', 'catalog.json'), t('catalog.developers_after'))),
      el('p', `text-sm text-ink-3 ${PROSE_LINKS}`, rich('catalog.missing')),
    );
  }

  const isTestOp = (o) => /(^|\s)test(\s|$)/.test(fold(o.name));
  function renderIssues(catalog) {
    const cities = catalog.cities.filter((c) => c.lines);
    const row = (c, detail, kind, label, extra) => el('li', 'flex flex-col gap-3 py-5',
      el('div', 'flex flex-wrap items-center justify-between gap-x-4 gap-y-2',
        el('div', 'min-w-0', link(url.city(c), 'font-medium text-link hover:underline', t('city.heading', { plate: c.plate, name: c.name })),
          detail ? el('p', 'text-sm text-ink-3', detail) : null),
        kind ? pill(kind, label) : null),
      extra);
    const group = (title, why, rows) => (rows.length
      ? block(h2p(title, rows.length), el('p', 'text-ink-2', why), el('ul', 'divide-y divide-overlay border-y border-overlay', ...rows))
      : null);

    const feeds = [];
    for (const c of cities) {
      const [kind, label] = feedState(c);
      if (kind === 'crit' || kind === 'warn') feeds.push([daysLeft(c.validity[1]), row(c, t('issues.validity_row', { validity: validityText(c.validity) }), kind, label)]);
      else if (kind === 'none') feeds.push([-1e9, row(c, t('issues.no_validity_row'), 'none', label)]);
    }
    feeds.sort((a, b) => a[0] - b[0]);

    const broken = cities.filter((c) => c.brokenLines)
      .sort((a, b) => b.brokenLines / b.lines - a.brokenLines / a.lines)
      .map((c) => {
        const pct = Math.floor(100 * (1 - c.brokenLines / c.lines));
        const lines = c.lineList.filter((l) => l.broken).sort((a, b) => byLine(a.line, b.line));
        const more = el('details', 'text-sm',
          el('summary', 'w-fit cursor-pointer text-link hover:underline', t('issues.show_lines')),
          el('div', 'mt-3 flex flex-wrap gap-2', ...lines.map((l) => chip(l.line, url.line(c, agencyOf(l.operator), l.line)))));
        return row(c, t('issues.broken_row', { broken: num(c.brokenLines), lines: num(c.lines) }), pct >= 95 ? 'ok' : 'warn',
          t('city.drawings_ok', { pct, suffix: pctSuffix(pct) }), more);
      });

    const noTimes = cities.filter((c) => !c.detailFile).map((c) => row(c, t('issues.lines_row', { n: num(c.lines) }), 'warn', t('issues.no_times_pill')));
    const stopDrawn = cities.filter((c) => c.stopDrawnLines).map((c) => row(c, t('issues.lines_row', { n: num(c.stopDrawnLines) }), 'none', t('issues.stop_drawn_pill')));
    const testOps = cities.filter((c) => c.operators.some(isTestOp))
      .map((c) => row(c, c.operators.filter(isTestOp).map((o) => o.name).join(', '), 'warn', t('issues.test_pill')));
    const empty = catalog.cities.filter((c) => !c.lines).map((c) => row(c, t('issues.empty_row', { n: num(c.stops) }), 'none', t('issues.empty_pill')));

    const reports = el('div');
    const autos = [
      group(t('issues.feeds_title'), t('issues.feeds_text', { days: ENDING_DAYS }), feeds.map(([, r]) => r)),
      group(t('issues.broken_title'), t('issues.broken_text'), broken),
      group(t('issues.times_title'), t('issues.times_text'), noTimes),
      group(t('issues.stop_drawn_title'), t('issues.stop_drawn_text'), stopDrawn),
      group(t('issues.test_title'), t('issues.test_text'), testOps),
      group(t('issues.empty_title'), t('issues.empty_text'), empty),
    ].filter(Boolean);

    show(
      pageHead(t('issues.title'), t('issues.intro')),
      block(h2p(t('issues.reports')),
        el('p', 'text-ink-2', t('issues.reports_text')),
        reports,
        el('p', 'text-sm', link('dogrula.html', 'text-link hover:underline', t('issues.verify_link')))),
      ...(autos.length ? autos : [block(h2p(t('issues.auto_title')), el('p', 'text-ink-3', t('issues.auto_none')))]),
      el('p', `text-sm text-ink-3 ${PROSE_LINKS}`, rich('issues.footer')),
    );
    if (window.hatlasContrib) window.hatlasContrib.reportsBlock(reports);
    else reports.append(el('p', 'text-ink-3', t('issues.reports_failed')));
  }

  /* ---------- Start ---------- */
  // "Bu doğru mu?" (dogrula.html): no map, no catalog needed; js/contrib.js fills it.
  if (page === 'verify') {
    if (window.hatlasContrib) {
      window.hatlasContrib.verifyPage(document.getElementById('verify'),
        { sehir: q.get('sehir') || '', hedef: q.get('hedef') || '' });
    }
    return;
  }
  if (page === 'catalog' || page === 'issues') {
    Promise.all([getJSON('data/catalog.json'), page === 'catalog' ? getJSON('data/status.json').catch(() => null) : null])
      .then(([catalog, status]) => (page === 'catalog' ? renderCatalog(catalog, status) : renderIssues(catalog)))
      .catch(() => show(el('p', 'text-ink-3', t('common.load_failed'))));
    return;
  }
  getJSON('data/catalog.json').then((catalog) => {
    const city = catalog.cities.find((c) => c.id === (page === 'city' ? q.get('id') : q.get('sehir')));
    if (!city) { notFound(t('city.what')); return null; }
    if (page === 'city') return renderCity(catalog, city);
    if (page === 'operator') return renderOperator(catalog, city, q.get('id') || '');
    if (page === 'line') {
      return Promise.all([
        city.detailFile ? getJSON(city.detailFile) : null,
        city.stopsFile ? getJSON(city.stopsFile) : null,
      ]).then(([detail, stopsData]) => renderLine(catalog, city, q.get('isletmeci') || '', q.get('hat') || '', detail, stopsData));
    }
    if (page === 'stop') {
      if (!city.stopsFile) { notFound(t('stop.what')); return null; }
      return getJSON(city.stopsFile).then((stopsData) => renderStop(catalog, city, q.get('id') || '', stopsData));
    }
    return null;
  }).catch(() => {
    show(el('p', 'mx-6 mt-10 text-ink-3 md:mx-8', t('common.load_failed')));
  });
})();
