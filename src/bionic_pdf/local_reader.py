"""Serve the bundled reader and hand a selected PDF to the user's browser on loopback."""
import errno
from functools import partial
import os
import secrets
import sys
import threading
import time
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote

DEFAULT_PORT = 8765
_server = None
_server_lock = threading.Lock()


class ReaderHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript',
                      '.js': 'text/javascript', '.wasm': 'application/wasm'}

    def log_message(self, *args):
        pass

    def do_GET(self):
        if not self.path.startswith('/selected/'):
            return super().do_GET()
        with _server_lock:
            entry = self.server.selections.pop(self.path, None)
        if entry is None or entry[1] < time.monotonic():
            return self.send_error(404)
        path, _ = entry
        try:
            document = path.open('rb')
        except OSError:
            return self.send_error(404)
        with document:
            self.send_response(200)
            self.send_header('Content-Type', 'application/pdf')
            self.send_header('Content-Length', str(os.fstat(document.fileno()).st_size))
            self.send_header('X-PDF-Name', quote(path.name, safe=''))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.copyfile(document, self.wfile)


class ReaderServer(ThreadingHTTPServer):
    # Two tools must not split requests for the same browser origin.
    allow_reuse_port = False
    allow_reuse_address = sys.platform != 'win32'

    def __init__(self, *args):
        super().__init__(*args)
        self.selections = {}


def reader_directory():
    module = Path(__file__).resolve()
    root = module.with_name('reader')
    if not (root / 'reader.html').is_file():
        root = module.parents[2] / 'extension'  # Source checkout
    if not (root / 'reader.html').is_file():
        raise FileNotFoundError('缺少本地阅读页文件，请重新安装制作工具。')
    return root


def _bind_reader():
    handler = partial(ReaderHandler, directory=str(reader_directory()))
    try:
        return ReaderServer(('127.0.0.1', DEFAULT_PORT), handler)
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        return ReaderServer(('127.0.0.1', 0), handler)


def start_reader(source=None):
    global _server
    path = Path(source).resolve(strict=True) if source else None
    if path is not None and (not path.is_file() or path.suffix.lower() != '.pdf'):
        raise OSError('请选择一个 PDF 文件。')
    with _server_lock:
        if _server is None:
            _server = _bind_reader()
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        url = f'http://127.0.0.1:{_server.server_port}/reader.html'
        if path is None:
            return url
        now = time.monotonic()
        _server.selections = {key: entry for key, entry in _server.selections.items() if entry[1] > now}
        token = secrets.token_urlsafe(32)
        _server.selections['/selected/' + token] = (path, now + 300)
        return url + '#selected=' + token
