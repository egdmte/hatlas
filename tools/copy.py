"""Puts the site's text (copy/tr.toml) into the pages and into js/copy.js.

    py -3 tools/copy.py           write the text into the pages and js/copy.js
    py -3 tools/copy.py --check   change nothing; exit 1 if a page or js/copy.js is out of date (deploy.py runs the real thing)

How it finds the places (all in the site's own .html files):
    <h1 data-copy="home.title">…</h1>                         the element's content becomes copy[home][title]
    <input data-copy-attr="placeholder=home.search; aria-label=home.search_label">   attributes
Inside a value, **bold** becomes <strong> and [text](address) a link; everything else is plain text.
{name} in a value is a gap the scripts fill in (a number, a stop's name); pages leave it as it is.

The scripts read their text through js/copy.js (window.hatlasCopy.t('stop.lines', {n: 3})). Only the keys a script
names in t('…') / rich('…') go into js/copy.js, so a typo in a key is caught here instead of showing up on the site.
Standard library only (tomllib needs Python 3.11+).
"""
import glob, html, html.parser, json, os, re, sys, tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE = os.path.join(ROOT, 'copy', 'tr.toml')
PAGES = sorted(glob.glob(os.path.join(ROOT, '*.html')))
SCRIPTS = [p for p in sorted(glob.glob(os.path.join(ROOT, 'js', '*.js'))) if not p.endswith('copy.js')]
OUT_JS = os.path.join(ROOT, 'js', 'copy.js')
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}
KEY = re.compile(r'^[a-z][a-z0-9_]*\.[a-z0-9_]+$')
SAFE_HREF = re.compile(r'^(?:https://|mailto:|#|\./|[a-z0-9-]+\.html(?:[?#].*)?$|[a-z0-9-]+/)', re.I)


def load():
    with open(SOURCE, 'rb') as f:
        data = tomllib.load(f)
    flat = {}
    for table, keys in data.items():
        if not isinstance(keys, dict):
            sys.exit(f'copy/tr.toml: "{table}" must be a [table]')
        for k, v in keys.items():
            if not isinstance(v, str):
                sys.exit(f'copy/tr.toml: [{table}] {k} must be text in quotes')
            flat[f'{table}.{k}'] = v
    return flat


def to_html(text):
    """Plain text, with **bold** and [text](address) turned into tags; everything else escaped."""
    out, pos = [], 0
    for m in re.finditer(r'\*\*(.+?)\*\*|\[([^\]]+)\]\(([^)\s]+)\)', text):
        out.append(html.escape(text[pos:m.start()], quote=False))
        if m.group(1) is not None:
            out.append(f'<strong>{html.escape(m.group(1), quote=False)}</strong>')
        else:
            href = m.group(3)
            if not SAFE_HREF.match(href):
                raise ValueError(f'link address not allowed: {href}')
            rel = ' rel="noopener"' if href.startswith('https://') else ''
            out.append(f'<a href="{html.escape(href)}"{rel}>{html.escape(m.group(2), quote=False)}</a>')
        pos = m.end()
    out.append(html.escape(text[pos:], quote=False))
    return ''.join(out)


def plain(text):
    """For attributes and <title>: the markup removed, the rest escaped."""
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)\s]+\)', r'\1', text)
    return html.escape(text)


class Finder(html.parser.HTMLParser):
    """Offsets of every data-copy element's content and every data-copy-attr start tag."""

    def __init__(self, src):
        super().__init__(convert_charrefs=False)
        self.src = src
        self.lines = [0]
        for m in re.finditer('\n', src):
            self.lines.append(m.end())
        self.stack = []      # [tag, key or None, content start]
        self.content = []    # (start, end, key, tag)
        self.attrs = []      # (tag start, tag end, [(attr, key)])

    def here(self):
        line, col = self.getpos()
        return self.lines[line - 1] + col

    def handle_starttag(self, tag, attrs):
        start = self.here()
        end = start + len(self.get_starttag_text())
        a = dict(attrs)
        if a.get('data-copy-attr'):
            pairs = []
            for part in a['data-copy-attr'].split(';'):
                if part.strip():
                    name, _, key = part.partition('=')
                    pairs.append((name.strip(), key.strip()))
            self.attrs.append((start, end, pairs))
        if tag not in VOID:
            self.stack.append([tag, a.get('data-copy'), end])

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID and self.stack and self.stack[-1][0] == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        here = self.here()
        while self.stack:
            t, key, start = self.stack.pop()
            if key:
                self.content.append((start, here, key, t))
            if t == tag:
                break


def render_page(path, copy, used):
    with open(path, encoding='utf-8', newline='') as f:
        src = f.read()
    p = Finder(src)
    p.feed(src)
    p.close()
    edits = []
    for start, end, key, tag in p.content:
        if key not in copy:
            raise KeyError(f'{os.path.basename(path)}: no "{key}" in copy/tr.toml')
        used.add(key)
        edits.append((start, end, plain(copy[key]) if tag == 'title' else to_html(copy[key])))
    for start, end, pairs in p.attrs:
        tag_text = src[start:end]
        for name, key in pairs:
            if key not in copy:
                raise KeyError(f'{os.path.basename(path)}: no "{key}" in copy/tr.toml')
            used.add(key)
            value = plain(copy[key])
            pat = re.compile(r'(\s' + re.escape(name) + r'=")[^"]*(")')
            if pat.search(tag_text):
                tag_text = pat.sub(lambda m: m.group(1) + value + m.group(2), tag_text, count=1)
            else:
                cut = len(tag_text) - (2 if tag_text.endswith('/>') else 1)
                tag_text = f'{tag_text[:cut]} {name}="{value}"{tag_text[cut:]}'
        edits.append((start, end, tag_text))
    out = src
    for start, end, new in sorted(edits, key=lambda e: e[0], reverse=True):
        out = out[:start] + new + out[end:]
    return src, out


def script_keys():
    keys = set()
    for path in SCRIPTS:
        with open(path, encoding='utf-8') as f:
            src = f.read()
        for m in re.finditer(r"""\b(?:t|rich)\(\s*['"]([^'"]+)['"]""", src):
            if KEY.match(m.group(1)):
                keys.add((m.group(1), os.path.basename(path)))
    return keys


def render_js(copy, used):
    needed = {}
    for key, where in sorted(script_keys()):
        if key not in copy:
            raise KeyError(f'{where}: no "{key}" in copy/tr.toml')
        used.add(key)
        needed[key] = copy[key]
    body = json.dumps(needed, ensure_ascii=False, indent=1, sort_keys=True)
    return f'''/* GENERATED by tools/copy.py from copy/tr.toml. Don't edit this file: change copy/tr.toml and run
   `npm run copy` (tools/deploy.py also runs it). Only the keys the scripts name are here.

   t('stop.lines', {{n: 3}})   the text, with {{n}} filled in (a missing key shows the key itself, and a console warning)
   rich('privacy.x', vars)    the same as page content: **bold** and [text](address) become elements; never HTML */
(function () {{
  'use strict';
  const COPY = {body};
  function t(key, vars) {{
    let s = COPY[key];
    if (s === undefined) {{ console.warn('hatlas copy: no', key); return key; }}
    if (vars) s = s.replace(/\\{{(\\w+)\\}}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k])));
    return s.replace(/\\*\\*(.+?)\\*\\*/g, '$1').replace(/\\[([^\\]]+)\\]\\([^)\\s]+\\)/g, '$1');
  }}
  function rich(key, vars) {{
    let s = COPY[key];
    if (s === undefined) {{ console.warn('hatlas copy: no', key); s = key; }}
    if (vars) s = s.replace(/\\{{(\\w+)\\}}/g, (m, k) => (vars[k] === undefined ? m : String(vars[k])));
    const frag = document.createDocumentFragment();
    let pos = 0;
    for (const m of s.matchAll(/\\*\\*(.+?)\\*\\*|\\[([^\\]]+)\\]\\(([^)\\s]+)\\)/g)) {{
      frag.append(s.slice(pos, m.index));
      if (m[1] !== undefined) {{
        const b = document.createElement('strong');
        b.textContent = m[1];
        frag.append(b);
      }} else if (/^(https:\\/\\/|mailto:|#|\\.\\/|[a-z0-9-]+\\.html)/i.test(m[3])) {{
        const a = document.createElement('a');
        a.href = m[3];
        if (m[3].startsWith('https://')) a.rel = 'noopener';
        a.textContent = m[2];
        frag.append(a);
      }} else {{
        frag.append(m[2]);
      }}
      pos = m.index + m[0].length;
    }}
    frag.append(s.slice(pos));
    return frag;
  }}
  window.hatlasCopy = {{ t, rich }};
}})();
'''


def main():
    check = '--check' in sys.argv
    copy = load()
    bad = [k for k in copy if not KEY.match(k)]
    if bad:
        sys.exit('copy/tr.toml: keys must be lower case letters, digits and _: ' + ', '.join(bad))
    used, stale = set(), []
    outputs = []
    for path in PAGES:
        old, new = render_page(path, copy, used)
        outputs.append((path, old, new))
    js_new = render_js(copy, used)
    js_old = open(OUT_JS, encoding='utf-8', newline='').read() if os.path.exists(OUT_JS) else ''
    outputs.append((OUT_JS, js_old, js_new))
    for path, old, new in outputs:
        if old != new:
            stale.append(os.path.relpath(path, ROOT))
            if not check:
                with open(path, 'w', encoding='utf-8', newline='') as f:
                    f.write(new)
    unused = sorted(set(copy) - used)
    if unused:
        print('not used anywhere (fine to delete, or a page lost its data-copy):', ', '.join(unused))
    if check:
        if stale:
            print('out of date:', ', '.join(stale), '-> run `npm run copy`')
            sys.exit(1)
        print('copy: everything up to date')
    else:
        print('copy: updated ' + (', '.join(stale) if stale else 'nothing (already up to date)'))


if __name__ == '__main__':
    try:
        main()
    except tomllib.TOMLDecodeError as e:   # a missing quote or similar in copy/tr.toml
        sys.exit(f'copy/tr.toml has a typo, nothing changed: {e}')
    except (KeyError, ValueError) as e:   # a key that isn't in copy/tr.toml, a link that isn't allowed
        sys.exit('copy: nothing changed. ' + str(e).strip("'"))
