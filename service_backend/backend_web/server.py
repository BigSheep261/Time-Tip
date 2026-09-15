import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
root = Path(os.getenv('WEB_DIR', Path(__file__).parent / 'dist'))
os.chdir(root if root.exists() else Path(__file__).parent)
class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = Path(self.translate_path(self.path))
        if not path.exists() and not self.path.startswith('/api/'):
            self.path = '/index.html'
        return super().do_GET()
ThreadingHTTPServer((os.getenv('WEB_HOST', '0.0.0.0'), int(os.getenv('WEB_PORT', '8788'))), Handler).serve_forever()
