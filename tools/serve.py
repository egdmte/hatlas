"""Local preview server for Hatlas: like `py -m http.server`, but tells the browser never to cache,
so a reload always shows the latest files. Listens on 127.0.0.1 only.

/api/* goes to the contributions API (api/hatlas_api.py) on 127.0.0.1:3200, as Caddy does on the server;
start it beside this one with `py -3 api/hatlas_api.py` (its local data: api/dev-data/).

Usage:  py -3 tools/serve.py [port]      (default 8765), then open http://localhost:8765
"""
import http.server, os, sys, functools, urllib.error, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = 'http://127.0.0.1:3200'


class NoCacheHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store')
        super().end_headers()

    def proxy(self):
        n = int(self.headers.get('Content-Length') or 0)
        headers = {k: v for k, v in self.headers.items() if k.lower() in ('content-type', 'x-hatlas-token')}
        headers['X-Forwarded-For'] = self.client_address[0]
        req = urllib.request.Request(API + self.path, data=self.rfile.read(n) if n else None, method=self.command, headers=headers)
        try:
            r = urllib.request.urlopen(req, timeout=30)
            status, body, ctype = r.status, r.read(), r.headers.get('Content-Type', 'application/json')
        except urllib.error.HTTPError as e:
            status, body, ctype = e.code, e.read(), e.headers.get('Content-Type', 'application/json')
        except OSError:
            status, body, ctype = 502, b'{"error":"API not running (py -3 api/hatlas_api.py)"}', 'application/json'
        self.send_response(status)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith('/api/'):
            return self.proxy()
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith('/api/'):
            return self.proxy()
        self.send_error(405)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    handler = functools.partial(NoCacheHandler, directory=ROOT)
    with http.server.ThreadingHTTPServer(('127.0.0.1', port), handler) as httpd:
        print(f'Hatlas: http://localhost:{port}  (no cache, /api/ -> {API}, Ctrl+C to stop)')
        httpd.serve_forever()
