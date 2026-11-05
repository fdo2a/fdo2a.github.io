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


@pytest.fixture
def drip_server():
    """codex #5: answers 200 at once, then drips the body one byte every 50 ms (never stalls
    long enough for a per-socket timeout). `headers_too` drips the header block instead."""
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('127.0.0.1', 0))
    s.listen(4)
    stop = threading.Event()

    def serve(c, path):
        head = b'HTTP/1.1 200 OK\r\nContent-Length: 100000\r\nX-Pad: ' + b'p' * 200 + b'\r\n\r\n'
        try:
            if path.startswith(b'/headers'):
                for i in range(len(head)):
                    if stop.is_set():
                        return
                    c.sendall(head[i:i + 1])
                    stop.wait(0.05)
            else:
                c.sendall(head)
            for _ in range(100000):
                if stop.is_set():
                    return
                c.sendall(b'x')
                stop.wait(0.05)
        except OSError:
            pass
        finally:
            c.close()

    def accept():
        s.settimeout(0.2)
        while not stop.is_set():
            try:
                c, _ = s.accept()
            except OSError:
                continue
            c.settimeout(5)
            try:
                req = c.recv(4096)
            except OSError:
                c.close()
                continue
            path = req.split(b' ')[1] if b' ' in req else b'/'
            threading.Thread(target=serve, args=(c, path), daemon=True).start()
    threading.Thread(target=accept, daemon=True).start()
    yield f'http://127.0.0.1:{s.getsockname()[1]}'
    stop.set()
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


@pytest.mark.parametrize('path', ['/body.zip', '/headers.zip'])
def test_codex_slow_drip_exits_1_within_max_time(monkeypatch, tmp_path, drip_server, capsys,
                                                 path):
    """codex #5: a server that keeps sending a byte at a time must not outlive --max-time."""
    import time
    t0 = time.monotonic()
    assert probe(monkeypatch, tmp_path, '--ff-probe-url', drip_server + path,
                 '--max-time', '1') == 1
    took = time.monotonic() - t0
    assert took < 1 + 0.75, took
    assert capsys.readouterr().out.startswith('000 ')
    assert list(tmp_path.iterdir()) == []


def test_codex_read_returning_late_is_cut_at_max_time(monkeypatch, capsys):
    """codex #5 injection: read() returns only after 0.5 s, max_time 0.1 → exit 1 near 0.1 s."""
    import time
    import urllib.request

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            time.sleep(0.5)
            return b'x'
        read1 = read

        def close(self):
            pass

    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: Resp())
    t0 = time.monotonic()
    assert cmd.ff_probe('http://example.invalid/x.zip', max_time=0.1) == 1
    assert time.monotonic() - t0 < 0.1 + 0.3


def test_close_waiting_on_read_lock_does_not_extend_deadline(monkeypatch, capsys):
    """codex impl review 2 #1: close() that waits on the reader's lock must not hold the
    probe past max_time, and the worker must not print a traceback."""
    import threading
    import time
    import urllib.request

    lock = threading.Lock()

    class Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            with lock:
                time.sleep(0.7)
                return b'x'
        read1 = read

        def close(self):
            with lock:
                pass

    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: Resp())
    t0 = time.monotonic()
    assert cmd.ff_probe('http://example.invalid/x.zip', max_time=0.1) == 1
    assert time.monotonic() - t0 < 0.1 + 0.3
    err = capsys.readouterr().err
    assert 'Traceback' not in err
