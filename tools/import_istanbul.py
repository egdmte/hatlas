"""Turns İBB's İETT GTFS download (loose CSV files) into a clean GTFS folder that build_catalog.py reads.

Usage:  py -3 -I tools/import_istanbul.py [source folder] [output folder] [routes geojson]
        defaults: ~/Downloads  ->  ~/Downloads/istanbul-gtfs,
                  routes from ~/Downloads/istanbul-iett-guzergah/iett-hat-guzergahlari.geojson if it is there

The source folder needs agency.csv, calendar.csv, routes.csv, trips.csv, stops.csv and stop_times.zip
(the zip, not stop_times.csv: a CSV opened in Excel stops at 1,048,576 rows and loses the rest).

What it repairs (seen in the 2026-11-18 download):
  - Mixed separators: agency.csv uses commas, the rest semicolons. Output is plain comma GTFS, UTF-8.
  - routes.csv names are double-encoded ("KADIKÃ–Y" for "KADIKÖY"); fixed byte by byte.
  - A few routes.csv rows are shifted (route_type sits in route_desc) or broken over two lines.
  - stops.csv coordinates have dots as thousands separators ("410.191.700.005.564" = 41.01917...);
    every Istanbul coordinate has two digits before the decimal point, so the dots are dropped and
    the point goes back after the second digit. Stops that land outside Istanbul are left out.
  - There is no shapes.txt. For every line and direction the most-run stop pattern is the one drawn, and its
    trips get that shape_id; other variants keep none. Its drawing comes from İBB's separate route dataset
    "İETT Hat Güzergahları Verisi" (GeoJSON; GUZERGAH_KODU = routes.csv route_code, e.g. "133P_D_D1854"), but only
    where that route fits today's stops (see ROUTE_FIT_*); otherwise it is drawn stop to stop, straight between
    stops, and its shape_id ends in "_stops" so build_catalog.py knows.
The files are read as data only; nothing in them is executed.
"""
import csv, io, json, math, os, sys, zipfile, collections

SRC = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser('~/Downloads')
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser('~/Downloads/istanbul-gtfs')
ROUTES = sys.argv[3] if len(sys.argv) > 3 else os.path.expanduser('~/Downloads/istanbul-iett-guzergah/iett-hat-guzergahlari.geojson')

# A drawn route is used only if it fits the timetable's stops: at least ROUTE_FIT_SHARE of the stops within
# ROUTE_FIT_M of it, and the first and last stops within ROUTE_END_M. The routes are from March 2026 like the
# timetable, but a line that changed since would otherwise be drawn along its old way.
ROUTE_FIT_M = 120
ROUTE_FIT_SHARE = 0.8
ROUTE_END_M = 300

# Istanbul with some room around it (lat, lon), for throwing out stops with broken coordinates.
BOX = (40.70, 27.90, 41.70, 29.95)


def read(name):
    with open(os.path.join(SRC, name), encoding='utf-8-sig', newline='') as f:
        text = f.read()
    first = text.split('\n', 1)[0]
    delim = ';' if first.count(';') > first.count(',') else ','
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


def write(name, fields, records):
    with open(os.path.join(OUT, name), 'w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(fields)
        for r in records:
            w.writerow([r.get(k, '') for k in fields])


def unmangle(s):
    """UTF-8 text that was decoded as Windows-1252 (or Latin-1) and saved again. Leaves good text alone."""
    if not s or s.isascii():
        return s
    b = bytearray()
    for c in s:
        if ord(c) < 256:
            b.append(ord(c))
        else:
            try:
                b += c.encode('cp1252')
            except UnicodeEncodeError:
                return s
    try:
        return b.decode('utf-8')
    except UnicodeDecodeError:
        return s


def coord(s):
    digits = (s or '').replace('.', '').replace(',', '').strip()
    if len(digits) < 3 or not digits.lstrip('-').isdigit():
        return None
    return float(digits[:2] + '.' + digits[2:])


def read_routes(codes):
    """GUZERGAH_KODU -> [(lat, lon)] for the wanted codes, read one feature per line (the file is 250 MB)."""
    out = {}
    if not os.path.exists(ROUTES):
        print('no route drawings found at', ROUTES, '- every line is drawn stop to stop')
        return out
    with open(ROUTES, encoding='utf-8-sig') as f:
        for line in f:
            line = line.strip().rstrip(',')
            if not line.startswith('{') or '"Feature"' not in line[:40]:
                continue
            ft = json.loads(line)
            code = (ft.get('properties') or {}).get('GUZERGAH_KODU', '')
            g = ft.get('geometry') or {}
            if code not in codes or not g:
                continue
            parts = [g['coordinates']] if g.get('type') == 'LineString' else g.get('coordinates', []) if g.get('type') == 'MultiLineString' else []
            pts = [(float(c[1]), float(c[0])) for part in parts for c in part]
            if len(pts) >= 2:
                out[code] = pts
    return out


def route_fits(route, stops):
    """'fits', or why not. route and stops are [(lat, lon)]; the route is turned round if it runs backwards."""
    if len(stops) < 2:
        return 'too few stops'
    lat0 = stops[0][0]
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    xy = lambda p: (p[1] * kx, p[0] * ky)
    # Points every ~25 m along the route, in 100 m cells, so each stop only looks at its neighbourhood.
    cells = collections.defaultdict(list)
    pts = [xy(p) for p in route]
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        n = max(1, int(math.hypot(bx - ax, by - ay) // 25))
        for i in range(n + 1):
            x, y = ax + (bx - ax) * i / n, ay + (by - ay) * i / n
            cells[(int(x // 100), int(y // 100))].append((x, y))

    def near(p):
        x, y = xy(p)
        cx, cy = int(x // 100), int(y // 100)
        best = float('inf')
        for i in (-2, -1, 0, 1, 2):
            for j in (-2, -1, 0, 1, 2):
                for qx, qy in cells.get((cx + i, cy + j), ()):
                    best = min(best, math.hypot(qx - x, qy - y))
        return best

    close = sum(1 for s in stops if near(s) <= ROUTE_FIT_M)
    if close < ROUTE_FIT_SHARE * len(stops):
        return 'off the stops'
    if near(stops[0]) > ROUTE_END_M or near(stops[-1]) > ROUTE_END_M:
        return 'ends elsewhere'
    d = lambda a, b: math.hypot(xy(a)[0] - xy(b)[0], xy(a)[1] - xy(b)[1])
    if d(stops[0], route[-1]) + d(stops[-1], route[0]) < d(stops[0], route[0]) + d(stops[-1], route[-1]):
        route.reverse()
    return 'fits'


def main():
    os.makedirs(OUT, exist_ok=True)

    agency = read('agency.csv')
    calendar = read('calendar.csv')
    write('agency.txt', ['agency_id', 'agency_name', 'agency_url', 'agency_timezone', 'agency_lang'], agency)
    write('calendar.txt', ['service_id', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
                           'sunday', 'start_date', 'end_date'], calendar)

    routes, last = [], None
    for r in read('routes.csv'):
        r = {k: unmangle(v or '') for k, v in r.items() if k}
        if not r['route_id']:  # the rest of the row above, broken over two lines
            if last is not None and not last['route_code']:
                last['route_code'] = r.get('route_short_name', '')
            continue
        if not r['route_type'] and r['route_desc'].isdigit():  # shifted one column to the right
            r['route_type'], r['route_desc'] = r['route_desc'], r['route_code']
            r['route_code'] = ''
        r['route_type'] = r['route_type'] or '3'
        r['agency_id'] = r['agency_id'] or '1'
        routes.append(r)
        last = r
    route_by_id = {r['route_id']: r for r in routes}

    stops, dropped = [], 0
    for s in read('stops.csv'):
        lat, lon = coord(s.get('stop_lat')), coord(s.get('stop_lon'))
        if lat is None or lon is None or not (BOX[0] <= lat <= BOX[2] and BOX[1] <= lon <= BOX[3]):
            dropped += 1
            continue
        stops.append({'stop_id': s['stop_id'], 'stop_code': s.get('stop_code', ''), 'stop_name': s['stop_name'].strip(),
                      'stop_desc': s.get('stop_desc', ''), 'stop_lat': f'{lat:.7f}', 'stop_lon': f'{lon:.7f}',
                      'location_type': s.get('location_type') or '0'})
    pos = {s['stop_id']: (s['stop_lat'], s['stop_lon']) for s in stops}
    write('stops.txt', ['stop_id', 'stop_code', 'stop_name', 'stop_desc', 'stop_lat', 'stop_lon', 'location_type'], stops)

    trips = [t for t in read('trips.csv') if t['route_id'] in route_by_id]

    # stop_times: copied as is, and each trip's stop pattern collected on the way.
    pattern = collections.defaultdict(list)
    zpath = os.path.join(SRC, 'stop_times.zip')
    with zipfile.ZipFile(zpath) as z, z.open('stop_times.txt') as raw, \
            open(os.path.join(OUT, 'stop_times.txt'), 'w', encoding='utf-8', newline='') as out:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline=''))
        fields = ['trip_id', 'arrival_time', 'departure_time', 'stop_id', 'stop_sequence', 'timepoint']
        w = csv.writer(out)
        w.writerow(fields)
        n = 0
        for r in reader:
            w.writerow([r.get(k, '') for k in fields])
            pattern[r['trip_id']].append((int(r['stop_sequence']), sys.intern(r['stop_id'])))
            n += 1
    pattern = {tid: tuple(s for _, s in sorted(v)) for tid, v in pattern.items()}

    # The drawn route per line and direction: the stop pattern most trips run.
    use = collections.Counter()
    for t in trips:
        p = pattern.get(t['trip_id'])
        if p:
            line = route_by_id[t['route_id']]['route_short_name']
            use[(line, t['direction_id'] or '0', t['route_id'], p)] += 1
    main_of = {}
    for (line, d, rid, p), _ in use.most_common():
        main_of.setdefault((line, d), (rid, p))

    wanted = {route_by_id[rid].get('route_code', ''): (line, d) for (line, d), (rid, _p) in main_of.items()}
    drawn = read_routes({c for c in wanted if c})
    shapes, shape_of, why = [], {}, collections.Counter()
    for (line, d), (rid, p) in sorted(main_of.items()):
        stops_ll = [(float(pos[s][0]), float(pos[s][1])) for s in p if s in pos]
        route = drawn.get(route_by_id[rid].get('route_code', ''))
        verdict = route_fits(route, stops_ll) if route else 'no route'
        why[verdict] += 1
        if verdict == 'fits':
            sid, points = f'{rid}_{d}', route
        else:
            sid, points = f'{rid}_{d}_stops', stops_ll
        shape_of[(rid, p)] = sid
        for seq, (lat, lon) in enumerate(points, 1):
            shapes.append({'shape_id': sid, 'shape_pt_lat': f'{lat:.6f}', 'shape_pt_lon': f'{lon:.6f}', 'shape_pt_sequence': seq})
    for t in trips:
        t['shape_id'] = shape_of.get((t['route_id'], pattern.get(t['trip_id'])), '')
    write('routes.txt', ['route_id', 'agency_id', 'route_short_name', 'route_long_name', 'route_type', 'route_desc'], routes)
    write('trips.txt', ['route_id', 'service_id', 'trip_id', 'trip_headsign', 'direction_id', 'shape_id'], trips)
    write('shapes.txt', ['shape_id', 'shape_pt_lat', 'shape_pt_lon', 'shape_pt_sequence'], shapes)

    lines = {r['route_short_name'] for r in routes}
    missing = {s for p in pattern.values() for s in p} - pos.keys()
    print(f'{len(routes)} route variants, {len(lines)} lines, {len(trips)} trips, {n} stop times')
    print(f'{len(stops)} stops kept, {dropped} dropped (coordinates outside Istanbul)')
    print(f'{len(main_of)} drawn routes; {len(missing)} stops used in stop_times have no coordinates')
    print('drawings: ' + ', '.join(f'{k}: {v}' for k, v in why.most_common()))
    print('written to', OUT)


if __name__ == '__main__':
    main()
