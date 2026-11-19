"""Writes data/stopnames.json: every stop name the site knows, for the main page's search ("durak arayın").

    py -3 tools/build_stopnames.py      (tools/build_catalog.py also runs it after every build)

Reads only the site's own files (data/catalog.json and data/stops-<city>.json), so it can run any time.
One row per stop *place*: the stops of one name within SIDE_RADIUS_M of each other are the two sides of one road
(the stop page shows them as tabs), so they become one result; the same name far away (two "Okul" stops in
different districts) stays two results. Each row: [name, a GTFS stop id of that place, lines through it].
The page loads this file only once someone starts typing (about 240 KB over the wire).
"""
import json, math, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
SIDE_RADIUS_M = 400   # as in js/pages.js


def metres(a, b):
    k = math.cos(math.radians(a[1])) * 111320
    return math.hypot((a[0] - b[0]) * k, (a[1] - b[1]) * 110540)


def main(data_dir=DATA):
    """data_dir: the folder with catalog.json and the stops files (build_catalog.py passes its own output folder,
    which is a staging folder during the daily update)."""
    with open(os.path.join(data_dir, 'catalog.json'), encoding='utf-8') as f:
        catalog = json.load(f)
    out = {}
    for city in catalog['cities']:
        if not city.get('stopsFile'):
            continue
        with open(os.path.join(data_dir, os.path.basename(city['stopsFile'])), encoding='utf-8') as f:
            d = json.load(f)
        lines_at = {}
        for key, ids in d['lines'].items():
            for sid in set(ids):
                lines_at.setdefault(sid, set()).add(key)
        by_name = {}
        for sid, (lon, lat, name) in d['stops'].items():
            by_name.setdefault(name, []).append((sid, (lon, lat)))
        rows = []
        for name, stops in by_name.items():
            places = []   # [first stop id, its point, the lines of every side]
            for sid, pt in sorted(stops):
                place = next((p for p in places if metres(p[1], pt) <= SIDE_RADIUS_M), None)
                if place:
                    place[2] |= lines_at.get(sid, set())
                else:
                    places.append([sid, pt, set(lines_at.get(sid, set()))])
            rows += [[name, sid, len(lines)] for sid, _, lines in places]
        rows.sort(key=lambda r: (-r[2], r[0]))
        out[city['id']] = rows
    path = os.path.join(data_dir, 'stopnames.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'version': 1, 'cities': out}, f, ensure_ascii=False, separators=(',', ':'))
    print(f'stopnames.json: {sum(len(r) for r in out.values())} stops in {len(out)} cities, {os.path.getsize(path) // 1024} KB')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else DATA)
