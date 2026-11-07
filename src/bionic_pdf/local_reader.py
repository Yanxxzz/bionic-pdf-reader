"""Serve bundled reader assets on loopback; selected PDFs stay in the browser."""
import errno
from functools import partial
import sys
import threading
from pathlib import Path
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_PORT = 8765
_server = None
_server_lock = threading.Lock()


class ReaderHandler(SimpleHTTPRequestHandler):
    extensions_map = {**SimpleHTTPRequestHandler.extensions_map, '.mjs': 'text/javascript',
                      '.js': 'text/javascript', '.wasm': 'application/wasm'}

    def log_message(self, *args):
        pass


class ReaderServer(ThreadingHTTPServer):
    # Two tools must not split requests for the same browser origin.
    allow_reuse_port = False
    allow_reuse_address = sys.platform != 'win32'


def _bind_reader():
    module = Path(__file__).resolve()
    root = module.with_name('reader')
    if not (root / 'reader.html').is_file():
        root = module.parents[2] / 'extension'  # Source checkout
    if not (root / 'reader.html').is_file():
        raise FileNotFoundError('缺少本地阅读页文件，请重新安装制作工具。')
    handler = partial(ReaderHandler, directory=str(root))
    try:
        return ReaderServer(('127.0.0.1', DEFAULT_PORT), handler)
    except OSError as error:
        if error.errno not in (errno.EADDRINUSE, errno.EACCES):
            raise
        return ReaderServer(('127.0.0.1', 0), handler)


def start_reader():
    global _server
    with _server_lock:
        if _server is None:
            _server = _bind_reader()
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        return f'http://127.0.0.1:{_server.server_port}/reader.html'
