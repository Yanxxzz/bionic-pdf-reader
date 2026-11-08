from contextlib import contextmanager
import socket
from urllib.error import HTTPError
from urllib.parse import unquote, urljoin, urlsplit
from urllib.request import urlopen
import pytest

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


def test_selected_documents_are_independent_single_use_downloads(monkeypatch, tmp_path):
    monkeypatch.setattr(local_reader, 'DEFAULT_PORT', 0)
    first, second = tmp_path / '第一本 #1.pdf', tmp_path / 'second.pdf'
    first.write_bytes(b'%PDF-1.6 first')
    second.write_bytes(b'%PDF-1.7 second')
    with reader_instance() as home:
        def handoff(path):
            launch = local_reader.start_reader(path)
            assert launch.split('#')[0] == home
            assert path.name not in launch and str(path.parent) not in launch
            return urljoin(home, '/selected/' + urlsplit(launch).fragment.removeprefix('selected='))

        a, b = handoff(first), handoff(second)
        assert a != b
        for url, source in [(b, second), (a, first)]:
            with urlopen(url, timeout=5) as response:
                assert response.read() == source.read_bytes()
                assert unquote(response.headers['X-PDF-Name']) == source.name
                assert response.headers['Cache-Control'] == 'no-store'
            with pytest.raises(HTTPError) as consumed:
                urlopen(url, timeout=5)
            assert consumed.value.code == 404
        with pytest.raises(HTTPError) as adjacent:
            urlopen(urljoin(home, 'second.pdf'), timeout=5)
        assert adjacent.value.code == 404
        missing = handoff(second)
        second.unlink()
        with pytest.raises(HTTPError) as gone:
            urlopen(missing, timeout=5)
        assert gone.value.code == 404
