"""Serve bundled reader assets on loopback; selected PDFs stay in the browser."""
import functools
import sys
import threading
from pathlib import Path
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer

_server=None

def start_reader():
    global _server
    if _server is None:
        root=Path(sys._MEIPASS)/'reader' if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[2]/'extension'
        if not (root/'reader.html').is_file():
            raise FileNotFoundError('Browser reader assets are available in the source checkout or Windows bundle.')
        class Handler(SimpleHTTPRequestHandler):
            extensions_map={**SimpleHTTPRequestHandler.extensions_map,'.mjs':'text/javascript','.js':'text/javascript','.wasm':'application/wasm'}
            def log_message(self,*args):pass
        _server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(root)))
        threading.Thread(target=_server.serve_forever,daemon=True).start()
    return f'http://127.0.0.1:{_server.server_port}/reader.html'
