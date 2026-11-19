"""Builds Hatlas's static data from GTFS feeds.

Usage:  py -3 -I tools/build_catalog.py
Reads every city feed listed in CITIES from KK_DATA (the kk-gtfs project's data folder,
https://github.com/Egezenn/kk-gtfs, data CC0) and writes:
  data/catalog.json             cities, operators and lines for the search and the map markers
  data/lines-<id>.geojson       one simplified shape per line and direction
  data/stops-<id>.json          stops along each line (only where the feed has stop times)
Only the standard library; GTFS files are read as data, never executed.
"""
import csv, json, math, os, shutil, sys, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Where the files go. tools/update_feeds.py passes a staging folder (`build_catalog.py <folder>`) and swaps it
# in only when the build finished, so a failed update never leaves data/ half-written.
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(ROOT, 'data')
KK_DATA = os.path.expanduser('~/Downloads/kk-gtfs-main/kk-gtfs-main/data')

SOURCE = {
    'name': 'kk-gtfs',
    'url': 'https://github.com/Egezenn/kk-gtfs',
    'licence': 'CC0 1.0',
    'note': 'KentKart verisinden derlenmiştir; asıl verinin hakları KentKart ve ilgili belediyelere aittir.',
}

# id (the feed's folder name) -> display name, plate code, province. Districts carry their province's plate.
CITIES = {
    'adana': ('Adana', '01', 'Adana'),
    'akcakoca': ('Akçakoca', '81', 'Düzce'),
    'alanya': ('Alanya', '07', 'Antalya'),
    'alapli': ('Alaplı', '67', 'Zonguldak'),
    'altinova': ('Altınova', '77', 'Yalova'),
    'antalya': ('Antalya', '07', 'Antalya'),
    'burdur': ('Burdur', '15', 'Burdur'),
    'canakkale': ('Çanakkale', '17', 'Çanakkale'),
    'civril': ('Çivril', '20', 'Denizli'),
    'duzce': ('Düzce', '81', 'Düzce'),
    'edirne': ('Edirne', '22', 'Edirne'),
    'eregli': ('Karadeniz Ereğli', '67', 'Zonguldak'),
    'erzurum': ('Erzurum', '25', 'Erzurum'),
    'gaziantep': ('Gaziantep', '27', 'Gaziantep'),
    'kastamonu': ('Kastamonu', '37', 'Kastamonu'),
    'kirklareli': ('Kırklareli', '39', 'Kırklareli'),
    'kocaeli': ('Kocaeli', '41', 'Kocaeli'),
    'luleburgaz': ('Lüleburgaz', '39', 'Kırklareli'),
    'mardin': ('Mardin', '47', 'Mardin'),
    'mugla': ('Muğla', '48', 'Muğla'),
    'nigde': ('Niğde', '51', 'Niğde'),
    'ordu': ('Ordu', '52', 'Ordu'),
    'osmaniye': ('Osmaniye', '80', 'Osmaniye'),
    'safranbolu': ('Safranbolu', '78', 'Karabük'),
    'sivas': ('Sivas', '58', 'Sivas'),
    'tokat': ('Tokat', '60', 'Tokat'),
    'yozgat': ('Yozgat', '66', 'Yozgat'),
    'istanbul': ('İstanbul', '34', 'İstanbul'),
}

# Feeds that don't come from kk-gtfs: their own folder and their own source line.
# İstanbul: İBB's İETT download, cleaned into GTFS by tools/import_istanbul.py, with its routes drawn from İBB's
# "İETT Hat Güzergahları Verisi". A line with no fitting route is drawn stop to stop: its shape_id ends in "_stops".
FEEDS = {
    'istanbul': {
        'path': os.path.expanduser('~/Downloads/istanbul-gtfs'),
        'source': {'name': 'İBB Açık Veri Portalı', 'url': 'https://data.ibb.gov.tr',
                   'licence': 'İBB Açık Veri Lisansı', 'note': 'İETT otobüs hatları, durakları ve güzergahları.'},
    },
}

# Friendlier names for some operators (feed id -> agency id -> name); the rest are title-cased.
AGENCY_NAMES = {'kocaeli': {'78': 'Kocaeli UlaşımPark'}, 'istanbul': {'1': 'İETT'}}

SIMPLIFY_M = 12  # Douglas-Peucker tolerance for the map lines, in metres

# A line's drawn route counts as broken when it is a straight stroke made of two points over this length,
# or when two neighbouring points are further apart than BROKEN_GAP_M. Ferries (route_type 4) are left out:
# their open-water legs really are long and straight. Measured 2026-11-17 over 3,845 shapes: half have no
# gap over 743 m, 99% none over ~9.8 km; the broken ones are two-point strokes (Mardin TR17, 88 km) and
# misplaced points (Akçakoca 01, a 1,100 km jump).
BROKEN_GAP_M = 5000
BROKEN_TWO_POINT_M = 1000
# Lines drawn stop to stop (no shapes in the feed) jump between stops by design, and express lines skip
# long stretches: in İstanbul (2026-11-18) the airport, Sabiha Gökçen and E- express lines have real
# non-stop legs of 15-33 km (303B Otogar–Marmara Cezaevi: 33 km). There only a jump this long counts,
# which means a stop placed in the wrong spot.
BROKEN_GAP_FROM_STOPS_M = 50000


def hav(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def shape_is_broken(seq, route_type, from_stops=False):
    """seq: sorted (sequence, lat, lon). True when the drawn route can't be the real one."""
    if route_type == '4' or len(seq) < 2:
        return False
    gaps = [hav(a[1:], b[1:]) for a, b in zip(seq, seq[1:])]
    if from_stops:
        return max(gaps) > BROKEN_GAP_FROM_STOPS_M
    if len(seq) == 2 and gaps[0] > BROKEN_TWO_POINT_M:
        return True
    return max(gaps) > BROKEN_GAP_M


def has(path, name):
    return os.path.exists(os.path.join(path, name))


def rows(path, name):
    if not has(path, name):
        return
    with open(os.path.join(path, name), encoding='utf-8-sig', newline='') as f:
        yield from csv.DictReader(f)


def tr_lower(s):
    return s.replace('I', 'ı').replace('İ', 'i').lower()


def tr_upper_char(c):
    return 'İ' if c == 'i' else 'I' if c == 'ı' else c.upper()


def tr_title(s):
    """ALL-CAPS GTFS names to Title Case with Turkish letters ("OTOGAR-BAYINDIRLIK" -> "Otogar-Bayındırlık")."""
    out, start = [], True
    for c in tr_lower(s):
        out.append(tr_upper_char(c) if start and c.isalpha() else c)
        start = c in ' -/(' or (start and not c.isalpha())
    return ''.join(out).replace('A.ş.', 'A.Ş.')


def map_color(hex6, min_lum=0.18):
    """GTFS colours are picked for light maps; mix too-dark ones with white so they read on the dark map."""
    hex6 = (hex6 or '').strip().lstrip('#')
    if len(hex6) != 6:
        hex6 = '9A9A9A'
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    lin = lambda c: c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    lum = lambda r, g, b: 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    t = 0.0
    while lum(r + (1 - r) * t, g + (1 - g) * t, b + (1 - b) * t) < min_lum and t < 1:
        t += 0.05
    mix = lambda c: round((c + (1 - c) * t) * 255)
    return '#{:02X}{:02X}{:02X}'.format(mix(r), mix(g), mix(b)), '#' + hex6.upper()


def rdp(points, eps):
    """Douglas-Peucker on (x, y) metres; returns kept indices."""
    if len(points) < 3:
        return list(range(len(points)))
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = points[a]
        bx, by = points[b]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy) or 1e-9
        best, idx = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs(dy * px - dx * py + bx * ay - by * ax) / norm
            if d > best:
                best, idx = d, i
        if best > eps and idx > 0:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [i for i, k in enumerate(keep) if k]


def clean_stop_name(raw):
    name = tr_title(raw)
    # "Karayolu Caddesi 1" / "... 2" are the two sides of the road; the map shows them as one name.
    return name[:-2] if len(name) > 2 and name[-2] == ' ' and name[-1].isdigit() else name


# ---------- Timetable facts (line and stop pages) ----------
# Day types: 'wd' weekdays (a service running on Monday stands for them), 'sa' Saturday, 'su' Sunday.
DAYS = ('wd', 'sa', 'su')
# The stop times are split into files of about this many stops, so a stop page loads one small file.
STOPS_PER_BUCKET = 500


def read_days(p):
    """service_id -> the day types it runs on."""
    return {c['service_id']: tuple(d for d, col in (('wd', 'monday'), ('sa', 'saturday'), ('su', 'sunday'))
                                   if (c.get(col) or '').strip() == '1')
            for c in rows(p, 'calendar.txt')}


def minutes(t):
    """'25:10:00' -> 1510 (after-midnight times stay past 24:00, the page shows them as 01:10). '' -> None."""
    t = (t or '').strip()
    if not t:
        return None
    h, m = t.split(':')[:2]
    return int(h) * 60 + int(m)


def headsign(s):
    s = (s or '').strip()
    return tr_title(s) if s and s == s.upper() and any(c.isalpha() for c in s) else s


def destination(hs):
    """'Gebze - İstasyon - Darıca - Kentönü' -> 'Kentönü'. The same rule is in js/pages.js (destination)."""
    parts = [x.strip() for x in hs.split('-') if x.strip()]
    return parts[-1] if parts else hs


def bucket_of(stop_id, n):
    """Which times-<city>/<n>.json holds a stop. The same sum is in js/pages.js (bucketOf)."""
    h = 0
    for ch in stop_id:
        h = (h * 31 + ord(ch)) % 2147483647
    return h % n


class TimetablePass:
    """Fed every stop_times row once; answers what the line and stop pages show."""

    def __init__(self, routes, trips, days):
        self.trip = {}                      # trip_id -> (route_id, agency, line, direction, headsign, day types)
        self.route_dir = collections.Counter()
        for t in trips:
            r = routes.get(t['route_id'])
            if not r:
                continue
            d = t['direction_id'] or '0'
            run = days.get(t['service_id'], ('wd',) if not days else ())  # no calendar at all: count as weekday
            self.trip[t['trip_id']] = (t['route_id'], r['agency_id'], r['route_short_name'], d, headsign(t['trip_headsign']), run)
            self.route_dir[(t['route_id'], d)] += 1
        self.first = {}                     # trip_id -> (sequence, minutes) at its first stop
        self.at = {}                        # (stop, 'agency|line', headsign, day) -> [first, last, trips]

    def add(self, r):
        info = self.trip.get(r['trip_id'])
        if not info:
            return
        seq = int(r['stop_sequence'])
        m = minutes(r['departure_time'] or r['arrival_time'])  # İstanbul: times only at timing points
        f = self.first.get(r['trip_id'])
        if f is None or seq < f[0]:
            self.first[r['trip_id']] = (seq, m)
        _rid, aid, line, _d, hs, run = info
        for day in run:
            k = (r['stop_id'], f'{aid}|{line}', hs, day)
            v = self.at.get(k)
            if v is None:
                self.at[k] = [m, m, 1]
                continue
            if m is not None:
                if v[0] is None or m < v[0]:
                    v[0] = m
                if v[1] is None or m > v[1]:
                    v[1] = m
            v[2] += 1

    def stop_rows(self):
        """stop -> [[line key, headsign, day, first, last, trips]], weekday when the line runs then, else Saturday, else Sunday."""
        best = {}
        for (s, key, hs, day), v in self.at.items():
            k = (s, key, hs)
            if k not in best or DAYS.index(day) < DAYS.index(best[k][0]):
                best[k] = (day, v)
        # Variants that end at the same place are one row ("…-Darıca-Bayramoğlu" and "…-Emek-Bayramoğlu").
        merged = {}
        for (s, key, hs), (day, (a, b, n)) in best.items():
            k = (s, key, destination(hs), day)
            m = merged.get(k)
            if m is None:
                merged[k] = [a, b, n]
                continue
            m[0] = a if m[0] is None else m[0] if a is None else min(m[0], a)
            m[1] = b if m[1] is None else m[1] if b is None else max(m[1], b)
            m[2] += n
        out = collections.defaultdict(list)
        for (s, key, dest, day), (a, b, n) in sorted(merged.items()):
            out[s].append([key, dest, day, a, b, n])
        return out

    def line_detail(self, wanted_trip, seqs, line_stops):
        """'agency|line' -> {dirs: [{h: headsign, stops: [ids], t: {day: [first, last, trips]}}]}, departures from the first stop."""
        firsts = collections.defaultdict(list)
        count = collections.Counter()
        signs = collections.defaultdict(collections.Counter)
        for tid, (_rid, aid, line, d, hs, run) in self.trip.items():
            f = self.first.get(tid)
            if f is None:
                continue  # a trip without stop times
            key = f'{aid}|{line}'
            signs[(key, d)][hs] += 1
            for day in run:
                count[(key, d, day)] += 1
                if f[1] is not None:
                    firsts[(key, d, day)].append(f[1])
        # The stop list per direction: the drawn trip of the line's busiest route variant.
        pick = {}
        for (rid, d), tid in wanted_trip.items():
            info = self.trip.get(tid)
            if not info:
                continue
            key, n = f'{info[1]}|{info[2]}', self.route_dir[(rid, d)]
            if (key, d) not in pick or n > pick[(key, d)][0]:
                pick[(key, d)] = (n, tid)
        out = {}
        for (key, d), (_n, tid) in sorted(pick.items()):
            if key not in line_stops:
                continue
            t = {}
            for day in DAYS:
                ms = firsts.get((key, d, day), [])
                if count[(key, d, day)]:
                    t[day] = [min(ms) if ms else None, max(ms) if ms else None, count[(key, d, day)]]
            hs = signs[(key, d)].most_common(1)[0][0] if signs[(key, d)] else ''
            out.setdefault(key, {'dirs': []})['dirs'].append({'h': hs, 'stops': [s for _, s in sorted(seqs[tid])], 't': t})
        return out

    def weekday_trips(self):
        per = collections.Counter(info[1] for tid, info in self.trip.items() if 'wd' in info[5] and tid in self.first)
        return sum(per.values()), dict(per)


def build(cid):
    name, plate, province = CITIES[cid]
    feed = FEEDS.get(cid, {})
    p = feed.get('path') or os.path.join(KK_DATA, cid)
    stops = list(rows(p, 'stops.txt'))
    if not stops:
        return None, f'{name}: no stops, skipped'

    agencies = {r['agency_id']: r['agency_name'] for r in rows(p, 'agency.txt')}
    routes = {r['route_id']: r for r in rows(p, 'routes.txt')}
    trips = list(rows(p, 'trips.txt'))

    # Which shape is drawn for each line and direction: the most used one, from trips.
    # Feeds without trips name shapes "<route_id><direction>", so they are linked by name.
    best_shape = {}
    if trips:
        use = collections.Counter((t['route_id'], t['direction_id'] or '0', t['shape_id']) for t in trips if t['shape_id'])
        for (rid, d, sid), _ in use.most_common():
            best_shape.setdefault((rid, d), sid)
    shape_ids = set()
    pts = collections.defaultdict(list)
    for r in rows(p, 'shapes.txt'):
        pts[r['shape_id']].append((int(r['shape_pt_sequence']), float(r['shape_pt_lat']), float(r['shape_pt_lon'])))
        shape_ids.add(r['shape_id'])
    # The same name link covers lines that have a drawn route but no trips (no timetable in the feed).
    for sid in sorted(shape_ids):
        rid, d = sid[:-1], sid[-1]
        if rid in routes:
            best_shape.setdefault((rid, d), sid)

    lat0 = sum(float(s['stop_lat']) for s in stops) / len(stops)
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540

    features = []
    stop_drawn = set()
    for (rid, d), sid in sorted(best_shape.items()):
        seq = sorted(pts.get(sid, []))
        if len(seq) < 2:
            continue
        keep = rdp([(lon * kx, lat * ky) for _, lat, lon in seq], SIMPLIFY_M)
        r = routes[rid]
        color, gtfs_color = map_color(r.get('route_color'))
        features.append({
            'type': 'Feature',
            # 'color' is for drawing on the dark map; 'gtfsColor' is the feed's own value.
            'properties': {'line': r['route_short_name'], 'dir': int(d) if d.isdigit() else 0,
                           'color': color, 'gtfsColor': gtfs_color, 'agency': r['agency_id'],
                           'broken': shape_is_broken(seq, (r.get('route_type') or '3').strip(), sid.endswith('_stops'))},
            'geometry': {'type': 'LineString', 'coordinates': [[round(seq[i][2], 5), round(seq[i][1], 5)] for i in keep]},
        })
        if sid.endswith('_stops'):   # drawn stop to stop (no route drawing in the feed); counted per line below
            stop_drawn.add((r['route_short_name'], r['agency_id']))
    drawn_routes = {rid for (rid, _d) in best_shape if len(pts.get(best_shape[(rid, _d)], [])) >= 2}

    # Lines for the search: number, title-cased name, operator and the box around both directions.
    line_box = {}
    broken_keys = {(f['properties']['line'], f['properties']['agency']) for f in features if f['properties']['broken']}
    for feat in features:
        key = (feat['properties']['line'], feat['properties']['agency'])
        xs = [c[0] for c in feat['geometry']['coordinates']]
        ys = [c[1] for c in feat['geometry']['coordinates']]
        b = line_box.get(key, [min(xs), min(ys), max(xs), max(ys)])
        line_box[key] = [min(b[0], min(xs)), min(b[1], min(ys)), max(b[2], max(xs)), max(b[3], max(ys))]
    lines = []
    for rid in sorted(drawn_routes, key=lambda x: (routes[x]['route_short_name'].zfill(6), x)):
        r = routes[rid]
        b = line_box.get((r['route_short_name'], r['agency_id']))
        if b and not any(l['line'] == r['route_short_name'] and l['operator'] == f"{cid}-{r['agency_id']}" for l in lines):
            entry = {'line': r['route_short_name'], 'name': tr_title(r['route_long_name']),
                     'operator': f"{cid}-{r['agency_id']}", 'bounds': [[b[0], b[1]], [b[2], b[3]]],
                     'type': int((r.get('route_type') or '3').strip() or 3)}  # GTFS: 0 tram, 1 metro, 2 rail, 3 bus, 4 ferry, 7 funicular
            if (r['route_short_name'], r['agency_id']) in broken_keys:
                entry['broken'] = True
            lines.append(entry)

    # Stops along each line, in order, from one trip per direction (needs stop_times). The same pass
    # gathers the timetable facts for the line and stop pages (see timetable_facts).
    line_stops = {}
    seqs = collections.defaultdict(list)
    wanted_trip = {}
    tt = None
    if trips and has(p, 'stop_times.txt'):
        for t in trips:
            k = (t['route_id'], t['direction_id'] or '0')
            if best_shape.get(k) == t['shape_id'] and k not in wanted_trip:
                wanted_trip[k] = t['trip_id']
        wanted_ids = set(wanted_trip.values())
        tt = TimetablePass(routes, trips, read_days(p))
        for r in rows(p, 'stop_times.txt'):
            if r['trip_id'] in wanted_ids:
                seqs[r['trip_id']].append((int(r['stop_sequence']), r['stop_id']))
            tt.add(r)
        for (rid, d), tid in wanted_trip.items():
            r = routes[rid]
            bucket = line_stops.setdefault(f"{r['agency_id']}|{r['route_short_name']}", [])
            bucket.extend(s for _, s in sorted(seqs[tid]) if s not in bucket)
    stop_info = {s['stop_id']: s for s in stops}
    used = {s for ids in line_stops.values() for s in ids}
    stops_file = None
    if line_stops:
        stop_out = {sid: [round(float(stop_info[sid]['stop_lon']), 6), round(float(stop_info[sid]['stop_lat']), 6),
                          clean_stop_name(stop_info[sid]['stop_name'])] for sid in sorted(used) if sid in stop_info}
        stops_file = f'data/stops-{cid}.json'
        with open(os.path.join(OUT, os.path.basename(stops_file)), 'w', encoding='utf-8') as f:
            json.dump({'stops': stop_out, 'lines': line_stops}, f, ensure_ascii=False, separators=(',', ':'))

    # Timetable facts for the line and stop pages (sehir/isletme/hat/durak.html).
    detail_file, buckets, wd_trips, op_trips = None, 0, None, {}
    if tt and line_stops:
        detail = tt.line_detail(wanted_trip, seqs, line_stops)
        detail_file = f'data/detail-{cid}.json'
        with open(os.path.join(OUT, os.path.basename(detail_file)), 'w', encoding='utf-8') as f:
            json.dump({'lines': detail}, f, ensure_ascii=False, separators=(',', ':'))
        at_stop = {s: v for s, v in tt.stop_rows().items() if s in used}
        buckets = max(1, math.ceil(len(at_stop) / STOPS_PER_BUCKET))
        parts = [{} for _ in range(buckets)]
        for s, v in at_stop.items():
            parts[bucket_of(s, buckets)][s] = v
        os.makedirs(os.path.join(OUT, f'times-{cid}'), exist_ok=True)
        for i, part in enumerate(parts):
            with open(os.path.join(OUT, f'times-{cid}', f'{i}.json'), 'w', encoding='utf-8') as f:
                json.dump(part, f, ensure_ascii=False, separators=(',', ':'))
        wd_trips, op_trips = tt.weekday_trips()
    op_stops = collections.defaultdict(set)
    for key, ids in line_stops.items():
        op_stops[key.split('|')[0]].update(ids)

    per_agency = collections.Counter(routes[rid]['agency_id'] for rid in drawn_routes)
    operators = []
    # Most lines first; equal counts by agency id, so every build lists them in the same order.
    for aid, n in sorted(per_agency.items(), key=lambda kv: (-kv[1], kv[0].zfill(6))):
        op = {'id': f'{cid}-{aid}', 'lines': n,
              'name': AGENCY_NAMES.get(cid, {}).get(aid) or tr_title(agencies.get(aid, aid))}
        if op_stops.get(aid):
            op['stops'] = len(op_stops[aid])
        if aid in op_trips:
            op['weekdayTrips'] = op_trips[aid]
        # An operator's logo is shown only if its file was added (following the operator's brand guidelines).
        logo = f"assets/operators/{op['id']}.png"
        if os.path.exists(os.path.join(ROOT, logo)):
            op['logo'] = logo
        operators.append(op)
    # A single placeholder "Kentkart Agency" says nothing about who runs the buses; leave it out of the search.
    operators = [o for o in operators if fold_name(o['name']) != 'kentkart agency']

    lats = sorted(float(s['stop_lat']) for s in stops)
    lons = sorted(float(s['stop_lon']) for s in stops)
    # Bounds from the 1st-99th percentile, so a stray far-away stop doesn't zoom the map out.
    lo, hi = int(len(lats) * 0.01), max(int(len(lats) * 0.99) - 1, 0)
    lines_file = None
    if features:
        lines_file = f'data/lines-{cid}.geojson'
        with open(os.path.join(OUT, os.path.basename(lines_file)), 'w', encoding='utf-8') as f:
            json.dump({'type': 'FeatureCollection', 'features': features}, f, ensure_ascii=False, separators=(',', ':'))
    validity = None
    cal = list(rows(p, 'calendar.txt'))
    if cal:
        validity = [min(c['start_date'] for c in cal), max(c['end_date'] for c in cal)]
    city = {
        'id': cid, 'name': name, 'plate': plate, 'province': province,
        'lines': len(lines), 'stops': len(stops), 'validity': validity,
        'brokenLines': sum(1 for l in lines if l.get('broken')),
        # The marker sits at the median stop, which is always where the stops are (a box's middle can be at sea).
        'center': [round(lons[len(lons) // 2], 5), round(lats[len(lats) // 2], 5)],
        'bounds': [[round(lons[lo], 5), round(lats[lo], 5)], [round(lons[hi], 5), round(lats[hi], 5)]],
        'operators': operators, 'lineList': lines,
        'linesFile': lines_file, 'stopsFile': stops_file,
    }
    if feed.get('source'):
        city['source'] = feed['source']
    # Lines drawn stop to stop (straight between stops), shown on the city page.
    n_stop_drawn = sum(1 for l in lines if (l['line'], agency_of(l['operator'])) in stop_drawn)
    if n_stop_drawn:
        city['stopDrawnLines'] = n_stop_drawn
    if detail_file:
        # detailFile: per line and direction, its stops and first/last departures; times-<id>/<n>.json:
        # per stop, the lines leaving it (split into timesBuckets files, see bucket_of).
        city.update({'detailFile': detail_file, 'timesBuckets': buckets, 'weekdayTrips': wd_trips})
    nb = city['brokenLines']
    note = (f"{name}: {len(lines)} lines ({nb} broken, {nb / len(lines):.0%})" if lines else f"{name}: no lines") + \
           f", {len(stops)} stops, {len(operators)} operators, stops per line: {'yes' if stops_file else 'no'}"
    return city, note


def agency_of(operator_id):
    return operator_id.split('-', 1)[1]


def fold_name(s):
    return tr_lower(s).strip()


def main():
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):  # old files (the earlier plate-based names included)
        if f.startswith(('lines-', 'stops-', 'detail-')):
            os.remove(os.path.join(OUT, f))
        elif f.startswith('times-'):
            shutil.rmtree(os.path.join(OUT, f))
    cities = []
    for cid in CITIES:
        city, note = build(cid)
        print(note)
        if city:
            cities.append(city)
    cities.sort(key=lambda c: c['name'])
    with open(os.path.join(OUT, 'catalog.json'), 'w', encoding='utf-8') as f:
        json.dump({'version': 2, 'source': SOURCE, 'cities': cities}, f, ensure_ascii=False, separators=(',', ':'))
    # The stop names for the main page's search, from the files just written
    # (loaded by path: the updater runs this script with python -I, which doesn't look in this folder for imports)
    import importlib.util
    spec = importlib.util.spec_from_file_location('build_stopnames', os.path.join(os.path.dirname(os.path.abspath(__file__)), 'build_stopnames.py'))
    stopnames = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stopnames)
    stopnames.main(OUT)


if __name__ == '__main__':
    main()
