/* Hatlas main page (index.html, the user's playground/index.html look): search (cities, operators, lines),
   the map, the feed notice ("N akışın süresi … doluyor") and the stop card on the map.
   The full pages for a city, operator, line or stop are sehir/isletme/hat/durak.html (js/pages.js).
   All data text goes into the page with textContent, never as HTML. */
(function () {
  'use strict';

  // Old addresses of the views that are pages now (index.html#katki, #fotograf-kurallari).
  const MOVED = { '#katki': 'katki.html', '#fotograf-kurallari': 'fotograf-kurallari.html' };
  window.addEventListener('hashchange', () => { if (MOVED[location.hash]) location.replace(MOVED[location.hash]); });
  if (MOVED[location.hash]) { location.replace(MOVED[location.hash]); return; }

  const TURKEY = [[25.6, 35.8], [44.9, 42.2]];
  const STYLE = 'https://tiles.openfreemap.org/styles/dark';
  const VISIBLE = 4;            // results before "Daha fazlasını görüntüle"
  const MAX_RESULTS = 60;
  // A feed that ends within this many days is "about to end". kk-gtfs publishes two months ahead and refreshes on
  // the 1st of each month, so its feeds normally end 30-61 days out; within 30 means a source fell behind.
  // The same number is in js/pages.js (city health check) and tools/update_feeds.py (first notification).
  const ENDING_DAYS = 30;

  const $ = (id) => document.getElementById(id);
  const { t } = window.hatlasCopy;   // the words: copy/tr.toml ([home], [common])
  const toast = (x) => (window.hatlasToast ? window.hatlasToast(x) : null);
  const track = (event, fields) => (window.hatlasUsage ? window.hatlasUsage.track(event, fields) : null);
  const input = $('searchInput');
  const panel = $('searchPanel');
  const list = $('searchResults');
  const footer = $('searchFooter');
  const more = $('searchMore');
  const empty = $('searchEmpty');

  let catalog = { cities: [] };
  let index = [];
  let results = [];
  let expanded = false;
  let active = -1;

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
  const num = (n) => Number(n).toLocaleString('tr-TR');
  const MONTHS = t('common.months').split(',').map((m) => m.trim());
  const dateText = (d) => `${Number(d.slice(6, 8))} ${MONTHS[Number(d.slice(4, 6)) - 1]} ${d.slice(0, 4)}`;
  function ymd(d) {
    return `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`;
  }
  const dayDiff = (a, b) => Math.round((Date.UTC(+b.slice(0, 4), +b.slice(4, 6) - 1, +b.slice(6, 8))
    - Date.UTC(+a.slice(0, 4), +a.slice(4, 6) - 1, +a.slice(6, 8))) / 86400000);
  const url = {
    city: (c) => `sehir.html?${new URLSearchParams({ id: c.id })}`,
    operator: (c, aid) => `isletme.html?${new URLSearchParams({ sehir: c.id, id: aid })}`,
    line: (c, aid, line) => `hat.html?${new URLSearchParams({ sehir: c.id, isletmeci: aid, hat: line })}`,
    stop: (c, id) => `durak.html?${new URLSearchParams({ sehir: c.id, id })}`,
  };
  const store = {
    get(area, k) { try { return window[area].getItem(k); } catch (e) { return null; } },
    set(area, k, v) { try { window[area].setItem(k, v); } catch (e) { /* ignore */ } },
  };
  const CHIP = 'inline-flex min-w-11 justify-center rounded-full bg-white px-2 py-1 font-semibold text-black';
  const SMALL_CHIP = 'inline-flex h-[26px] min-w-[34px] items-center justify-center rounded-full bg-white px-2.5 text-[13px] font-semibold text-black hover:bg-white/80';
  const LINK = 'w-fit text-sm font-medium text-link hover:underline';
  const PICK_LINK = 'mt-1 inline-flex h-9 w-fit items-center rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent-hover';

  // "Katkıda bulun" → Düzenle / Bildir open the map to pick what to change (index.html?katki=duzenle|bildir);
  // the stop card and the "current" box then lead straight to that stop's or line's form (#duzenle, #bildir).
  const PICK = {
    duzenle: { hash: '#duzenle', title: t('home.pick_edit_title'), hint: t('home.pick_edit_hint'),
      stop: t('home.pick_edit_stop'), line: null },
    bildir: { hash: '#bildir', title: t('home.pick_report_title'), hint: t('home.pick_report_hint'),
      stop: t('home.pick_report_stop'), line: t('home.pick_report_line') },
    guncelle: { hash: '#guncelle', title: t('home.pick_update_title'), hint: t('home.pick_update_hint'),
      stop: t('home.pick_update_stop'), line: t('home.pick_update_line'), city: t('home.pick_update_city') },
  }[new URLSearchParams(location.search).get('katki')] || null;
  if (PICK) {
    $('pickTitle').textContent = PICK.title;
    $('pickHint').textContent = PICK.hint;
    $('pickNotice').hidden = false;
  }

  /* ---------- Turkish-insensitive matching: "uskudar" finds "Üsküdar" ---------- */
  function fold(s) {
    return String(s)
      .replace(/İ/g, 'i').replace(/I/g, 'ı').toLowerCase()
      .replace(/ı/g, 'i').replace(/ç/g, 'c').replace(/ğ/g, 'g')
      .replace(/ö/g, 'o').replace(/ş/g, 's').replace(/ü/g, 'u')
      .normalize('NFD').replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, ' ').trim();
  }
  function initials(name) {
    const words = name.replace(/^(Kocaeli|Ss\.)\s+/i, '').split(/\s+/).filter((w) => /^[A-Za-zÇĞİÖŞÜçğıöşü]/.test(w));
    return (words.slice(0, 2).map((w) => w[0]).join('') || name[0]).toLocaleUpperCase('tr');
  }

  function buildIndex() {
    index = [];
    for (const c of catalog.cities) {
      index.push({ kind: 'city', title: c.name, sub: c.lines ? t('home.result_city', { n: c.lines }) : t('home.result_city_empty'),
        badge: `TR${c.plate}`, city: c, weight: c.lines,
        keys: [fold(c.name), `tr${c.plate}`, c.plate],
        // A district (Alanya) also comes up for its province's name (Antalya), below the province itself.
        weakKeys: c.province !== c.name ? [fold(c.province)] : [] });
      for (const o of c.operators) {
        // The city name is a weaker key: "Kocaeli" should list the city first, then its biggest operators.
        index.push({ kind: 'operator', title: o.name, sub: t('home.result_operator', { n: o.lines }),
          badge: initials(o.name), logo: o.logo, city: c, operator: o, weight: o.lines,
          keys: [fold(o.name)], weakKeys: [fold(c.name)] });
      }
      for (const l of c.lineList) {
        index.push({ kind: 'line', title: `${l.line} · ${c.name}`, sub: l.name, badge: l.line,
          city: c, line: l, keys: [fold(l.line)], weakKeys: [fold(l.name)] });
      }
    }
  }

  /* Ranking: exact line number first, then starts-with, then contains; cities before operators before lines. */
  function search(q) {
    const f = fold(q);
    if (!f) return [];
    const kindRank = { city: 0, operator: 1, line: 2, stop: 3 };
    const scored = [];
    for (const item of index) {
      let best = 99;
      const rate = (k) => (k === f ? 0 : k.startsWith(f) ? 1 : k.includes(' ' + f) ? 2 : k.includes(f) ? 3 : 99);
      for (const k of item.keys) best = Math.min(best, rate(k));
      for (const k of item.weakKeys || []) { const r = rate(k); if (r < 99) best = Math.min(best, r + 2); }
      if (best < 99) scored.push([best, kindRank[item.kind], item]);
    }
    scored.sort((a, b) => a[0] - b[0] || a[1] - b[1] || (b[2].weight || 0) - (a[2].weight || 0)
      || a[2].title.localeCompare(b[2].title, 'tr', { numeric: true }));
    return scored.slice(0, MAX_RESULTS).map((s) => s[2]);
  }

  /* ---------- Search panel ---------- */
  function badgeEl(item) {
    if (item.kind === 'stop') {
      const i = el('img', 'size-5');
      i.src = 'assets/icons/stop-bus.svg'; i.width = 20; i.height = 20; i.alt = '';
      return el('span', 'flex size-9 shrink-0 items-center justify-center rounded-full bg-overlay', i);
    }
    if (item.logo) {
      const i = el('img', 'size-9 shrink-0 rounded-full bg-white');
      i.src = item.logo; i.width = 36; i.height = 36; i.alt = '';
      return i;
    }
    const round = item.kind === 'line' ? 'bg-white text-black' : 'bg-overlay text-ink-2';
    return el('span', `flex size-9 shrink-0 items-center justify-center rounded-full font-semibold ${round} ${item.badge.length > 4 ? 'text-[10px]' : 'text-xs'}`, item.badge);
  }

  /* ---------- Stops in the search (data/stopnames.json, built by tools/build_stopnames.py) ----------
     About 30,000 stop places (both sides of a road are one), ~240 KB over the wire: loaded the first time someone
     types two letters, then added to the same index as cities, operators and lines. Busiest stops rank first. */
  let stopNames = null;      // the request, once made
  let stopsReady = false;    // loaded (or failed): until then an empty result isn't counted as "nothing found"
  function wantStops() {
    if (stopNames || !catalog.cities.length) return;
    stopNames = fetch('data/stopnames.json')
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!d) return;
        const byId = new Map(catalog.cities.map((c) => [c.id, c]));
        for (const [cid, rows] of Object.entries(d.cities)) {
          const c = byId.get(cid);
          if (!c) continue;
          for (const [name, id, n] of rows) {
            index.push({ kind: 'stop', title: name, sub: t('home.result_stop', { city: c.name, n }), city: c, stop: id,
              weight: n, keys: [fold(name)] });
          }
        }
      })
      .catch(() => {})
      .finally(() => { stopsReady = true; if (input.value.trim()) render(); });
  }

  function render() {
    const q = input.value.trim();
    list.textContent = '';
    active = -1;
    if (!q) { closePanel(); return; }
    if (fold(q).length >= 2) wantStops();
    results = search(q);
    panel.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    empty.hidden = results.length > 0;
    const shown = expanded ? results : results.slice(0, VISIBLE);
    shown.forEach((item, i) => {
      const btn = el('button', 'result flex w-full items-center gap-3 rounded-md px-2 py-2 text-left hover:bg-raised aria-selected:bg-raised',
        badgeEl(item),
        el('span', 'flex min-w-0 flex-col', el('span', 'truncate font-medium', item.title), el('span', 'truncate text-sm text-ink-3', item.sub)));
      btn.type = 'button';
      btn.id = `result-${i}`;
      btn.setAttribute('role', 'option');
      btn.setAttribute('aria-selected', 'false');
      btn.addEventListener('click', () => choose(item));
      list.append(el('li', null, btn));
    });
    const hiddenCount = results.length - shown.length;
    footer.hidden = hiddenCount <= 0;
    more.textContent = t('home.more_results', { n: hiddenCount });
    noteEmpty(q);
  }

  // A search that found nothing is counted once typing has stopped for 2 s, once per text
  // (js/usage.js sends it only after "İzin ver"; the API refuses anything that looks like an address or a number).
  let emptyTimer = 0;
  let lastEmpty = '';
  function noteEmpty(q) {
    clearTimeout(emptyTimer);
    if (results.length || !catalog.cities.length || !stopsReady || q === lastEmpty) return;
    emptyTimer = setTimeout(() => {
      if (input.value.trim() !== q) return;
      lastEmpty = q;
      track('search_empty', { q });
    }, 2000);
  }

  function closePanel() {
    panel.hidden = true;
    expanded = false;
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }

  function move(step) {
    const opts = list.querySelectorAll('.result');
    if (!opts.length) return;
    if (active >= 0) opts[active].setAttribute('aria-selected', 'false');
    active = (active + step + opts.length) % opts.length;
    opts[active].setAttribute('aria-selected', 'true');
    opts[active].scrollIntoView({ block: 'nearest' });
    input.setAttribute('aria-activedescendant', opts[active].id);
  }

  input.addEventListener('input', () => { expanded = false; render(); });
  input.addEventListener('focus', () => { if (input.value.trim()) render(); });
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); if (panel.hidden) render(); move(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); move(-1); }
    else if (e.key === 'Enter') {
      const opts = list.querySelectorAll('.result');
      const target = active >= 0 ? opts[active] : opts[0];
      if (target) { e.preventDefault(); target.click(); }
    } else if (e.key === 'Escape') { closePanel(); }
  });
  more.addEventListener('click', () => { expanded = true; render(); input.focus(); });
  document.addEventListener('pointerdown', (e) => { if (!$('search').contains(e.target)) closePanel(); });

  function choose(item) {
    input.value = item.kind === 'line' ? `${item.line.line} · ${item.city.name}`
      : item.kind === 'stop' ? `${item.title} · ${item.city.name}` : item.title;
    closePanel();
    input.blur();
    showOnMap(item);
  }

  /* ---------- Feed notice: feeds that end within ENDING_DAYS, or have ended ----------
     Worked out here from each city's validity (data/catalog.json) and today's date, so it is right on the
     day it is read. data/status.json (tools/update_feeds.py) adds when the data last changed. */
  function feedNotice() {
    const today = ymd(new Date());
    const dated = catalog.cities.filter((c) => c.validity);
    const ended = dated.filter((c) => c.validity[1] < today);
    const ending = dated.filter((c) => c.validity[1] >= today && dayDiff(today, c.validity[1]) <= ENDING_DAYS);
    if (!ended.length && !ending.length) return;
    const parts = [];
    if (ended.length) parts.push(t('home.feeds_ended', { n: ended.length }));
    if (ending.length) {
      const dates = [...new Set(ending.map((c) => c.validity[1]))];
      parts.push(dates.length === 1
        ? t('home.feeds_ending_on', { n: ending.length, date: dateText(dates[0]) })
        : t('home.feeds_ending_within', { n: ending.length, days: ENDING_DAYS }));
    }
    $('feedNoticeText').textContent = parts.join(' ');
    if (ended.length) $('feedNoticeBar').className = 'bg-crit p-6 py-2 text-black';
    const items = $('feedListItems');
    for (const c of [...ended, ...ending].sort((a, b) => a.validity[1].localeCompare(b.validity[1]) || a.name.localeCompare(b.name, 'tr'))) {
      const left = dayDiff(today, c.validity[1]);
      items.append(el('li', 'flex items-center gap-3 py-2',
        el('span', 'min-w-0 flex-1 truncate', link(url.city(c), 'text-link hover:underline', c.name)),
        el('span', 'shrink-0 text-sm text-ink-3', left < 0 ? t('home.feed_ended_row', { date: dateText(c.validity[1]) }) : t('home.feed_ending_row', { date: dateText(c.validity[1]), days: left }))));
    }
    $('feedNotice').hidden = false;
    $('feedNoticeMore').addEventListener('click', () => {
      const open = $('feedList').hidden;
      $('feedList').hidden = !open;
      $('feedNoticeMore').setAttribute('aria-expanded', String(open));
    });
    fetch('data/status.json').then((r) => (r.ok ? r.json() : null)).then((s) => {
      if (s && /^\d{4}-\d{2}-\d{2}/.test(s.updated || '')) {
        const d = s.updated.slice(0, 10).replace(/-/g, '');
        $('feedChecked').textContent = t('home.feeds_checked', { date: dateText(d) });
      }
    }).catch(() => {});
  }

  /* ---------- Map ---------- */
  let map = null;
  let loading = 1;   // the map's first full draw
  function busy(step) {
    loading = Math.max(0, loading + step);
    $('loader').hidden = loading === 0;
  }
  const loadedLines = new Map();   // city id -> Promise
  const lineNames = new Map();     // `${operator}|${line}` -> name

  function initMap() {
    if (!window.maplibregl) { $('map').textContent = t('common.map_failed'); busy(-1); return; }
    map = new maplibregl.Map({
      container: 'map',
      style: STYLE,
      bounds: TURKEY,
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-right');
    map.on('load', () => { tintBaseMap(); addCities(); });
    map.on('moveend', autoLoadLines);
    map.once('idle', () => busy(-1));   // style, tiles and the first draw are done
    // The base style asks for a few POI icons its sprite lacks; an empty image keeps the console quiet.
    map.on('styleimagemissing', (e) => {
      if (!map.hasImage(e.id)) map.addImage(e.id, { width: 1, height: 1, data: new Uint8Array(4) });
    });
  }

  /* The base style's colours, nudged to the Figma map: near-black land, slate water. */
  function tintBaseMap() {
    for (const layer of map.getStyle().layers) {
      try {
        if (layer.type === 'background') map.setPaintProperty(layer.id, 'background-color', '#111419');
        else if (layer.type === 'fill' && /water/.test(layer.id)) map.setPaintProperty(layer.id, 'fill-color', '#27303a');
        // Place names in Turkish where the tiles have them ("Türkiye", not "Turkey").
        else if (layer.type === 'symbol' && layer.layout && layer.layout['text-field']) {
          map.setLayoutProperty(layer.id, 'text-field', ['coalesce', ['get', 'name:tr'], ['get', 'name']]);
        }
      } catch (e) { /* layer without that property */ }
    }
  }

  function addCities() {
    map.addSource('cities', {
      type: 'geojson',
      data: {
        type: 'FeatureCollection',
        features: catalog.cities.map((c) => ({
          type: 'Feature', properties: { id: c.id, name: c.name },
          geometry: { type: 'Point', coordinates: c.center },
        })),
      },
    });
    map.addLayer({ id: 'city-dot', type: 'circle', source: 'cities', maxzoom: 9,
      paint: { 'circle-radius': 6, 'circle-color': '#ffffff', 'circle-stroke-width': 3, 'circle-stroke-color': 'rgba(255,255,255,.18)' } });
    map.addLayer({ id: 'city-label', type: 'symbol', source: 'cities', maxzoom: 9,
      layout: { 'text-field': ['get', 'name'], 'text-font': ['Noto Sans Regular'], 'text-size': 13, 'text-offset': [0, 1.3], 'text-anchor': 'top' },
      paint: { 'text-color': '#ffffff', 'text-halo-color': '#020202', 'text-halo-width': 1.2 } });
    map.on('click', 'city-dot', (e) => {
      const c = catalog.cities.find((x) => x.id === e.features[0].properties.id);
      if (c) showOnMap({ kind: 'city', city: c });
    });
    map.on('mouseenter', 'city-dot', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'city-dot', () => { map.getCanvas().style.cursor = ''; });
  }

  // Credit for a city's line data: its own source when it has one (İstanbul: İBB), otherwise kk-gtfs.
  // Built from our own catalog, but escaped anyway since it goes into the map's credit line as HTML.
  function creditFor(city) {
    const s = city.source;
    const esc = (x) => String(x).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
    const label = esc(t('common.map_credit'));
    if (!s || !/^https:\/\//.test(s.url || '')) return `${label} <a href="https://github.com/Egezenn/kk-gtfs" target="_blank" rel="noopener">kk-gtfs</a> (${esc(t('common.kentkart_licence'))})`;
    return `${label} <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.name)}</a> (${esc(s.licence)})`;
  }

  function loadLines(city) {
    if (loadedLines.has(city.id)) return loadedLines.get(city.id);
    if (!city.linesFile) return Promise.resolve();   // a place with stops but no lines yet
    for (const l of city.lineList) lineNames.set(`${l.operator}|${l.line}`, l.name);
    busy(1);
    const p = fetch(city.linesFile)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((geo) => {
        const id = `lines-${city.id}`;
        map.addSource(id, { type: 'geojson', data: geo, attribution: creditFor(city) });
        map.addLayer({ id, type: 'line', source: id,
          layout: { 'line-join': 'round', 'line-cap': 'round' },
          paint: {
            'line-color': ['get', 'color'],
            'line-width': ['interpolate', ['linear'], ['zoom'], 8, 0.7, 12, 1.8, 15, 3.2],
            'line-opacity': 0.85,
          } }, map.getLayer('city-dot') ? 'city-dot' : undefined);
        map.on('click', id, (e) => lineInfo(e, city));
        map.on('mouseenter', id, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', id, () => { map.getCanvas().style.cursor = ''; });
      })
      .catch(() => { loadedLines.delete(city.id); toast(t('home.lines_failed')); })
      .finally(() => busy(-1));
    loadedLines.set(city.id, p);
    return p;
  }

  /* Lines appear by themselves once a city fills the view. */
  function autoLoadLines() {
    if (map.getZoom() < 8) return;
    const b = map.getBounds();
    for (const c of catalog.cities) {
      const [[w, s], [e, n]] = c.bounds;
      if (b.getWest() < e && b.getEast() > w && b.getSouth() < n && b.getNorth() > s) loadLines(c);
    }
  }

  // A click on a line: its number, name and operator, and the way to its page.
  function lineInfo(e, city) {
    // A click on a stop belongs to the stop, not to the line under it.
    if (map.getLayer('stops-hit') && map.queryRenderedFeatures(e.point, { layers: ['stops-hit'] }).length) return;
    const p = e.features[0].properties;
    const op = city.operators.find((o) => o.id === `${city.id}-${p.agency}`);
    const box = el('div', 'flex flex-col gap-1',
      el('strong', 'font-semibold', `${p.line} · ${lineNames.get(`${city.id}-${p.agency}|${p.line}`) || ''}`),
      op ? el('span', 'text-sm text-ink-3', op.name) : null,
      link(url.line(city, p.agency, p.line), `${LINK} mt-1`, t('home.line_page')));
    new maplibregl.Popup({ closeButton: false, maxWidth: '280px' }).setLngLat(e.lngLat).setDOMContent(box).addTo(map);
  }

  /* ---------- Stops: loaded per city when a line is opened ---------- */
  const loadedStops = new Map();   // city id -> Promise<{stops, lines, byStop}>
  function loadStops(city) {
    if (loadedStops.has(city.id)) return loadedStops.get(city.id);
    if (!city.stopsFile) return Promise.resolve(null);   // the feed has no stop times, so no stops per line
    busy(1);
    const p = fetch(city.stopsFile)
      .then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then((d) => {
        d.byStop = {};   // stop id -> line keys ("agency|line") that stop there
        for (const [key, ids] of Object.entries(d.lines)) for (const s of ids) (d.byStop[s] = d.byStop[s] || []).push(key);
        return d;
      })
      .catch(() => { loadedStops.delete(city.id); toast(t('home.stops_failed')); return null; })
      .finally(() => busy(-1));
    loadedStops.set(city.id, p);
    return p;
  }

  const lineKeyExpr = ['concat', ['get', 'agency'], '|', ['get', 'line']];
  const agencyOf = (operatorId) => operatorId.split('-').pop();
  const keyOf = (l) => `${agencyOf(l.operator)}|${l.line}`;

  function ensureStopLayer() {
    if (map.getSource('stops')) return;
    map.addSource('stops', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    map.addLayer({ id: 'stops', type: 'circle', source: 'stops',
      paint: {
        'circle-radius': ['interpolate', ['linear'], ['zoom'],
          10, ['case', ['get', 'selected'], 6, 2.5],
          14, ['case', ['get', 'selected'], 7.5, 4.5],
          17, ['case', ['get', 'selected'], 9, 6]],
        'circle-color': '#ffffff',
        'circle-stroke-color': ['case', ['get', 'selected'], 'rgba(255,255,255,.3)', '#020202'],
        'circle-stroke-width': ['case', ['get', 'selected'], 5, 1.5],
      } });
    // An invisible, wider circle so stops are easy to hit with a mouse or a finger.
    map.addLayer({ id: 'stops-hit', type: 'circle', source: 'stops', paint: { 'circle-radius': 13, 'circle-opacity': 0 } });
    map.on('click', 'stops-hit', (e) => {
      const f = e.features[0];
      if (current && current.city) selectStop(current.city, f.properties.id, f.geometry.coordinates);
    });
    map.on('mouseenter', 'stops-hit', () => { map.getCanvas().style.cursor = 'pointer'; });
    map.on('mouseleave', 'stops-hit', () => { map.getCanvas().style.cursor = ''; });
  }

  function setStops(data, ids, selected) {
    ensureStopLayer();
    const features = [];
    for (const id of ids) {
      const s = data && data.stops[id];
      if (!s) continue;
      features.push({ type: 'Feature', properties: { id, name: s[2], selected: id === selected },
        geometry: { type: 'Point', coordinates: [s[0], s[1]] } });
    }
    features.sort((a, b) => a.properties.selected - b.properties.selected);   // the selected stop on top
    map.getSource('stops').setData({ type: 'FeatureCollection', features });
  }

  /* ---------- "Bu veritabanının düzeltilmeye ihtiyacı var" banner ----------
     Shown for a city whose feed has expired, that has no lines, or where at least BROKEN_SHARE of its lines
     have a broken drawn route (see BROKEN_* in tools/build_catalog.py); and for a single opened line whose
     own route is broken. Closing it hides it for that city until the browser tab is closed. */
  const BROKEN_SHARE = 0.05;
  const banner = $('dataBanner');
  function needsFixing(view) {
    const c = view.city;
    if (!c.lines) return true;
    if (c.validity && c.validity[1] < ymd(new Date())) return true;
    if (c.brokenLines / c.lines >= BROKEN_SHARE) return true;
    return view.kind === 'line' && !!(view.line && view.line.broken);
  }
  function updateBanner(view) {
    const show = !!view && needsFixing(view) && !store.get('sessionStorage', `hatlas.banner.${view.city.id}`);
    banner.hidden = !show;
    const wrap = document.querySelector('.map-wrap');
    wrap.classList.toggle('has-banner', show);
    // The zoom buttons go below the banner, however many lines it wraps to.
    if (show) wrap.style.setProperty('--banner-h', `${banner.offsetHeight}px`);
  }
  $('dataBannerClose').addEventListener('click', () => {
    if (current) store.set('sessionStorage', `hatlas.banner.${current.city.id}`, '1');
    updateBanner(null);
  });

  /* ---------- "What the map shows" box in the left column ---------- */
  function showCurrent(view, stopName) {
    const box = $('current');
    box.textContent = '';
    const c = view.city;
    if (view.kind === 'city') {
      box.append(el('h2', 'text-lg font-medium', t('city.heading', { plate: c.plate, name: c.name })),
        el('p', 'text-sm text-ink-3', t('home.current_city', { lines: num(c.lines), operators: num(c.operators.length) })),
        PICK && PICK.city && c.lines ? link(url.city(c) + PICK.hash, PICK_LINK, PICK.city) : link(url.city(c), LINK, t('home.city_page')));
    } else if (view.kind === 'operator') {
      box.append(el('h2', 'text-lg font-medium', view.operator.name),
        el('p', 'text-sm text-ink-3', t('home.current_operator', { lines: num(view.operator.lines), city: c.name })),
        link(url.operator(c, agencyOf(view.operator.id)), LINK, t('home.operator_page')));
    } else if (view.kind === 'line') {
      const op = c.operators.find((o) => o.id === view.line.operator);
      box.append(el('div', 'flex items-center gap-3', el('span', CHIP, view.line.line), el('span', 'text-sm text-ink-3', c.name)),
        el('h2', 'font-medium', view.line.name),
        op ? el('p', 'text-sm text-ink-3', op.name) : '',   // append() would show null as "null"
        PICK && PICK.line
          ? link(url.line(c, agencyOf(view.line.operator), view.line.line) + PICK.hash, PICK_LINK, PICK.line)
          : link(url.line(c, agencyOf(view.line.operator), view.line.line), LINK, t('home.line_page')),
        PICK ? el('p', 'text-sm text-ink-3', t('home.pick_line_hint')) : '');
    } else if (view.kind === 'stop') {
      box.append(el('h2', 'text-lg font-medium', stopName || ''),
        el('p', 'text-sm text-ink-3', t('home.current_stop', { lines: num(view.keys.length), city: c.name })),
        PICK ? link(url.stop(c, view.stop) + PICK.hash, PICK_LINK, PICK.stop) : link(url.stop(c, view.stop), LINK, t('home.stop_page')));
    }
    box.hidden = false;
  }

  /* What the map shows: a whole city, one operator's lines, one line, or every line through one stop. */
  let current = null;
  let stopPopup = null;
  let stopReturn = null;   // the view to go back to when the stop card closes
  function applyView(view, stopName) {
    current = view;
    const c = view.city;
    const id = `lines-${c.id}`;
    if (stopPopup) { const p = stopPopup; stopPopup = null; p.remove(); }
    updateBanner(view);
    showCurrent(view, stopName);
    if (!map.getLayer(id)) return;
    const thin = ['interpolate', ['linear'], ['zoom'], 8, 0.7, 12, 1.8, 15, 3.2];
    const thick = ['interpolate', ['linear'], ['zoom'], 8, 1.5, 12, 3.2, 15, 5];
    if (view.kind === 'city') {
      map.setFilter(id, null);
      map.setPaintProperty(id, 'line-width', thin);
      if (map.getSource('stops')) setStops(null, []);
    } else if (view.kind === 'operator') {
      map.setFilter(id, ['==', ['get', 'agency'], agencyOf(view.operator.id)]);
      map.setPaintProperty(id, 'line-width', thin);
      if (map.getSource('stops')) setStops(null, []);
    } else {
      // A line, or all lines through a stop: only those are drawn, with their stops.
      map.setFilter(id, ['in', lineKeyExpr, ['literal', view.keys]]);
      map.setPaintProperty(id, 'line-width', thick);
      loadStops(c).then((d) => {
        if (!d || current !== view) return;
        const ids = [];
        const seen = new Set();
        for (const k of view.keys) for (const s of d.lines[k] || []) if (!seen.has(s)) { seen.add(s); ids.push(s); }
        setStops(d, ids, view.stop);
      });
    }
  }

  /* ---------- A stop: a card on the map (Figma "Desktop - 5"'s card), the full page is durak.html ---------- */
  const byNumber = (a, b) => a.line.localeCompare(b.line, 'tr', { numeric: true });

  function selectStop(city, stopId, lngLat) {
    const before = current && current.kind !== 'stop' ? current : stopReturn;
    loadStops(city).then((d) => {
      if (!d || !d.stops[stopId]) return;
      track('map', { city: city.id, kind: 'stop', target: stopId });
      const lines =(d.byStop[stopId] || []).map((k) => city.lineList.find((l) => keyOf(l) === k)).filter(Boolean).sort(byNumber);
      // The line the stop was reached from (a line view), else its first line, names the stop's context.
      const via = (before && before.kind === 'line' && before.line && lines.find((l) => keyOf(l) === keyOf(before.line))) || lines[0];
      applyView({ kind: 'stop', city, keys: lines.map(keyOf), stop: stopId }, d.stops[stopId][2]);
      stopReturn = before;
      stopPopup = new maplibregl.Popup({ closeButton: true, closeOnClick: false, maxWidth: '300px', offset: 14, className: 'stop-popup' })
        .setLngLat(lngLat).setDOMContent(stopCard(city, stopId, d.stops[stopId], lines, via)).addTo(map);
      const mine = stopPopup;
      // Closing the card (× or Escape) goes back to the line or city the stop was opened from.
      mine.on('close', () => {
        if (stopPopup !== mine) return;
        stopPopup = null;
        const back = stopReturn;
        stopReturn = null;
        applyView(back || { kind: 'city', city });
      });
    });
  }

  function lineChip(city, line) {
    const b = el('button', SMALL_CHIP, line.line);
    b.type = 'button';
    b.title = line.name;
    b.addEventListener('click', () => {
      input.value = `${line.line} · ${city.name}`;
      stopReturn = null;
      showOnMap({ kind: 'line', city, line });
    });
    return b;
  }

  function stopCard(city, stopId, stop, lines, via) {
    const icon = el('img', 'mt-0.5 shrink-0');
    icon.src = 'assets/icons/popup-bus.svg'; icon.width = 24; icon.height = 24; icon.alt = '';
    // A busy stop (50 lines at Eskihisar) would make the card taller than the map: show the first
    // CHIP_LIMIT - 1 and a "+N" chip that opens the rest inside the card's scrolling chip area.
    const CHIP_LIMIT = 12;
    const chips = el('div', 'mt-2 flex max-h-32 flex-wrap gap-1.5 overflow-y-auto pr-0.5 [scrollbar-color:var(--color-line-strong)_transparent] [scrollbar-width:thin]');
    const shown = lines.length > CHIP_LIMIT ? lines.slice(0, CHIP_LIMIT - 1) : lines;
    shown.forEach((l) => chips.append(lineChip(city, l)));
    if (shown.length < lines.length) {
      const moreChip = el('button', 'inline-flex h-[26px] min-w-[34px] items-center justify-center rounded-full bg-soft px-2.5 text-[13px] font-semibold text-soft-ink hover:bg-[#10245a]',
        t('home.stop_more', { n: lines.length - shown.length }));
      moreChip.type = 'button';
      moreChip.title = t('home.stop_more_title');
      moreChip.addEventListener('click', () => {
        moreChip.remove();
        lines.slice(shown.length).forEach((l) => chips.append(lineChip(city, l)));
      });
      chips.append(moreChip);
    }
    const op = via && city.operators.find((o) => o.id === via.operator);
    // While picking (PICK), the stop's form is the main button and "Tüm hattı görüntüle" the second one.
    const MAIN = 'inline-flex h-9 w-full items-center justify-center rounded-lg bg-accent px-3.5 text-sm font-semibold text-white hover:bg-accent-hover disabled:bg-overlay disabled:text-ink-3';
    const SECOND = 'inline-flex h-9 w-full items-center justify-center rounded-lg bg-soft px-3.5 text-sm font-semibold text-soft-ink hover:bg-[#16306e] disabled:bg-overlay disabled:text-ink-3';
    const all = el('button', PICK ? `mt-2 ${SECOND}` : `mt-4 ${MAIN}`, t('home.stop_all_line'));
    all.type = 'button';
    all.disabled = !via;
    all.addEventListener('click', () => {
      input.value = `${via.line} · ${city.name}`;
      stopReturn = null;
      showOnMap({ kind: 'line', city, line: via });
    });
    return el('div', 'flex flex-col text-ink',
      el('div', 'flex justify-between gap-3 pr-7',   // room for the card's × button
        el('div', 'min-w-0', el('strong', 'block text-[19px] leading-tight font-semibold', stop[2]),
          via ? el('span', 'mt-1 block text-[15px] leading-snug text-ink-2', via.name) : null),
        icon),
      el('div', 'mt-4 text-sm font-medium', t('home.stop_lines')), chips,
      op ? el('div', 'mt-4 text-sm font-medium', t('home.stop_operator', { name: op.name })) : null,
      PICK ? link(url.stop(city, stopId) + PICK.hash, `mt-4 ${MAIN}`, PICK.stop) : null,
      all,
      PICK ? null : link(url.stop(city, stopId), `mt-2 ${SECOND}`, t('home.stop_page')));
  }

  function showOnMap(item) {
    if (!map) return;
    const c = item.city;
    // A stop from the search: the same as tapping it on the map (its lines drawn, the stop card open)
    if (item.kind === 'stop') {
      loadLines(c).then(() => loadStops(c)).then((d) => {
        const s = d && d.stops[item.stop];
        if (!s) return;
        map.flyTo({ center: [s[0], s[1]], zoom: Math.max(map.getZoom(), 15), duration: 900 });
        selectStop(c, item.stop, [s[0], s[1]]);
      });
      return;
    }
    track('map', { city: c.id, kind: item.kind,
      target: item.kind === 'operator' ? agencyOf(item.operator.id) : item.kind === 'line' ? keyOf(item.line) : '' });
    loadLines(c).then(() => {
      if (item.kind === 'operator') applyView({ kind: 'operator', city: c, operator: item.operator });
      else if (item.kind === 'line') applyView({ kind: 'line', city: c, keys: [keyOf(item.line)], line: item.line });
      else applyView({ kind: 'city', city: c });
    });
    const bounds = item.kind === 'line' ? item.line.bounds : c.bounds;
    map.fitBounds(bounds, { padding: 48, maxZoom: 14, duration: 900 });
  }

  /* ---------- "Yakınımdaki hatlar": location only when asked, never sent anywhere ---------- */
  let here = null;
  $('nearby').addEventListener('click', () => {
    if (!navigator.geolocation) { toast(t('home.no_geolocation')); return; }
    track('nearby', {});   // that it was used, never where
    navigator.geolocation.getCurrentPosition((pos) => {
      const ll = [pos.coords.longitude, pos.coords.latitude];
      if (!map) return;
      if (here) here.remove();
      here = new maplibregl.Marker({ element: el('div', 'here-dot') }).setLngLat(ll).addTo(map);
      map.flyTo({ center: ll, zoom: 14, duration: 1000 });
    }, () => toast(t('home.location_failed')), { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 });
  });

  /* ---------- Start ---------- */
  fetch('data/catalog.json')
    .then((r) => r.json())
    .then((data) => { catalog = data; buildIndex(); feedNotice(); if (input.value.trim()) render(); })
    .catch(() => toast(t('home.data_failed')))
    .finally(initMap);
})();
