"""Hatlas feed updater: runs once a day on the user's PC (Windows task "Hatlas veri güncellemesi",
installed by tools/install_update_task.ps1).

Usage:  py -3 -I tools/update_feeds.py              check, download what's new, rebuild, commit data/, notify
        py -3 -I tools/update_feeds.py --check      only ask the sources what their newest version is
        py -3 -I tools/update_feeds.py --baseline   remember the sources' current versions as "already here"
                                                     (for when the local copies were downloaded by hand)
        py -3 -I tools/update_feeds.py --rebuild    rebuild data/ even if nothing new came in
        py -3 -I tools/update_feeds.py --auto-deploy=on|off
                                                     after a rebuild, also put the site live (tools/deploy.py)
        add --quiet to skip the Windows notification, --deploy to deploy after this run's rebuild

What it does:
  1. kk-gtfs (22 cities): asks GitHub for the newest commit of Egezenn/kk-gtfs. When it changed, downloads the
     repository zip and swaps it into ~/Downloads/kk-gtfs-main, the folder build_catalog.py reads.
  2. İstanbul: asks İBB's open data portal when the files of "iett-gtfs-verisi" (timetable) and "iett-hat-guzergahlari"
     (route drawings, one 250 MB GeoJSON) last changed. When either did, downloads it (into ~/Downloads/istanbul-iett
     or ~/Downloads/istanbul-iett-guzergah) and runs import_istanbul.py once into ~/Downloads/istanbul-gtfs.
  3. When anything came in: rebuilds into a staging folder, swaps it in as data/ only if the build finished,
     writes data/status.json (when the data last changed, from which versions) and commits data/. Never pushes.
     With auto-deploy on, the new data then goes live on hatlas.avartech.net (tools/deploy.py, no sudo).
     A source whose import or build failed is tried again the next day.
  4. Works out how close each feed is to its end and sends a Windows notification (tools/notify.ps1): new data,
     a feed 30 / 14 / 7 / 1 days before its end, an ended feed, and failures. Each warning goes out once.

Everything downloaded is treated as data: zips are checked for paths that leave their folder, sizes are capped,
and only the two known hosts are contacted. State and a log are kept in %LOCALAPPDATA%\\Hatlas, outside the repo.
"""
import datetime, json, os, shutil, subprocess, sys, tempfile, urllib.request, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
DOWNLOADS = os.path.expanduser('~/Downloads')
KK_DIR = os.path.join(DOWNLOADS, 'kk-gtfs-main')            # build_catalog.py's KK_DATA is inside it
IBB_RAW = os.path.join(DOWNLOADS, 'istanbul-iett')           # İBB's files as downloaded
IBB_GTFS = os.path.join(DOWNLOADS, 'istanbul-gtfs')          # the cleaned GTFS (build_catalog.py FEEDS)
IBB_ROUTES = os.path.join(DOWNLOADS, 'istanbul-iett-guzergah')  # İETT route drawings (import_istanbul.py reads them)
IBB_ROUTES_FILE = 'iett-hat-guzergahlari.geojson'
HOME = os.path.join(os.environ.get('LOCALAPPDATA') or os.path.expanduser('~'), 'Hatlas')
STATE = os.path.join(HOME, 'update-state.json')
LOG = os.path.join(HOME, 'update.log')

KK_COMMIT = 'https://api.github.com/repos/Egezenn/kk-gtfs/commits/main'
KK_ZIP = 'https://codeload.github.com/Egezenn/kk-gtfs/zip/refs/heads/main'
IBB_PACKAGE = 'https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi'
IBB_ROUTES_PACKAGE = 'https://data.ibb.gov.tr/api/3/action/package_show?id=iett-hat-guzergahlari'
IBB_FILES_HOST = 'https://data.ibb.gov.tr/'
# The İBB files import_istanbul.py needs: (resource name, format) -> file name here.
IBB_WANTED = {('agency', 'CSV'): 'agency.csv', ('calendar', 'CSV'): 'calendar.csv', ('routes', 'CSV'): 'routes.csv',
              ('trips', 'CSV'): 'trips.csv', ('stops', 'CSV'): 'stops.csv', ('stop_times', 'ZIP'): 'stop_times.zip'}

WARN_DAYS = (30, 14, 7, 1)          # warn this many days before a feed ends (and once more when it has ended)
MAX_DOWNLOAD = 400 * 1024 * 1024    # bytes; kk-gtfs is ~45 MB, İBB's timetable ~30 MB, its routes ~250 MB
TIMEOUT = 60
AGENT = 'Hatlas-feed-updater/1.0'   # a generic name; nothing about the user is sent


def log(msg):
    os.makedirs(HOME, exist_ok=True)
    line = f'{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}'
    try:
        print(line)   # no console under pyw (the scheduled task); a console may not take every letter
    except (UnicodeEncodeError, OSError, AttributeError):
        pass
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def load_state():
    try:
        with open(STATE, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_state(state):
    os.makedirs(HOME, exist_ok=True)
    tmp = STATE + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STATE)


def get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'application/json'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def download(url, path):
    req = urllib.request.Request(url, headers={'User-Agent': AGENT})
    size = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r, open(path, 'wb') as f:
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_DOWNLOAD:
                raise RuntimeError(f'{url}: larger than {MAX_DOWNLOAD // 2**20} MB, stopped')
            f.write(chunk)
    return size


def safe_extract(zpath, dest):
    """Unzip, refusing any entry that would land outside dest."""
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(zpath) as z:
        for m in z.infolist():
            target = os.path.abspath(os.path.join(dest, m.filename))
            if not (target == dest or target.startswith(dest + os.sep)):
                raise RuntimeError(f'zip entry leaves its folder: {m.filename!r}')
        z.extractall(dest)


def swap_in(new, final):
    """Replace final with new; the old copy is kept until the new one is in place."""
    old = final + '.old'
    if os.path.exists(old):
        shutil.rmtree(old)
    if os.path.exists(final):
        os.rename(final, old)
    os.rename(new, final)
    if os.path.exists(old):
        shutil.rmtree(old)


def fresh_dir(path):
    if os.path.exists(path):
        shutil.rmtree(path)
    os.makedirs(path)
    return path


# ---------- The sources ----------
def kk_version():
    c = get_json(KK_COMMIT)
    return {'version': c['sha'], 'date': c['commit']['committer']['date']}


def kk_fetch():
    staging = fresh_dir(KK_DIR + '.new')
    with tempfile.TemporaryDirectory() as tmp:
        z = os.path.join(tmp, 'kk-gtfs.zip')
        n = download(KK_ZIP, z)
        log(f'kk-gtfs: downloaded {n / 2**20:.1f} MB')
        safe_extract(z, staging)
    data = os.path.join(staging, 'kk-gtfs-main', 'data')
    if not os.path.isdir(data):
        raise RuntimeError('kk-gtfs: the zip has no kk-gtfs-main/data folder')
    unpack_cities(data)
    swap_in(staging, KK_DIR)


def unpack_cities(data):
    """The repository keeps each city as data/<city>.zip; build_catalog.py reads data/<city>/*.txt."""
    n = 0
    for name in sorted(os.listdir(data)):
        if name.endswith('.zip'):
            safe_extract(os.path.join(data, name), fresh_dir(os.path.join(data, name[:-4])))
            n += 1
    if n < 10:
        raise RuntimeError(f'kk-gtfs: only {n} city zips in data/')
    log(f'kk-gtfs: unpacked {n} cities')


def ibb_resources():
    pkg = get_json(IBB_PACKAGE)['result']
    found = {}
    for r in pkg['resources']:
        key = ((r.get('name') or '').strip().lower(), (r.get('format') or '').strip().upper())
        if key in IBB_WANTED:
            found[IBB_WANTED[key]] = r
    missing = set(IBB_WANTED.values()) - found.keys()
    if missing:
        raise RuntimeError(f'İBB: the dataset no longer lists {", ".join(sorted(missing))}')
    return found


def ibb_version():
    res = ibb_resources()
    stamps = {name: r.get('last_modified') or r.get('metadata_modified') or '' for name, r in res.items()}
    return {'version': max(stamps.values()), 'files': stamps}


def ibb_fetch():
    staging = fresh_dir(IBB_RAW + '.new')
    for name, r in ibb_resources().items():
        url = r.get('url') or ''
        if not url.startswith(IBB_FILES_HOST):
            raise RuntimeError(f'İBB: {name} points outside data.ibb.gov.tr ({url[:60]})')
        n = download(url, os.path.join(staging, name))
        log(f'İBB: {name} {n / 2**20:.1f} MB')
    swap_in(staging, IBB_RAW)


def ibb_routes_resource():
    res = [r for r in get_json(IBB_ROUTES_PACKAGE)['result']['resources'] if (r.get('format') or '').upper() == 'GEOJSON']
    if len(res) != 1:
        raise RuntimeError(f'İBB routes: expected one GeoJSON file, found {len(res)}')
    return res[0]


def ibb_routes_version():
    r = ibb_routes_resource()
    return {'version': r.get('last_modified') or r.get('metadata_modified') or ''}


def ibb_routes_fetch():
    url = ibb_routes_resource().get('url') or ''
    if not url.startswith(IBB_FILES_HOST):
        raise RuntimeError(f'İBB routes: the file points outside data.ibb.gov.tr ({url[:60]})')
    staging = fresh_dir(IBB_ROUTES + '.new')
    n = download(url, os.path.join(staging, IBB_ROUTES_FILE))
    log(f'İBB routes: {n / 2**20:.1f} MB')
    swap_in(staging, IBB_ROUTES)


def ibb_import():
    """The İstanbul GTFS from the timetable files and the route drawings (after either came in)."""
    out = fresh_dir(IBB_GTFS + '.new')
    run([sys.executable, '-I', '-X', 'utf8', os.path.join(ROOT, 'tools', 'import_istanbul.py'), IBB_RAW, out,
         os.path.join(IBB_ROUTES, IBB_ROUTES_FILE)])
    swap_in(out, IBB_GTFS)


SOURCES = {'kk-gtfs': (kk_version, kk_fetch), 'ibb-iett': (ibb_version, ibb_fetch),
           'ibb-routes': (ibb_routes_version, ibb_routes_fetch)}


# ---------- Build, commit, warn ----------
def run(cmd):
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if p.returncode:
        raise RuntimeError(f'{os.path.basename(cmd[4] if len(cmd) > 4 else cmd[-1])} failed: {(p.stderr or p.stdout)[-400:]}')
    return p.stdout


def read_catalog(folder):
    try:
        with open(os.path.join(folder, 'catalog.json'), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {'cities': []}


def rebuild(versions):
    staging = fresh_dir(DATA + '.new')
    out = run([sys.executable, '-I', '-X', 'utf8', os.path.join(ROOT, 'tools', 'build_catalog.py'), staging])
    new = read_catalog(staging)
    if len(new['cities']) < 10:
        raise RuntimeError(f'the new build has only {len(new["cities"])} cities; kept the old data')
    old = read_catalog(DATA)
    status = {'updated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
              'sources': {k: {'version': v['version'][:12] if k == 'kk-gtfs' else v['version']} for k, v in versions.items()}}
    with open(os.path.join(staging, 'status.json'), 'w', encoding='utf-8') as f:
        json.dump(status, f, ensure_ascii=False, indent=1)
    swap_in(staging, DATA)
    log(out.strip().replace('\n', ' | ')[-600:])
    # What changed, for the notification: cities whose feed end moved, and new or dropped cities.
    o = {c['id']: c for c in old['cities']}
    changes = []
    for c in new['cities']:
        before = o.pop(c['id'], None)
        if before is None:
            changes.append(f'{c["name"]} eklendi')
        elif (before.get('validity') or [None, None])[1] != (c.get('validity') or [None, None])[1] and c.get('validity'):
            changes.append(f'{c["name"]} {date_text(c["validity"][1])} tarihine kadar')
    changes += [f'{c["name"]} çıkarıldı' for c in o.values()]
    return new, changes


def commit():
    git = shutil.which('git')
    if not git:
        log('git not found; data/ not committed')
        return
    subprocess.run([git, '-C', ROOT, 'add', '-A', '--', 'data'], check=True, capture_output=True)
    p = subprocess.run([git, '-C', ROOT, 'commit', '-m', f'Data: feeds updated {datetime.date.today()} (automatic)', '--', 'data'],
                       capture_output=True, text=True)
    log('data/ committed' if p.returncode == 0 else f'nothing to commit ({(p.stdout or p.stderr).strip()[:120]})')


MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']


def date_text(d):
    return f'{int(d[6:8])} {MONTHS[int(d[4:6]) - 1]} {d[:4]}'


def ending_warnings(catalog, state):
    """New warnings for feeds near or past their end; remembers which went out so each goes out once."""
    sent = state.setdefault('warned', {})
    today = datetime.date.today()
    groups = {}
    for c in catalog['cities']:
        if not c.get('validity'):
            continue
        end = c['validity'][1]
        left = (datetime.date(int(end[:4]), int(end[4:6]), int(end[6:8])) - today).days
        step = 0 if left < 0 else next((d for d in sorted(WARN_DAYS) if left <= d), None)
        if step is None:
            continue
        key = f'{c["id"]}:{end}'
        if key in sent and sent[key] <= step:
            continue
        sent[key] = step
        groups.setdefault((step, end), []).append(c['name'])
    out = []
    for (step, end), names in sorted(groups.items()):
        who = ', '.join(sorted(names)) if len(names) <= 4 else f'{", ".join(sorted(names)[:3])} ve {len(names) - 3} şehir daha'
        if step == 0:
            out.append(f'{len(names)} akışın süresi doldu: {who}')
        else:
            out.append(f'{len(names)} akışın süresi {date_text(end)} tarihinde doluyor ({step} gün): {who}')
    return out


def notify(title, lines, quiet):
    if quiet or not lines:
        return
    ps = os.path.join(ROOT, 'tools', 'notify.ps1')
    text = '\n'.join(lines)[:600]
    try:
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', ps,
                        '-Title', title, '-Message', text], capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        log(f'notification failed: {e}')


def forget(names, seen, before):
    """Undo 'already have it' for sources whose data didn't make it into data/, so the next run tries again."""
    for n in names:
        if n in before:
            seen[n] = before[n]
        else:
            seen.pop(n, None)


def main():
    args = set(sys.argv[1:])
    quiet = '--quiet' in args
    state = load_state()
    seen = state.setdefault('sources', {})
    for a in args:
        if a.startswith('--auto-deploy='):
            state['autoDeploy'] = a.split('=', 1)[1] == 'on'
            save_state(state)
            log(f'auto-deploy {"on" if state["autoDeploy"] else "off"}')
            return
    before = {k: v for k, v in seen.items()}
    versions, todo, errors = {}, [], []
    for name, (version, _fetch) in SOURCES.items():
        try:
            versions[name] = version()
        except Exception as e:  # network, API changes: report, carry on with the other source
            errors.append(f'{name}: {e}')
            continue
        if seen.get(name, {}).get('version') != versions[name]['version']:
            todo.append(name)
    for name, v in versions.items():
        log(f'{name}: newest {v["version"][:40]}' + (' (new)' if name in todo else ''))

    if '--check' in args:
        return
    if '--baseline' in args:
        for name, v in versions.items():
            seen[name] = v
        save_state(state)
        log('baseline saved: the local copies count as these versions')
        return

    fetched = []
    for name in todo:
        try:
            log(f'{name}: downloading')
            SOURCES[name][1]()
            seen[name] = versions[name]
            fetched.append(name)
        except Exception as e:
            errors.append(f'{name}: {e}')
    if {'ibb-iett', 'ibb-routes'} & set(fetched):
        try:
            ibb_import()
        except Exception as e:
            errors.append(f'İstanbul import: {e}')
            forget([f for f in fetched if f.startswith('ibb-')], seen, before)
            fetched = [f for f in fetched if not f.startswith('ibb-')]
    catalog = read_catalog(DATA)
    changes = []
    if fetched or '--rebuild' in args:
        try:
            catalog, changes = rebuild({k: seen[k] for k in seen if k in SOURCES})
            commit()
        except Exception as e:
            errors.append(f'build: {e}')
            forget(fetched, seen, before)
        else:
            # A failed deploy leaves the data built and committed here; the next deploy sends it.
            if state.get('autoDeploy') or '--deploy' in args:
                try:
                    log(run([sys.executable, '-I', '-X', 'utf8', os.path.join(ROOT, 'tools', 'deploy.py')]).strip()[-400:])
                except Exception as e:
                    errors.append(f'deploy: {e}')
    state['checked'] = datetime.datetime.now().isoformat(timespec='seconds')
    warnings = ending_warnings(catalog, state)
    save_state(state)

    for e in errors:
        log(f'ERROR {e}')
    for w in warnings:
        log(f'warning: {w}')
    if fetched:
        notify('Hatlas: yeni veri geldi', [f'Güncellenen: {", ".join(fetched)}'] + changes[:6] + warnings, quiet)
    elif warnings:
        notify('Hatlas: akış süresi', warnings, quiet)
    if errors:
        notify('Hatlas: güncelleme sorunu', errors + [f'Ayrıntılar: {LOG}'], quiet)
    log('done' + (f' ({len(errors)} error(s))' if errors else ''))


if __name__ == '__main__':
    main()
