import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'dashboard'), **kwargs)

    def do_GET(self):
        reports = {'/report.json': ROOT / 'build/incremental/report.json',
                   '/forecast/report.json': ROOT / 'build/forecast/report.json'}
        path = reports.get(self.path.split('?')[0])
        if path is None:
            return super().do_GET()
        if not path.exists():
            self.send_error(404, 'Generate the report first; see README')
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8768)
    args = parser.parse_args()
    print(f'Dashboard: http://127.0.0.1:{args.port}', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
