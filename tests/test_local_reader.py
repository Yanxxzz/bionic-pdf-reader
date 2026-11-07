from contextlib import contextmanager
import socket
from urllib.parse import urlsplit
from urllib.request import urlopen

from bionic_pdf import local_reader


@contextmanager
def reader_instance():
    previous, local_reader._server = local_reader._server, None
    try:
        yield local_reader.start_reader()
    finally:
        if local_reader._server is not None:
            local_reader._server.shutdown()
            local_reader._server.server_close()
        local_reader._server = previous


def test_reader_reuses_its_address_and_leaves_an_occupied_port_alone(monkeypatch):
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    monkeypatch.setattr(local_reader, 'DEFAULT_PORT', port)
    with reader_instance() as first:
        assert urlsplit(first).port == port
        assert local_reader.start_reader() == first
        with reader_instance() as second:
            assert second != first
            for url in (first, second):
                with urlopen(url, timeout=5) as response:
                    assert b'id="file-input"' in response.read()
    with reader_instance() as reopened:
        assert reopened == first
