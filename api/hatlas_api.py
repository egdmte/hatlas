"""Hatlas contributions API: suggestions without an account, checked by everyone ("Bu doğru mu?").

Runs on the VPS as the "hatlas" user behind Caddy (hatlas.avartech.net/api/*, see deploy/setup-hatlas.sh);
Python's standard library and SQLite only. Locally: `py -3 api/hatlas_api.py` (port 3200, ./api/dev-data/),
with tools/serve.py passing /api/* to it.

What people can suggest (user, 2026-11-18): a stop's accessibility facts, a stop's name, and reports (a short note
on a stop or a line); since 2026-11-19 also "Güncelle": a stop that was removed, a line's new route (drawn on the map)
and a new stop (a point, a name and the lines that stop there). Rules:
  - No account: the first visit gets a temporary name like "~2026-48213" and a random token kept in the browser
    (sent as X-Hatlas-Token; never a cookie, so other sites can't act for the visitor).
  - A suggestion goes live at PUBLISH_YES "doğru" votes from that many different connections, with more "doğru"
    than "yanlış" connections, and not before it has been open PUBLISH_AFTER_HOURS (24 h, since 2026-11-19); it is rejected at REJECT_NO "yanlış" connections outnumbering "doğru". A
    connection is the visitor's IPv4 /24 or IPv6 /48, stored only as a salted hash. Nobody votes on their own
    suggestion (same name or same connection); people may change their vote while it is open.
  - The newest live suggestion for the same stop and fact (or name) is the one shown.
  - KVKK: raw IP addresses are kept only in ip_log, for abuse, and deleted after RETENTION_DAYS; connection hashes
    are cleared from decided suggestions after the same time. Nothing else about the visitor is stored.
Everything that comes in is checked against the site's own data (data/catalog.json, stops-<city>.json) and length
limits, stored as data and given back as JSON; the site shows it with textContent only.

Admin (on the server):  sudo -u hatlas python3 /srv/hatlas-api/current/hatlas_api.py admin remove <id> [reason]
                        sudo -u hatlas python3 /srv/hatlas-api/current/hatlas_api.py admin list [n]
                        sudo -u hatlas python3 /srv/hatlas-api/current/hatlas_api.py admin usage [days]
                        sudo -u hatlas python3 /srv/hatlas-api/current/hatlas_api.py admin recent [hours]

Usage statistics (opt-in, js/usage.js): POST /api/usage adds one to a count per day (page, city, line, stop, data file,
or a search that found nothing). No IP, token or connection hash is stored with them; searches go after
USAGE_QUERY_DAYS, counts after USAGE_DAYS.
"""
import datetime, hashlib, http.server, ipaddress, json, math, os, re, secrets, sqlite3, sys, threading, time, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get('HATLAS_API_PORT', '3200'))
STATE = (os.environ.get('HATLAS_STATE') or os.environ.get('STATE_DIRECTORY')
         or ('/var/lib/hatlas' if os.path.isdir('/var/lib/hatlas') else os.path.join(HERE, 'dev-data')))
SITE_DATA = os.environ.get('HATLAS_SITE_DATA') or os.path.join(os.path.dirname(HERE), 'data')
DB_PATH = os.path.join(STATE, 'hatlas.db')

PUBLISH_YES = 3        # user, 2026-11-18: three "doğru" from three different connections
REJECT_NO = 3
# Launch hardening (2026-11-19): nothing goes live before it has been open this long, however fast the votes come.
# Gives the owner a day to see it on "Bu doğru mu?" or `admin recent` and remove it, and makes a burst of fake
# votes from fresh connections useless. Rejections still happen at once. Tests set it with HATLAS_PUBLISH_AFTER_HOURS.
PUBLISH_AFTER_HOURS = float(os.environ.get('HATLAS_PUBLISH_AFTER_HOURS', '24'))
PROMOTE_EVERY = float(os.environ.get('HATLAS_PROMOTE_EVERY', '60'))   # seconds between checks for suggestions whose wait is over
RETENTION_DAYS = 90    # raw IPs and connection hashes (KVKK)
LIMITS = {'suggest': (30, 86400), 'vote': (300, 86400), 'hello': (20, 3600), 'any': (120, 60),
          'usage': (600, 3600)}  # (count, seconds) per connection
MAX_BODY = 8000         # a drawn route; Caddy allows 8 KB
FACTS = ('staff', 'stepfree', 'sidewalk', 'shelter')
VALUES = ('yes', 'no')
REPORT_KINDS = ('works', 'announcement', 'not_running', 'other')
MAX_NAME, MAX_TEXT, MAX_URL = 80, 500, 300
MAX_POINTS = 300       # clicks in a drawn route
MAX_ROUTE_KM = 300
MAX_STOP_LINES = 30
KINDS = ('access', 'name', 'report', 'removed', 'route', 'newstop')
TARGETS = ('stop', 'line', 'city')

# Usage statistics (user, 2026-11-19): only from visitors who said "İzin ver" on the main page's card (js/usage.js).
# Stored as counts per day; never an IP, a token, a connection hash or anything that ties two events together.
USAGE_EVENTS = ('view', 'map', 'search_empty', 'download', 'nearby')
USAGE_PAGES = ('home', 'city', 'operator', 'line', 'stop', 'catalog', 'issues', 'verify', 'contribute', 'privacy', 'photo-rules')
USAGE_KINDS = ('', 'city', 'operator', 'line', 'stop', 'file')
USAGE_DAYS = 400          # counts: a bit over a year, to compare a month with the same month last year
USAGE_QUERY_DAYS = 90     # searches that found nothing
MAX_QUERY = 40


# ---------- Storage ----------
SCHEMA = '''
CREATE TABLE IF NOT EXISTS contributors (
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, token_hash TEXT NOT NULL UNIQUE, created TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('access', 'name', 'report', 'removed', 'route', 'newstop')),
  city TEXT NOT NULL, target_type TEXT NOT NULL CHECK (target_type IN ('stop', 'line', 'city')), target TEXT NOT NULL,
  payload TEXT NOT NULL, contributor INTEGER NOT NULL REFERENCES contributors(id), net_hash TEXT,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'live', 'rejected', 'withdrawn', 'removed')),
  created TEXT NOT NULL, decided TEXT, note TEXT);
CREATE INDEX IF NOT EXISTS suggestions_target ON suggestions(city, target_type, target, status);
CREATE INDEX IF NOT EXISTS suggestions_status ON suggestions(status, created);
CREATE TABLE IF NOT EXISTS votes (
  suggestion INTEGER NOT NULL REFERENCES suggestions(id), contributor INTEGER NOT NULL REFERENCES contributors(id),
  net_hash TEXT, vote TEXT NOT NULL CHECK (vote IN ('yes', 'no', 'unsure')), created TEXT NOT NULL,
  PRIMARY KEY (suggestion, contributor));
CREATE TABLE IF NOT EXISTS ip_log (
  id INTEGER PRIMARY KEY, contributor INTEGER, ip TEXT NOT NULL, action TEXT NOT NULL, created TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ip_log_created ON ip_log(created);
CREATE TABLE IF NOT EXISTS usage (
  day TEXT NOT NULL, event TEXT NOT NULL, page TEXT NOT NULL, city TEXT NOT NULL, kind TEXT NOT NULL,
  target TEXT NOT NULL, q TEXT NOT NULL, n INTEGER NOT NULL,
  PRIMARY KEY (day, event, page, city, kind, target, q));
'''

_local = threading.local()


def db():
    con = getattr(_local, 'con', None)
    if con is None:
        con = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA foreign_keys=ON')
        con.execute('PRAGMA busy_timeout=10000')
        _local.con = con
    return con


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def init():
    os.makedirs(STATE, exist_ok=True)
    migrate()
    db().executescript(SCHEMA)


def migrate():
    """A database from before "Güncelle" checks kind and target_type against the old lists. SQLite can't change a
    CHECK, so the suggestions table is rebuilt once with the new one, keeping every row and id (votes point at them)."""
    c = db()
    row = c.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'suggestions'").fetchone()
    if not row or "'newstop'" in row['sql']:
        return
    new = SCHEMA.split('CREATE TABLE IF NOT EXISTS suggestions (')[1].split(');')[0]
    c.execute('PRAGMA foreign_keys=OFF')
    c.execute('BEGIN IMMEDIATE')
    try:
        c.execute(f'CREATE TABLE suggestions_new ({new})')
        c.execute('INSERT INTO suggestions_new SELECT id, kind, city, target_type, target, payload, contributor, net_hash, '
                  'status, created, decided, note FROM suggestions')
        c.execute('DROP TABLE suggestions')
        c.execute('ALTER TABLE suggestions_new RENAME TO suggestions')
        if c.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('foreign keys broken by the migration')
        c.execute('COMMIT')
    except Exception:
        c.execute('ROLLBACK')
        raise
    finally:
        c.execute('PRAGMA foreign_keys=ON')
    print('migrated: suggestions accept', ', '.join(KINDS), file=sys.stderr)


def secret():
    """Salt for connection hashes: made once, kept next to the database, never sent anywhere."""
    path = os.path.join(STATE, 'salt')
    if not os.path.exists(path):
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as f:
            f.write(secrets.token_hex(32))
    with open(path) as f:
        return f.read().strip()


SALT = None


def purge():
    """KVKK: raw IPs and connection hashes older than RETENTION_DAYS go."""
    cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=RETENTION_DAYS)).isoformat(timespec='seconds')
    c = db()
    c.execute('DELETE FROM ip_log WHERE created < ?', (cut,))
    c.execute("UPDATE suggestions SET net_hash = NULL WHERE net_hash IS NOT NULL AND status != 'open' AND created < ?", (cut,))
    c.execute("UPDATE votes SET net_hash = NULL WHERE net_hash IS NOT NULL AND created < ? AND suggestion IN "
              "(SELECT id FROM suggestions WHERE status != 'open')", (cut,))
    today = datetime.datetime.now(datetime.timezone.utc).date()
    c.execute('DELETE FROM usage WHERE day < ?', ((today - datetime.timedelta(days=USAGE_DAYS)).isoformat(),))
    c.execute("DELETE FROM usage WHERE q != '' AND day < ?", ((today - datetime.timedelta(days=USAGE_QUERY_DAYS)).isoformat(),))


_last_promote = 0.0


def promote(force=False):
    """Publishes open suggestions that had enough votes and whose waiting time is now over (at most every
    PROMOTE_EVERY seconds; called before each request and by the hourly housekeeping)."""
    global _last_promote
    if not force and time.time() - _last_promote < PROMOTE_EVERY:
        return
    _last_promote = time.time()
    cut = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=PUBLISH_AFTER_HOURS)).isoformat(timespec='seconds')
    c = db()
    for r in c.execute("SELECT id FROM suggestions WHERE status = 'open' AND created <= ?", (cut,)).fetchall():
        c.execute('BEGIN IMMEDIATE')
        try:
            decide(c, r['id'])
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise


# ---------- The site's own data, to check what people point at ----------
_cache = {}


def site_json(name):
    path = os.path.join(SITE_DATA, name)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _cache.get(path)
    if hit and hit[0] == mtime:
        return hit[1]
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    _cache[path] = (mtime, data)
    return data


def city_of(cid):
    cat = site_json('catalog.json') or {'cities': []}
    return next((c for c in cat['cities'] if c['id'] == cid), None)


def stop_exists(city, sid):
    if not city.get('stopsFile'):
        return False
    d = site_json(os.path.basename(city['stopsFile'])) or {}
    return sid in d.get('stops', {})


def line_exists(city, key):
    aid, _, line = key.partition('|')
    return any(l['line'] == line and l['operator'] == f"{city['id']}-{aid}" for l in city.get('lineList', []))


def in_city(city, lon, lat):
    """A point near the city's lines (its bounds plus ~10 km): new stops and drawn routes stay in that city."""
    (w, so), (e, n) = city['bounds']
    return w - 0.1 <= lon <= e + 0.1 and so - 0.1 <= lat <= n + 0.1


def km(a, b):
    lat = math.radians((a[1] + b[1]) / 2)
    return math.hypot((b[0] - a[0]) * math.cos(lat), b[1] - a[1]) * 111.32


def lonlat(v, city):
    """[lon, lat] rounded to ~1 m, or None when it isn't two numbers inside the city."""
    if not (isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in v)):
        return None
    lon, lat = round(float(v[0]), 5), round(float(v[1]), 5)
    return [lon, lat] if in_city(city, lon, lat) else None


def text_and_source(p, required):
    text = ' '.join(str(p.get('text', '')).split())
    src = str(p.get('source', '')).strip()
    if (required or text) and not 10 <= len(text) <= MAX_TEXT:
        return None, f'text must be 10-{MAX_TEXT} characters'
    if src and (len(src) > MAX_URL or not re.match(r'^https://[^\s<>"]+$', src)):
        return None, 'source must be an https:// address'
    out = {}
    if text:
        out['text'] = text
    if src:
        out['source'] = src
    return out, None


# ---------- Visitors ----------
def network_of(ip):
    a = ipaddress.ip_address(ip)
    if a.version == 6 and a.ipv4_mapped:
        a = a.ipv4_mapped
    net = ipaddress.ip_network(f'{a}/{24 if a.version == 4 else 48}', strict=False)
    return hashlib.sha256(f'{SALT}|{net}'.encode()).hexdigest()[:20]


def new_name(c):
    year = datetime.date.today().year
    for _ in range(50):
        name = f'~{year}-{secrets.randbelow(90000) + 10000}'
        if not c.execute('SELECT 1 FROM contributors WHERE name = ?', (name,)).fetchone():
            return name
    raise RuntimeError('no free temporary name')


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


_hits = {}
_hits_lock = threading.Lock()


def allowed(net, what):
    """Sliding-window limits per connection, in memory (they reset on restart, which is fine for abuse limits)."""
    count, window = LIMITS[what]
    t = time.time()
    with _hits_lock:
        q = [x for x in _hits.get((net, what), []) if x > t - window]
        if len(q) >= count:
            _hits[(net, what)] = q
            return False
        q.append(t)
        _hits[(net, what)] = q
        if len(_hits) > 50000:   # forget idle entries
            for k in [k for k, v in _hits.items() if not v or v[-1] < t - 86400]:
                del _hits[k]
    return True


# ---------- Rules ----------
def tally(c, sid):
    """Distinct connections per vote; a connection that voted both ways counts on its newest vote."""
    rows = c.execute('SELECT net_hash, vote FROM votes WHERE suggestion = ? AND net_hash IS NOT NULL ORDER BY created', (sid,)).fetchall()
    last = {}
    for r in rows:
        last[r['net_hash']] = r['vote']
    yes = sum(1 for v in last.values() if v == 'yes')
    no = sum(1 for v in last.values() if v == 'no')
    unsure = sum(1 for v in last.values() if v == 'unsure')
    return yes, no, unsure


def iso_dt(s):
    return datetime.datetime.fromisoformat(s)


def publish_at(created):
    return (iso_dt(created) + datetime.timedelta(hours=PUBLISH_AFTER_HOURS)).isoformat(timespec='seconds')


def waited(created):
    return datetime.datetime.now(datetime.timezone.utc) >= iso_dt(created) + datetime.timedelta(hours=PUBLISH_AFTER_HOURS)


def decide(c, sid):
    yes, no, _ = tally(c, sid)
    row = c.execute('SELECT created FROM suggestions WHERE id = ?', (sid,)).fetchone()
    if no >= REJECT_NO and no > yes:
        status = 'rejected'
    elif yes >= PUBLISH_YES and yes > no and row and waited(row['created']):
        status = 'live'
    else:
        status = None
    if status:
        c.execute("UPDATE suggestions SET status = ?, decided = ? WHERE id = ? AND status = 'open'", (status, now(), sid))
    return status


def check_payload(kind, target_type, p, city):
    """The payload as stored, or an error message."""
    if not isinstance(p, dict):
        return None, 'payload must be an object'
    if kind == 'removed':
        if target_type != 'stop':
            return None, 'removed is for stops'
        return text_and_source(p, required=True)
    if kind == 'route':
        if target_type != 'line':
            return None, 'routes are for lines'
        raw = p.get('points')
        if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_POINTS:
            return None, f'draw 2-{MAX_POINTS} points'
        pts = [lonlat(v, city) for v in raw]
        if None in pts:
            return None, 'points must be [lon, lat] in the city'
        if sum(km(a, b) for a, b in zip(pts, pts[1:])) > MAX_ROUTE_KM:
            return None, 'route too long'
        out, err = text_and_source(p, required=True)
        if err:
            return None, err
        return {'points': pts, **out}, None
    if kind == 'newstop':
        if target_type != 'city':
            return None, 'new stops are for cities'
        name = ' '.join(str(p.get('name', '')).split())
        if not 2 <= len(name) <= MAX_NAME:
            return None, f'name must be 2-{MAX_NAME} characters'
        pt = lonlat(p.get('point'), city)
        if not pt:
            return None, 'point must be [lon, lat] in the city'
        lines = p.get('lines', [])
        if not isinstance(lines, list) or len(lines) > MAX_STOP_LINES or not all(isinstance(k, str) and line_exists(city, k) for k in lines):
            return None, 'unknown line'
        out, err = text_and_source(p, required=False)
        if err:
            return None, err
        return {'name': name, 'point': pt, 'lines': sorted(set(lines)), **out}, None
    if kind == 'access':
        if target_type != 'stop':
            return None, 'accessibility is for stops'
        facts = {k: v for k, v in p.get('facts', {}).items() if k in FACTS and v in VALUES} if isinstance(p.get('facts'), dict) else {}
        if not facts:
            return None, 'no facts'
        return {'facts': facts}, None
    if kind == 'name':
        if target_type != 'stop':
            return None, 'names are for stops'
        name = ' '.join(str(p.get('name', '')).split())
        if not 2 <= len(name) <= MAX_NAME:
            return None, f'name must be 2-{MAX_NAME} characters'
        return {'name': name}, None
    if kind == 'report':
        rk = p.get('type')
        text = ' '.join(str(p.get('text', '')).split())
        src = str(p.get('source', '')).strip()
        if rk not in REPORT_KINDS:
            return None, 'unknown report type'
        if not 10 <= len(text) <= MAX_TEXT:
            return None, f'text must be 10-{MAX_TEXT} characters'
        if src and (len(src) > MAX_URL or not re.match(r'^https://[^\s<>"]+$', src)):
            return None, 'source must be an https:// address'
        out = {'type': rk, 'text': text}
        if src:
            out['source'] = src
        return out, None
    return None, 'unknown kind'


def check_usage(d):
    """One usage event as stored (event, page, city, kind, target, q), or an error message. Everything must be one of
    the site's own pages, cities, operators, lines, stops or data files, so nothing a visitor typed is kept except a
    search that found nothing (short, lower case, and never something that looks like an address, e-mail or number)."""
    event, page = d.get('event'), d.get('page')
    cid, kind, target = str(d.get('city') or ''), str(d.get('kind') or ''), str(d.get('target') or '')
    if event not in USAGE_EVENTS or page not in USAGE_PAGES or kind not in USAGE_KINDS:
        return None, 'unknown event'
    city = city_of(cid) if cid else None
    if cid and not city:
        return None, 'unknown city'
    if kind in ('city', 'operator', 'line', 'stop') and not city:
        return None, 'unknown city'
    if kind in ('', 'city') and target:
        return None, 'unknown target'
    if kind == 'operator' and not any(o['id'] == f"{cid}-{target}" for o in city.get('operators', [])):
        return None, 'unknown target'
    if kind == 'line' and not line_exists(city, target):
        return None, 'unknown target'
    if kind == 'stop' and not stop_exists(city, target):
        return None, 'unknown target'
    if kind == 'file' and (cid or not re.fullmatch(r'[a-z0-9-]{1,40}\.(?:geojson|json)', target)
                           or not os.path.isfile(os.path.join(SITE_DATA, target))):
        return None, 'unknown target'
    q = ''
    if event == 'search_empty':
        q = ' '.join(str(d.get('q') or '').split()).lower()
        if not 2 <= len(q) <= MAX_QUERY or re.search(r'@|https?:|www\.|\.(?:com|net|org|tr)\b|\d{7,}', q):
            return None, 'not kept'
    return (event, page, cid, kind, target, q), None


def label_of(city_id, ttype, target):
    """What the suggestion is about, in the site's own words (never text a visitor typed)."""
    city = city_of(city_id)
    if not city:
        return {'city': city_id}
    out = {'city': city['name']}
    if ttype == 'city':
        out['name'] = city['name']
    elif ttype == 'stop' and city.get('stopsFile'):
        s = (site_json(os.path.basename(city['stopsFile'])) or {}).get('stops', {}).get(target)
        if s:
            out['name'] = s[2]
    elif ttype == 'line':
        aid, _, line = target.partition('|')
        l = next((l for l in city.get('lineList', []) if l['line'] == line and l['operator'] == f'{city_id}-{aid}'), None)
        if l:
            out.update({'line': line, 'name': l['name']})
    return out


def public(c, row, me=None):
    """A suggestion as the site shows it: never the connection hash, never who voted."""
    yes, no, unsure = tally(c, row['id'])
    name = c.execute('SELECT name FROM contributors WHERE id = ?', (row['contributor'],)).fetchone()
    out = {'id': row['id'], 'kind': row['kind'], 'city': row['city'], 'targetType': row['target_type'],
           'target': row['target'], 'about': label_of(row['city'], row['target_type'], row['target']),
           'payload': json.loads(row['payload']), 'by': name['name'] if name else '?',
           'status': row['status'], 'created': row['created'], 'decided': row['decided'],
           'votes': {'yes': yes, 'no': no, 'unsure': unsure}, 'needed': PUBLISH_YES}
    # Enough votes, waiting for its day to pass: the site says when it goes live
    if row['status'] == 'open' and yes >= PUBLISH_YES and yes > no:
        out['ready'] = True
        out['publishAt'] = publish_at(row['created'])
    if me is not None:
        v = c.execute('SELECT vote FROM votes WHERE suggestion = ? AND contributor = ?', (row['id'], me)).fetchone()
        out['myVote'] = v['vote'] if v else None
        out['mine'] = row['contributor'] == me
    return out


# ---------- HTTP ----------
class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status, self.message = status, message


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'hatlas-api'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):  # no IPs or paths with ids in the service log
        pass

    # Caddy sets X-Forwarded-For to the visitor's address; the API only listens on 127.0.0.1, so only Caddy (or,
    # locally, tools/serve.py) can reach it. Without the header (a direct local call) the socket address is used.
    def client_ip(self):
        fwd = self.headers.get('X-Forwarded-For', '')
        ip = fwd.split(',')[-1].strip() if fwd else self.client_address[0]
        try:
            ipaddress.ip_address(ip)
        except ValueError:
            ip = self.client_address[0]
        return ip

    def send_json(self, status, data):
        body = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        if not (self.headers.get('Content-Type') or '').startswith('application/json'):
            raise ApiError(415, 'send JSON')
        n = int(self.headers.get('Content-Length') or 0)
        if n > MAX_BODY:
            raise ApiError(413, 'too large')
        try:
            data = json.loads(self.rfile.read(n) or b'{}')
        except ValueError:
            raise ApiError(400, 'bad JSON')
        if not isinstance(data, dict):
            raise ApiError(400, 'send an object')
        return data

    def me(self, required=True):
        tok = self.headers.get('X-Hatlas-Token', '')
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', tok):
            if required:
                raise ApiError(401, 'no token')
            return None
        row = db().execute('SELECT id, name FROM contributors WHERE token_hash = ?', (token_hash(tok),)).fetchone()
        if not row and required:
            raise ApiError(401, 'unknown token')
        return row

    def do_GET(self):
        self.route('GET')

    def do_POST(self):
        self.route('POST')

    def route(self, method):
        try:
            url = urllib.parse.urlsplit(self.path)
            parts = [urllib.parse.unquote(p) for p in url.path.split('/') if p]
            q = dict(urllib.parse.parse_qsl(url.query))
            ip = self.client_ip()
            self.net = network_of(ip)
            self.ip = ip
            if not allowed(self.net, 'any'):
                raise ApiError(429, 'slow down')
            promote()
            if parts[:1] != ['api'] or len(parts) < 2:
                raise ApiError(404, 'not found')
            name = ROUTES.get((method, parts[1]))
            if not name:
                raise ApiError(404, 'not found')
            self.send_json(200, getattr(self, name)(parts[2:], q))
        except ApiError as e:
            self.send_json(e.status, {'error': e.message})
        except Exception as e:  # never the details to the visitor
            print('error:', type(e).__name__, e, file=sys.stderr)
            self.send_json(500, {'error': 'server error'})

    # GET /api/health
    def get_health(self, rest, q):
        return {'ok': True}

    # POST /api/hello: the temporary name and token (or the existing ones, given the token)
    def post_hello(self, rest, q):
        self.body()
        me = self.me(required=False)
        if me:
            return {'name': me['name']}
        if not allowed(self.net, 'hello'):
            raise ApiError(429, 'slow down')
        c = db()
        token = secrets.token_urlsafe(32)
        c.execute('BEGIN IMMEDIATE')
        try:
            name = new_name(c)
            cur = c.execute('INSERT INTO contributors (name, token_hash, created) VALUES (?, ?, ?)', (name, token_hash(token), now()))
            c.execute('INSERT INTO ip_log (contributor, ip, action, created) VALUES (?, ?, ?, ?)', (cur.lastrowid, self.ip, 'hello', now()))
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise
        return {'name': name, 'token': token}

    # POST /api/suggest {kind, city, targetType, target, payload}
    def post_suggest(self, rest, q):
        data = self.body()
        me = self.me()
        if not allowed(self.net, 'suggest'):
            raise ApiError(429, 'too many suggestions today')
        kind, ttype, target = data.get('kind'), data.get('targetType'), str(data.get('target', ''))
        city = city_of(str(data.get('city', '')))
        if not city:
            raise ApiError(400, 'unknown city')
        if ttype == 'stop' and not stop_exists(city, target):
            raise ApiError(400, 'unknown stop')
        if ttype == 'line' and not line_exists(city, target):
            raise ApiError(400, 'unknown line')
        if ttype == 'city' and target != city['id']:
            raise ApiError(400, 'unknown target')
        if ttype not in TARGETS:
            raise ApiError(400, 'unknown target')
        payload, err = check_payload(kind, ttype, data.get('payload'), city)
        if err:
            raise ApiError(400, err)
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            cur = c.execute('INSERT INTO suggestions (kind, city, target_type, target, payload, contributor, net_hash, created) '
                            'VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                            (kind, city['id'], ttype, target, json.dumps(payload, ensure_ascii=False), me['id'], self.net, now()))
            c.execute('INSERT INTO ip_log (contributor, ip, action, created) VALUES (?, ?, ?, ?)', (me['id'], self.ip, f'suggest {cur.lastrowid}', now()))
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise
        row = c.execute('SELECT * FROM suggestions WHERE id = ?', (cur.lastrowid,)).fetchone()
        return public(c, row, me['id'])

    # POST /api/vote/<id> {vote: yes|no|unsure}
    def post_vote(self, rest, q):
        data = self.body()
        me = self.me()
        if not allowed(self.net, 'vote'):
            raise ApiError(429, 'too many votes today')
        if len(rest) != 1 or not rest[0].isdigit():
            raise ApiError(404, 'not found')
        vote = data.get('vote')
        if vote not in ('yes', 'no', 'unsure'):
            raise ApiError(400, 'vote yes, no or unsure')
        c = db()
        c.execute('BEGIN IMMEDIATE')
        try:
            row = c.execute('SELECT * FROM suggestions WHERE id = ?', (int(rest[0]),)).fetchone()
            if not row or row['status'] != 'open':
                raise ApiError(409, 'not open')
            if row['contributor'] == me['id'] or row['net_hash'] == self.net:
                raise ApiError(403, 'not on your own suggestion')
            c.execute('INSERT INTO votes (suggestion, contributor, net_hash, vote, created) VALUES (?, ?, ?, ?, ?) '
                      'ON CONFLICT (suggestion, contributor) DO UPDATE SET vote = excluded.vote, net_hash = excluded.net_hash, created = excluded.created',
                      (row['id'], me['id'], self.net, vote, now()))
            c.execute('INSERT INTO ip_log (contributor, ip, action, created) VALUES (?, ?, ?, ?)', (me['id'], self.ip, f'vote {row["id"]}', now()))
            decide(c, row['id'])
            c.execute('COMMIT')
        except Exception:
            c.execute('ROLLBACK')
            raise
        return public(c, c.execute('SELECT * FROM suggestions WHERE id = ?', (row['id'],)).fetchone(), me['id'])

    # POST /api/withdraw/<id>: the suggester takes back their own suggestion (open or live)
    def post_withdraw(self, rest, q):
        self.body()
        me = self.me()
        if len(rest) != 1 or not rest[0].isdigit():
            raise ApiError(404, 'not found')
        c = db()
        n = c.execute("UPDATE suggestions SET status = 'withdrawn', decided = ? WHERE id = ? AND contributor = ? AND status IN ('open', 'live')",
                      (now(), int(rest[0]), me['id'])).rowcount
        if not n:
            raise ApiError(409, 'not yours or already closed')
        return {'ok': True}

    # GET /api/open?city=&limit=: suggestions waiting for votes (newest first; with a token, not your own)
    def get_open(self, rest, q):
        me = self.me(required=False)
        c = db()
        args, where = [], "status = 'open'"
        if q.get('city'):
            where += ' AND city = ?'
            args.append(q['city'])
        if q.get('target'):
            where += ' AND target = ?'
            args.append(q['target'])
        if me:
            where += ' AND contributor != ?'
            args.append(me['id'])
        where += ' AND (net_hash IS NULL OR net_hash != ?)'   # nor what came from your own connection
        args.append(self.net)
        lim = q.get('limit', '20')
        limit = max(1, min(int(lim), 50)) if lim.isdigit() else 20
        rows = c.execute(f'SELECT * FROM suggestions WHERE {where} ORDER BY created DESC LIMIT ?', (*args, limit)).fetchall()
        return {'items': [public(c, r, me['id'] if me else None) for r in rows]}

    # GET /api/reports[?city=]: the newest published reports everywhere (the site's "Sorunlar" page)
    def get_reports(self, rest, q):
        c = db()
        args, where = [], "kind IN ('report', 'removed', 'route', 'newstop') AND status = 'live'"
        if q.get('city'):
            where += ' AND city = ?'
            args.append(q['city'])
        lim = q.get('limit', '30')
        limit = max(1, min(int(lim), 50)) if lim.isdigit() else 30
        rows = c.execute(f'SELECT * FROM suggestions WHERE {where} ORDER BY decided DESC LIMIT ?', (*args, limit)).fetchall()
        items = []
        for r in rows:
            p = json.loads(r['payload'])
            name = c.execute('SELECT name FROM contributors WHERE id = ?', (r['contributor'],)).fetchone()
            items.append({'id': r['id'], 'kind': r['kind'], 'city': r['city'], 'targetType': r['target_type'], 'target': r['target'],
                          'about': label_of(r['city'], r['target_type'], r['target']), 'type': p.get('type'),
                          'text': p.get('text'), 'name': p.get('name'), 'source': p.get('source'),
                          'by': name['name'] if name else '?', 'since': r['decided']})
        return {'items': items}

    # GET /api/mine: your suggestions and their state
    def get_mine(self, rest, q):
        me = self.me()
        c = db()
        rows = c.execute('SELECT * FROM suggestions WHERE contributor = ? ORDER BY created DESC LIMIT 100', (me['id'],)).fetchall()
        return {'name': me['name'], 'items': [public(c, r, me['id']) for r in rows]}

    # GET /api/stop/<city>/<id>: what the community confirmed for a stop, and how much waits for votes
    def get_stop(self, rest, q):
        return self.target_view(rest, 'stop')

    # GET /api/line/<city>/<agency|line>
    def get_line(self, rest, q):
        return self.target_view(rest, 'line')

    def target_view(self, rest, ttype):
        if len(rest) != 2:
            raise ApiError(404, 'not found')
        c = db()
        rows = c.execute("SELECT * FROM suggestions WHERE city = ? AND target_type = ? AND target = ? AND status IN ('live', 'open') "
                         'ORDER BY decided, created', (rest[0], ttype, rest[1])).fetchall()
        facts, name, reports, routes, removed, waiting = {}, None, [], [], None, 0
        for r in rows:
            if r['status'] == 'open':
                waiting += 1
                continue
            p = json.loads(r['payload'])
            if r['kind'] == 'access':
                for k, v in p['facts'].items():
                    facts[k] = {'value': v, 'since': r['decided'], 'id': r['id']}   # newest live wins (ordered by decided)
            elif r['kind'] == 'name':
                name = {'value': p['name'], 'since': r['decided'], 'id': r['id']}
            elif r['kind'] == 'removed':
                removed = {'id': r['id'], **p, 'since': r['decided']}
            elif r['kind'] == 'route':
                routes.append({'id': r['id'], **p, 'since': r['decided']})
            elif r['kind'] == 'report':
                reports.append({'id': r['id'], **p, 'since': r['decided']})
        out = {'facts': facts, 'name': name, 'reports': list(reversed(reports))[:20], 'waiting': waiting}
        if ttype == 'stop':
            out['removed'] = removed
        if ttype == 'line':
            out['routes'] = list(reversed(routes))[:5]
        return out

    # GET /api/city/<city>: new stops the community confirmed, and how many wait for votes
    def get_city(self, rest, q):
        if len(rest) != 1:
            raise ApiError(404, 'not found')
        c = db()
        rows = c.execute("SELECT * FROM suggestions WHERE city = ? AND kind = 'newstop' AND status IN ('live', 'open') "
                         'ORDER BY decided DESC LIMIT 200', (rest[0],)).fetchall()
        stops = [{'id': r['id'], **json.loads(r['payload']), 'since': r['decided']} for r in rows if r['status'] == 'live']
        return {'newStops': stops, 'waiting': sum(1 for r in rows if r['status'] == 'open')}

    # GET /api/suggestion/<id>: one open or published suggestion, to see a drawing before voting
    def get_suggestion(self, rest, q):
        if len(rest) != 1 or not rest[0].isdigit():
            raise ApiError(404, 'not found')
        c = db()
        row = c.execute("SELECT * FROM suggestions WHERE id = ? AND status IN ('open', 'live')", (int(rest[0]),)).fetchone()
        if not row:
            raise ApiError(404, 'not found')
        return public(c, row)

    # POST /api/usage {event, page, city?, kind?, target?, q?}: one count, only sent after "İzin ver" (js/usage.js).
    # Deliberately ignores X-Hatlas-Token and writes nothing to ip_log: a count can't be tied to a person or to
    # another count. The connection limit below lives in memory only.
    def post_usage(self, rest, q):
        data = self.body()
        if not allowed(self.net, 'usage'):
            raise ApiError(429, 'slow down')
        row, err = check_usage(data)
        if err:
            raise ApiError(400, err)
        db().execute('INSERT INTO usage (day, event, page, city, kind, target, q, n) VALUES (?, ?, ?, ?, ?, ?, ?, 1) '
                     'ON CONFLICT (day, event, page, city, kind, target, q) DO UPDATE SET n = n + 1',
                     (datetime.datetime.now(datetime.timezone.utc).date().isoformat(), *row))
        return {'ok': True}


# (method, first path part after /api/) -> handler; nothing else is reachable.
ROUTES = {('GET', 'health'): 'get_health', ('POST', 'hello'): 'post_hello', ('POST', 'suggest'): 'post_suggest',
          ('POST', 'vote'): 'post_vote', ('POST', 'withdraw'): 'post_withdraw', ('GET', 'open'): 'get_open',
          ('GET', 'mine'): 'get_mine', ('GET', 'stop'): 'get_stop', ('GET', 'line'): 'get_line',
          ('GET', 'reports'): 'get_reports', ('GET', 'city'): 'get_city', ('GET', 'suggestion'): 'get_suggestion',
          ('POST', 'usage'): 'post_usage'}


def serve():
    global SALT
    init()
    SALT = secret()
    purge()

    def housekeeping():
        while True:
            time.sleep(3600)
            try:
                purge()
                promote(force=True)
            except Exception as e:
                print('housekeeping failed:', e, file=sys.stderr)
    threading.Thread(target=housekeeping, daemon=True).start()

    # The service runs /srv/hatlas-api/current/hatlas_api.py. When deploy.py points "current" at a new release,
    # this file's real path changes: the process exits and systemd (Restart=always) starts the new code.
    started_as = os.path.realpath(__file__)

    def watch():
        while True:
            time.sleep(30)
            if os.path.realpath(__file__) != started_as:
                print('new release, restarting', file=sys.stderr)
                os._exit(0)
    threading.Thread(target=watch, daemon=True).start()

    srv = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    srv.daemon_threads = True
    print(f'hatlas-api on 127.0.0.1:{PORT}, data in {STATE}', file=sys.stderr)
    srv.serve_forever()


def admin(args):
    init()
    c = db()
    if args[:1] == ['list']:
        n = int(args[1]) if len(args) > 1 else 30
        for r in c.execute('SELECT s.id, s.kind, s.city, s.target, s.status, s.created, s.payload, c.name FROM suggestions s '
                           'JOIN contributors c ON c.id = s.contributor ORDER BY s.id DESC LIMIT ?', (n,)):
            print(r['id'], r['status'], r['kind'], r['city'], r['target'], r['name'], r['created'][:16], r['payload'][:100])
    elif args[:1] == ['remove'] and len(args) >= 2 and args[1].isdigit():
        n = c.execute("UPDATE suggestions SET status = 'removed', decided = ?, note = ? WHERE id = ?",
                      (now(), ' '.join(args[2:])[:200] or None, int(args[1]))).rowcount
        print('removed' if n else 'no such suggestion')
    elif args[:1] == ['recent']:
        # What came in or went live lately, to check after the launch post: ids for `admin remove <id>`
        hours = int(args[1]) if len(args) > 1 and args[1].isdigit() else 24
        since = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)).isoformat(timespec='seconds')
        rows = c.execute('SELECT s.*, c.name FROM suggestions s JOIN contributors c ON c.id = s.contributor '
                         'WHERE s.created >= ? OR s.decided >= ? ORDER BY s.id DESC', (since, since)).fetchall()
        print(f'{len(rows)} suggestions new or decided in the last {hours} h')
        for r in rows:
            yes, no, _ = tally(c, r['id'])
            when = f"goes live {publish_at(r['created'])[:16]}" if r['status'] == 'open' and yes >= PUBLISH_YES and yes > no else ''
            print(f"{r['id']:>6}  {r['status']:<9} {r['kind']:<8} {r['city']:<12} {r['target']:<14} {r['name']}  "
                  f"yes {yes} no {no}  {r['created'][:16]}  {when}")
            print(f"        {r['payload'][:160]}")
    elif args[:1] == ['usage']:
        days = int(args[1]) if len(args) > 1 and args[1].isdigit() else 30
        since = (datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=days - 1)).isoformat()

        def top(title, sql, n=20):
            print(f'\n{title} (last {days} days)')
            for r in c.execute(sql + f' LIMIT {n}', (since,)):
                print(f'  {r[-1]:>7}  ' + '  '.join(str(x) for x in r[:-1]))
        top('Events', 'SELECT event, page, SUM(n) FROM usage WHERE day >= ? GROUP BY event, page ORDER BY 3 DESC', 40)
        top('Cities', "SELECT city, SUM(n) FROM usage WHERE day >= ? AND city != '' GROUP BY city ORDER BY 2 DESC")
        top('Lines', "SELECT city, target, SUM(n) FROM usage WHERE day >= ? AND kind = 'line' GROUP BY city, target ORDER BY 3 DESC")
        top('Stops', "SELECT city, target, SUM(n) FROM usage WHERE day >= ? AND kind = 'stop' GROUP BY city, target ORDER BY 3 DESC")
        top('Downloads', "SELECT target, SUM(n) FROM usage WHERE day >= ? AND kind = 'file' GROUP BY target ORDER BY 2 DESC")
        top('Searches with no result', "SELECT q, SUM(n) FROM usage WHERE day >= ? AND event = 'search_empty' GROUP BY q ORDER BY 2 DESC", 40)
    else:
        print(__doc__)


if __name__ == '__main__':
    if sys.argv[1:2] == ['admin']:
        admin(sys.argv[2:])
    else:
        serve()
