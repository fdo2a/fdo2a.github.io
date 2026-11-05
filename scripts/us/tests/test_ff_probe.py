"""--ff-probe: can this runner fetch the French factor file? Writes nothing, exits 0/1."""
import http.server
import os
import socket
import sys
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import collect_market_data as cmd  # noqa: E402


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/ok.zip':
            body = b'PK' + b'x' * 5000
            self.send_response(200)
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), _H)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


@pytest.fixture
def silent_socket():
    """Accepts the connection and never answers."""
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    s.listen(1)
    held = []
    stop = threading.Event()

    def accept():
        s.settimeout(0.2)
        while not stop.is_set():
            try:
                held.append(s.accept()[0])
            except OSError:
                pass
    t = threading.Thread(target=accept, daemon=True)
    t.start()
    yield f'http://127.0.0.1:{s.getsockname()[1]}/x.zip'
    stop.set()
    for c in held:
        c.close()
    s.close()


def probe(monkeypatch, tmp_path, *args):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['collect_market_data.py', '--ff-probe', *args])
    with pytest.raises(SystemExit) as e:
        cmd.main()
    return e.value.code


def test_ff_probe_200_exits_0(monkeypatch, tmp_path, server, capsys):
    assert probe(monkeypatch, tmp_path, '--ff-probe-url', server + '/ok.zip') == 0
    assert capsys.readouterr().out.split()[:2] == ['200', '5002']
    assert list(tmp_path.iterdir()) == []


def test_ff_probe_404_exits_1_writes_nothing(monkeypatch, tmp_path, server, capsys):
    assert probe(monkeypatch, tmp_path, '--ff-probe-url', server + '/gone.zip') == 1
    assert capsys.readouterr().out.startswith('404 ')
    assert list(tmp_path.iterdir()) == []


def test_ff_probe_timeout_exits_1(monkeypatch, tmp_path, silent_socket):
    import time
    t0 = time.monotonic()
    assert probe(monkeypatch, tmp_path, '--ff-probe-url', silent_socket, '--max-time', '2') == 1
    assert time.monotonic() - t0 < 10
    assert list(tmp_path.iterdir()) == []


def test_ff_probe_default_url_is_the_french_file():
    from fund.factors_check import FRENCH_URL
    assert FRENCH_URL.endswith('/F-F_Research_Data_Factors_daily_CSV.zip')
    assert FRENCH_URL.startswith('https://mba.tuck.dartmouth.edu/')
