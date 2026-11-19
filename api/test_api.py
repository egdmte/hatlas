"""Tests the contribution rules against a throwaway copy of the API (temporary database, port 3299).

Usage:  py -3 -I api/test_api.py
Fake visitors come from different addresses through X-Forwarded-For, as Caddy would send them.
"""
import json, os, sqlite3, subprocess, sys, tempfile, time, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 3299
failures = 0
STATE = None


def call(method, path, ip, body=None, token=None, raw=None):
    headers = {'Content-Type': 'application/json', 'X-Forwarded-For': ip}
    if token:
        headers['X-Hatlas-Token'] = token
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f'http://127.0.0.1:{PORT}{path}', method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def check(cond, msg):
    global failures
    failures += not cond
    print(('PASS ' if cond else 'FAIL ') + msg)


OLD_SCHEMA = '''
CREATE TABLE contributors (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE, created TEXT NOT NULL);
CREATE TABLE suggestions (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('access', 'name', 'report')),
  city TEXT NOT NULL, target_type TEXT NOT NULL CHECK (target_type IN ('stop', 'line')), target TEXT NOT NULL,
  payload TEXT NOT NULL, contributor INTEGER NOT NULL REFERENCES contributors(id), net_hash TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'live', 'rejected', 'withdrawn', 'removed')),
  created TEXT NOT NULL, decided TEXT, note TEXT);
CREATE TABLE votes (
  suggestion INTEGER NOT NULL REFERENCES suggestions(id), contributor INTEGER NOT NULL REFERENCES contributors(id),
  net_hash TEXT, vote TEXT NOT NULL CHECK (vote IN ('yes', 'no', 'unsure')), created TEXT NOT NULL,
  PRIMARY KEY (suggestion, contributor));
INSERT INTO contributors VALUES (1, '~2026-00001', 'x', '2026-11-18T00:00:00+00:00');
INSERT INTO suggestions VALUES (1, 'name', 'kocaeli', 'stop', '30263', '{"name": "Eski Ad Testi"}', 1, NULL, 'live',
  '2026-11-18T00:00:00+00:00', '2026-11-18T01:00:00+00:00', NULL);
INSERT INTO votes VALUES (1, 1, NULL, 'unsure', '2026-11-18T00:30:00+00:00');
'''


def main():
    global STATE, PORT
    state = STATE = tempfile.mkdtemp()
    old = sqlite3.connect(os.path.join(state, 'hatlas.db'))
    old.executescript(OLD_SCHEMA)
    old.close()
    # The rules themselves, without the day's wait (checked separately below)
    env = dict(os.environ, HATLAS_API_PORT=str(PORT), HATLAS_STATE=state, HATLAS_SITE_DATA=os.path.join(ROOT, 'data'),
               HATLAS_PUBLISH_AFTER_HOURS='0', HATLAS_PROMOTE_EVERY='0')
    proc = subprocess.Popen([sys.executable, '-I', os.path.join(ROOT, 'api', 'hatlas_api.py')], env=env)
    time.sleep(1.5)
    try:
        run()
    finally:
        proc.terminate()
        proc.wait()
        con = sqlite3.connect(os.path.join(state, 'hatlas.db'))
        print('ip_log rows:', con.execute('SELECT count(*) FROM ip_log').fetchone()[0])
        con.close()
    # The 24-hour wait before anything goes live, on a fresh database
    PORT = 3298
    STATE = tempfile.mkdtemp()
    env = dict(env, HATLAS_API_PORT=str(PORT), HATLAS_STATE=STATE, HATLAS_PUBLISH_AFTER_HOURS='24')
    proc = subprocess.Popen([sys.executable, '-I', os.path.join(ROOT, 'api', 'hatlas_api.py')], env=env)
    time.sleep(1.5)
    try:
        waiting()
    finally:
        proc.terminate()
        proc.wait()
    print('all passed' if not failures else f'{failures} FAILED')
    sys.exit(1 if failures else 0)


def run():
    users = {}
    for n, ip in [('A', '10.0.1.5'), ('B', '10.0.2.5'), ('B2', '10.0.2.9'), ('C', '10.0.3.5'), ('D', '10.0.4.5'), ('E', '2001:db8:1::1')]:
        s, r = call('POST', '/api/hello', ip, {})
        users[n] = (r['token'], ip)
    check(r['name'].startswith('~20') and len(r['name']) == 11, f'temporary name {r["name"]}')
    s, r = call('POST', '/api/hello', users['A'][1], {}, users['A'][0])
    check('token' not in r, 'hello with a token returns the same name, no new token')

    tA, ipA = users['A']
    stop = {'kind': 'access', 'city': 'kocaeli', 'targetType': 'stop', 'target': '30262'}
    s, r = call('POST', '/api/suggest', ipA, {**stop, 'payload': {'facts': {'shelter': 'yes', 'bogus': 'yes'}}}, tA)
    check(s == 200 and r['payload'] == {'facts': {'shelter': 'yes'}}, 'suggestion accepted, unknown fact dropped')
    sid = r['id']
    check(call('POST', '/api/suggest', ipA, {**stop, 'target': '999999', 'payload': {'facts': {'shelter': 'yes'}}}, tA)[0] == 400, 'unknown stop refused')
    line = {'kind': 'report', 'city': 'kocaeli', 'targetType': 'line', 'target': '78|440'}
    check(call('POST', '/api/suggest', ipA, {**line, 'payload': {'type': 'works', 'text': 'kısa'}}, tA)[0] == 400, 'too-short report refused')
    check(call('POST', '/api/suggest', ipA, {**line, 'payload': {'type': 'works', 'text': 'Yol çalışması var, iki hafta', 'source': 'javascript:alert(1)'}}, tA)[0] == 400, 'non-https source refused')
    check(call('POST', '/api/suggest', ipA, {**line, 'target': '78|NOPE', 'payload': {'type': 'works', 'text': 'Yol çalışması var, iki hafta'}}, tA)[0] == 400, 'unknown line refused')
    check(call('POST', '/api/suggest', ipA, {**stop, 'payload': {'facts': {'shelter': 'yes'}}})[0] == 401, 'no token refused')
    check(call('POST', f'/api/vote/{sid}', ipA, {'vote': 'yes'}, tA)[0] == 403, 'no vote on your own suggestion')

    tB, ipB = users['B']
    tB2, ipB2 = users['B2']
    tC, ipC = users['C']
    tE, ipE = users['E']
    s, r = call('POST', f'/api/vote/{sid}', ipB, {'vote': 'yes'}, tB)
    check(r['votes']['yes'] == 1 and r['status'] == 'open', 'vote 1 counted')
    s, r = call('POST', f'/api/vote/{sid}', ipB2, {'vote': 'yes'}, tB2)
    check(r['votes']['yes'] == 1, 'a second name on the same /24 counts once')
    s, r = call('POST', f'/api/vote/{sid}', ipC, {'vote': 'yes'}, tC)
    check(r['votes']['yes'] == 2 and r['status'] == 'open', 'vote 2, still open')
    s, r = call('GET', '/api/stop/kocaeli/30262', ipC)
    check(r['waiting'] == 1 and r['facts'] == {}, 'stop view: 1 waiting, nothing live yet')
    s, r = call('POST', f'/api/vote/{sid}', ipE, {'vote': 'yes'}, tE)
    check(r['status'] == 'live', 'the third connection (IPv6) publishes it')
    s, r = call('GET', '/api/stop/kocaeli/30262', ipC)
    check(r['facts'].get('shelter', {}).get('value') == 'yes', 'stop view shows the live fact')
    check(call('POST', f'/api/vote/{sid}', users['D'][1], {'vote': 'no'}, users['D'][0])[0] == 409, 'no votes once decided')

    s, r = call('POST', '/api/suggest', ipB, {**stop, 'kind': 'name', 'payload': {'name': '  Mezbahane   Üst  '}}, tB)
    check(r['payload']['name'] == 'Mezbahane Üst', 'name spaces tidied')
    n2 = r['id']
    s, r = call('POST', f'/api/vote/{n2}', ipA, {'vote': 'yes'}, tA)
    s, r = call('POST', f'/api/vote/{n2}', ipA, {'vote': 'no'}, tA)
    check(r['votes'] == {'yes': 0, 'no': 1, 'unsure': 0}, 'changing your vote replaces it')
    for u in ('C', 'D'):
        s, r = call('POST', f'/api/vote/{n2}', users[u][1], {'vote': 'no'}, users[u][0])
    check(r['status'] == 'rejected', '3 "yanlış" from 3 connections reject it')

    s, r = call('POST', '/api/suggest', ipC, {**line, 'payload': {'type': 'works', 'text': 'Yol çalışması var, iki hafta sürecek', 'source': 'https://example.org/duyuru'}}, tC)
    rid = r['id']
    s, r = call('GET', '/api/open?city=kocaeli', ipC, token=tC)
    check(all(i['id'] != rid for i in r['items']), 'the open list hides your own')
    s, r = call('GET', '/api/open?city=kocaeli', ipA, token=tA)
    check(any(i['id'] == rid for i in r['items']), 'others see it')
    text = json.dumps(r)
    check('net_hash' not in text and '10.0.' not in text, 'no connection hash or IP in answers')
    s, r = call('POST', f'/api/withdraw/{rid}', ipC, {}, tC)
    check(r.get('ok') is True, 'withdraw your own')
    check(call('POST', f'/api/withdraw/{sid}', ipC, {}, tC)[0] == 409, "can't withdraw someone else's")
    s, r = call('POST', '/api/suggest', ipA, {**line, 'payload': {'type': 'not_running', 'text': 'Bu hat Ekim sonunda kaldırıldı'}}, tA)
    pid = r['id']
    check(all(i['id'] != pid for i in call('GET', '/api/reports', ipC)[1]['items']), 'an open report is not among published reports')
    for u in ('B', 'C', 'D'):
        call('POST', f'/api/vote/{pid}', users[u][1], {'vote': 'yes'}, users[u][0])
    s, r = call('GET', '/api/reports?city=kocaeli', ipC)
    got = next((i for i in r['items'] if i['id'] == pid), None)
    check(got is not None and got['about'].get('line') == '440' and got['text'].startswith('Bu hat'), 'a published report is listed with its line')
    check('net_hash' not in json.dumps(r) and '10.0.' not in json.dumps(r), 'no connection hash or IP in reports')
    s, r = call('GET', '/api/mine', ipA, token=tA)
    check(len(r['items']) == 2 and r['items'][0]['status'] == 'live', 'mine lists your suggestion')
    check(call('GET', '/api/__init__', ipA)[0] == 404 and call('GET', '/api/hello', ipA)[0] == 404, 'unknown routes and wrong methods 404')
    check(call('POST', '/api/suggest', ipA, raw=b'x' * 9000, token=tA)[0] == 413, 'large body refused')
    check(call('POST', '/api/suggest', ipA, raw=b'not json', token=tA)[0] == 400, 'bad JSON refused')
    guncelle(users)
    usage(users)


def guncelle(users):
    """Güncelle: a removed stop, a drawn route, a new stop; and the database from before them."""
    r = call('GET', '/api/stop/kocaeli/30263', users['C'][1])[1]
    check((r.get('name') or {}).get('value') == 'Eski Ad Testi', 'old database migrated, its published name kept')
    tE, ipE = users['E']
    voters = [users[u] for u in ('B', 'C', 'D')]

    def publish(sid):
        for t, ip in voters:
            st, r = call('POST', f'/api/vote/{sid}', ip, {'vote': 'yes'}, t)
        return r.get('status')

    cat = json.load(open(os.path.join(ROOT, 'data', 'catalog.json'), encoding='utf-8'))
    (w, so), (e, n) = next(c for c in cat['cities'] if c['id'] == 'kocaeli')['bounds']
    mid = [round((w + e) / 2, 5), round((so + n) / 2, 5)]
    near = lambda i: [round(mid[0] + i * 0.0005, 5), round(mid[1] + i * 0.0003, 5)]

    base = {'kind': 'removed', 'city': 'kocaeli', 'targetType': 'stop', 'target': '30262'}
    check(call('POST', '/api/suggest', ipE, {**base, 'payload': {}}, tE)[0] == 400, 'removed stop needs a note')
    st, r = call('POST', '/api/suggest', ipE, {**base, 'payload': {'text': 'Durak Ekim sonunda kaldırıldı, tabela yok'}}, tE)
    check(st == 200 and publish(r['id']) == 'live', 'removed stop published by three')
    r = call('GET', '/api/stop/kocaeli/30262', ipE)[1]
    check((r.get('removed') or {}).get('text', '').startswith('Durak Ekim'), 'stop view shows it as removed')

    route = {'kind': 'route', 'city': 'kocaeli', 'targetType': 'line', 'target': '78|440'}
    note = 'Köprü çalışması: hat Ankara Caddesi yerine buradan gidiyor'
    check(call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': [mid], 'text': note}}, tE)[0] == 400, 'a route needs two points')
    check(call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': [mid, [0, 0]], 'text': note}}, tE)[0] == 400, 'a point outside the city is refused')
    check(call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': [mid, ['a', 1]], 'text': note}}, tE)[0] == 400, 'a point must be numbers')
    check(call('POST', '/api/suggest', ipE, {**route, 'target': '30262', 'payload': {'points': [mid, near(1)], 'text': note}}, tE)[0] == 400, 'a route is for a line')
    long = [near(i % 100) for i in range(300)]
    st, r = call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': long, 'text': note}}, tE)
    check(st == 200 and len(r['payload']['points']) == 300, '300 points fit in one request')
    check(call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': long + [mid], 'text': note}}, tE)[0] in (400, 413), '301 points refused')
    st, r = call('POST', '/api/suggest', ipE, {**route, 'payload': {'points': [mid, near(1), near(2)], 'text': note, 'source': 'https://example.org/x'}}, tE)
    rid = r['id']
    check(call('GET', f'/api/suggestion/{rid}', ipE)[0] == 200, 'an open route can be looked at before voting')
    check(publish(rid) == 'live', 'route published by three')
    r = call('GET', '/api/line/kocaeli/78|440', ipE)[1]
    check(any(x['id'] == rid and len(x['points']) == 3 for x in r.get('routes', [])), 'line view lists the published route')

    new = {'kind': 'newstop', 'city': 'kocaeli', 'targetType': 'city', 'target': 'kocaeli'}
    good = {'name': 'Yeni Çarşı', 'point': near(3), 'lines': ['78|440', '78|440']}
    check(call('POST', '/api/suggest', ipE, {**new, 'target': 'adana', 'payload': good}, tE)[0] == 400, 'new stop: target must be its city')
    check(call('POST', '/api/suggest', ipE, {**new, 'payload': {**good, 'lines': ['78|NOPE']}}, tE)[0] == 400, 'new stop: unknown line refused')
    check(call('POST', '/api/suggest', ipE, {**new, 'payload': {**good, 'point': [0, 0]}}, tE)[0] == 400, 'new stop: outside the city refused')
    st, r = call('POST', '/api/suggest', ipE, {**new, 'payload': good}, tE)
    check(st == 200 and r['payload']['lines'] == ['78|440'], 'new stop accepted, lines de-duplicated')
    nid = r['id']
    r = call('GET', '/api/city/kocaeli', ipE)[1]
    check(r['waiting'] >= 1 and not any(x['id'] == nid for x in r['newStops']), 'an open new stop only counts as waiting')
    check(publish(nid) == 'live', 'new stop published by three')
    r = call('GET', '/api/city/kocaeli', ipE)[1]
    check(any(x['id'] == nid and x['name'] == 'Yeni Çarşı' for x in r['newStops']), 'city view lists the new stop')
    r = call('GET', '/api/reports', ipE)[1]
    kinds = {x['kind'] for x in r['items']}
    check({'removed', 'route', 'newstop'} <= kinds, 'Sorunlar lists the published updates')
    check(call('GET', '/api/suggestion/999999', ipE)[0] == 404 and call('GET', '/api/suggestion/abc', ipE)[0] == 404, 'unknown suggestion 404')
    check('net_hash' not in json.dumps(r) and '10.0.' not in json.dumps(r), 'no connection hash or IP in updates')



def usage(users):
    """Opt-in usage counts: only the site's own pages and data, counted per day, never tied to anyone."""
    tA, ip = users['A']
    con = sqlite3.connect(os.path.join(STATE, 'hatlas.db'))
    logged = con.execute('SELECT count(*) FROM ip_log').fetchone()[0]
    ok = lambda body, token=None: call('POST', '/api/usage', ip, body, token)[0] == 200
    bad = lambda body: call('POST', '/api/usage', ip, body)[0] == 400
    check(ok({'event': 'view', 'page': 'home'}), 'usage: a home page view is counted')
    check(ok({'event': 'view', 'page': 'stop', 'city': 'kocaeli', 'kind': 'stop', 'target': '30262'}), 'usage: a stop view')
    check(ok({'event': 'view', 'page': 'stop', 'city': 'kocaeli', 'kind': 'stop', 'target': '30262'}, tA), 'usage: a token is ignored, not refused')
    check(ok({'event': 'map', 'page': 'home', 'city': 'kocaeli', 'kind': 'line', 'target': '78|440'}), 'usage: a line on the map')
    check(ok({'event': 'map', 'page': 'home', 'city': 'kocaeli', 'kind': 'operator', 'target': '78'}), 'usage: an operator on the map')
    check(ok({'event': 'download', 'page': 'catalog', 'kind': 'file', 'target': 'lines-kocaeli.geojson'}), 'usage: a download')
    check(ok({'event': 'search_empty', 'page': 'home', 'q': '  Bahçeşehir   Metro '}), 'usage: a search that found nothing')
    check(bad({'event': 'view', 'page': 'stop', 'city': 'kocaeli', 'kind': 'stop', 'target': '999999'}), 'usage: unknown stop refused')
    check(bad({'event': 'view', 'page': 'nowhere'}) and bad({'event': 'click', 'page': 'home'}), 'usage: unknown page or event refused')
    check(bad({'event': 'view', 'page': 'home', 'city': 'atlantis'}), 'usage: unknown city refused')
    check(bad({'event': 'view', 'page': 'home', 'target': 'free text'}), 'usage: free text as a target refused')
    check(bad({'event': 'download', 'page': 'catalog', 'kind': 'file', 'target': '../api/hatlas.db'})
          and bad({'event': 'download', 'page': 'catalog', 'kind': 'file', 'target': 'nope.json'}), 'usage: only existing data files')
    for q in ('ali@example.com', '0532 1234567', '05321234567', 'www.site', 'x'):
        check(bad({'event': 'search_empty', 'page': 'home', 'q': q}), f'usage: search "{q}" not kept')
    check(bad({'event': 'view', 'page': 'home', 'q': 'secret'}) is False, 'usage: q ignored outside search_empty')
    rows = con.execute('SELECT * FROM usage').fetchall()
    cols = [d[0] for d in con.execute('SELECT * FROM usage').description]
    stop = [r for r in rows if r[cols.index('kind')] == 'stop']
    check(len(stop) == 1 and stop[0][cols.index('n')] == 2, 'usage: two stop views are one row counting 2')
    check(any(r[cols.index('q')] == 'bahçeşehir metro' for r in rows), 'usage: the search is kept tidied and lower case')
    check(not any(r[cols.index('q')] == 'secret' for r in rows), 'usage: no free text kept from other events')
    check(cols == ['day', 'event', 'page', 'city', 'kind', 'target', 'q', 'n'], 'usage: no column for an IP, token or hash')
    check(con.execute('SELECT count(*) FROM ip_log').fetchone()[0] == logged, 'usage: nothing written to the IP log')
    con.close()



def waiting():
    """Three "doğru" are not enough on their own: a suggestion goes live once it has also been open for a day."""
    users = {}
    for n, ip in [('A', '10.1.1.5'), ('B', '10.1.2.5'), ('C', '10.1.3.5'), ('D', '10.1.4.5')]:
        users[n] = (call('POST', '/api/hello', ip, {})[1]['token'], ip)
    tA, ipA = users['A']
    st, r = call('POST', '/api/suggest', ipA, {'kind': 'name', 'city': 'kocaeli', 'targetType': 'stop', 'target': '30262',
                                               'payload': {'name': 'Bekleyen Ad'}}, tA)
    sid = r['id']
    for u in ('B', 'C', 'D'):
        st, r = call('POST', f'/api/vote/{sid}', users[u][1], {'vote': 'yes'}, users[u][0])
    check(r['status'] == 'open' and r.get('ready') is True and r.get('publishAt'), 'wait: three "doğru" within a day keep it open, marked ready')
    check(call('GET', '/api/stop/kocaeli/30262', ipA)[1]['name'] is None, 'wait: the stop page does not show it yet')
    con = sqlite3.connect(os.path.join(STATE, 'hatlas.db'))
    con.execute("UPDATE suggestions SET created = '2026-01-01T00:00:00+00:00' WHERE id = ?", (sid,))
    con.commit()
    con.close()
    call('GET', '/api/health', ipA)   # any request lets the API publish what has waited long enough
    r = call('GET', f'/api/suggestion/{sid}', ipA)[1]
    check(r['status'] == 'live' and 'ready' not in r, 'wait: once the day is over it goes live by itself')
    check(call('GET', '/api/stop/kocaeli/30262', ipA)[1]['name']['value'] == 'Bekleyen Ad', 'wait: then the stop page shows it')
    st, r = call('POST', '/api/suggest', ipA, {'kind': 'name', 'city': 'kocaeli', 'targetType': 'stop', 'target': '30263',
                                               'payload': {'name': 'Yanlış Ad'}}, tA)
    nid = r['id']
    for u in ('B', 'C', 'D'):
        st, r = call('POST', f'/api/vote/{nid}', users[u][1], {'vote': 'no'}, users[u][0])
    check(r['status'] == 'rejected', 'wait: three "yanlış" still reject at once')


if __name__ == '__main__':
    main()
