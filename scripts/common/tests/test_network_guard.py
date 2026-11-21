"""scripts/conftest.py 의 네트워크 가드 — 바깥은 막고 로컬은 통과시키는지."""
import os
import socket
import tempfile
import threading

import pytest


def test_external_connect_is_blocked(netguard):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(netguard.Blocked):
            s.connect(("93.184.216.34", 80))
        with pytest.raises(netguard.Blocked):
            s.connect_ex(("93.184.216.34", 443))
    finally:
        s.close()
    assert len(netguard.consume()) == 2


def test_external_dns_is_blocked(netguard):
    with pytest.raises(netguard.Blocked):
        socket.getaddrinfo("example.com", 443)
    with pytest.raises(netguard.Blocked):
        socket.gethostbyname("example.com")
    assert len(netguard.consume()) == 2


def test_swallowed_block_is_still_recorded(netguard):
    try:
        socket.create_connection(("example.com", 80), timeout=1)
    except Exception:
        pass   # 수집 코드가 흔히 하는 것처럼 삼켜도
    assert netguard.consume(), "삼킨 호출도 기록돼야 시험 끝에 실패로 칠 수 있다"


def test_udp_sendto_external_is_blocked(netguard):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        with pytest.raises(netguard.Blocked):
            s.sendto(b"x", ("8.8.8.8", 53))
    finally:
        s.close()
    assert netguard.consume()


# ── curl_cffi: 주소를 가리지 않고 전송 자체를 거절한다(로컬 포함) ──────────────────
# libcurl 안의 리디렉트·프록시·이름 풀이는 파이썬에서 볼 수 없다(codex 구현 검토 1·2회) — 그래서
# 전송이 시작되는 두 자리(Curl.perform, AsyncCurl.add_handle)에서 전부 막는다.

class _Counting:
    """요청 수를 세는 로컬 서버 — 막힌 전송은 여기까지 오지 못해야 한다."""

    def __enter__(self):
        from http.server import BaseHTTPRequestHandler, HTTPServer
        self.hits = hits = []

        class H(BaseHTTPRequestHandler):
            def do_GET(self):
                hits.append(self.path)
                self.send_response(302)      # 통과됐다면 바깥으로 리디렉트했을 서버
                self.send_header("Location", "http://example.com/leak")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.srv.server_port}/"
        return self

    def __exit__(self, *exc):
        self.srv.shutdown()
        self.srv.server_close()


def _refused(netguard, srv, call):
    with pytest.raises(netguard.Blocked):
        call()
    got = netguard.consume()
    assert len(got) == 1 and "curl_cffi" in got[0], got
    assert srv.hits == [], "막힌 전송이 서버에 닿았다"


def test_curl_cffi_module_helper_is_refused_even_for_localhost(netguard):
    creq = pytest.importorskip("curl_cffi.requests")
    with _Counting() as srv:
        _refused(netguard, srv, lambda: creq.get(srv.url, timeout=10, allow_redirects=True))


def test_curl_cffi_session_is_refused(netguard):
    creq = pytest.importorskip("curl_cffi.requests")
    with _Counting() as srv, creq.Session() as s:
        _refused(netguard, srv, lambda: s.get(srv.url, timeout=10))
        _refused(netguard, srv, lambda: s.post(srv.url, data=b"x", timeout=10))


def test_curl_cffi_stream_is_refused(netguard):
    """stream=True 는 perform 을 다른 스레드에서 부르고 그 예외를 curl_cffi 가 삼킨다 — 예외가
    호출자에게 오지 않아도 기록은 남고(그래서 시험은 실패하고), 멈추지 않으며, 서버에 닿지 않는다."""
    creq = pytest.importorskip("curl_cffi.requests")
    with _Counting() as srv, creq.Session() as s:
        try:
            s.get(srv.url, timeout=10, stream=True)
        except Exception:
            pass
        got = netguard.consume()
        assert len(got) == 1 and "curl_cffi" in got[0], got
        assert srv.hits == []


def test_curl_cffi_async_session_is_refused(netguard):
    """비동기 전송은 Curl.perform 을 거치지 않는다(codex 구현 검토 2회) — add_handle 에서 막는다."""
    creq = pytest.importorskip("curl_cffi.requests")
    import asyncio

    async def go(url, **kw):
        async with creq.AsyncSession() as s:
            return await asyncio.wait_for(s.get(url, timeout=10, **kw), 20)

    with _Counting() as srv:
        _refused(netguard, srv, lambda: asyncio.run(go(srv.url)))
        _refused(netguard, srv, lambda: asyncio.run(go(srv.url, stream=True)))


def test_curl_cffi_raw_perform_is_refused_whatever_the_options(netguard):
    """프록시·NOPROXY 를 어떻게 두든(빈 값 포함) 전송이 시작되지 않는다."""
    curl = pytest.importorskip("curl_cffi.curl")
    from curl_cffi.const import CurlOpt
    with _Counting() as srv:
        for url in (srv.url.encode(), b"http://[::ffff:127.0.0.1]:%d/" % srv.srv.server_port,
                    b"https://query2.finance.yahoo.com/v8/finance/chart/%5EN225"):
            c = curl.Curl()
            try:
                c.setopt(CurlOpt.URL, url)
                c.setopt(CurlOpt.PROXY, b"")
                c.setopt(CurlOpt.NOPROXY, b"*")
                c.setopt(CurlOpt.FOLLOWLOCATION, 1)
                _refused(netguard, srv, c.perform)
            finally:
                c.close()


def test_curl_cffi_swallowed_refusal_is_still_recorded(netguard):
    creq = pytest.importorskip("curl_cffi.requests")
    with _Counting() as srv:
        try:
            creq.get(srv.url, timeout=10)
        except Exception:
            pass
        assert len(netguard.consume()) == 1 and srv.hits == []


def test_localhost_tcp_passes():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    t = threading.Thread(target=lambda: srv.accept()[0].close())
    t.start()
    try:
        with socket.create_connection(("localhost", port), timeout=5):
            pass
    finally:
        t.join(5)
        srv.close()


def test_unix_socket_passes():
    if not hasattr(socket, "AF_UNIX"):
        pytest.skip("유닉스 소켓 없음")
    d = tempfile.mkdtemp(dir="/tmp")
    path = os.path.join(d, "s")
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(path)
    srv.listen(1)
    try:
        c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        c.connect(path)
        c.close()
    finally:
        srv.close()
        os.unlink(path)
        os.rmdir(d)


@pytest.mark.parametrize("host,local", [
    ("localhost", True), ("127.0.0.1", True), ("::1", True), ("127.5.5.5", True),
    ("[::1]", True), (None, True), ("api.stock.naver.com", False), ("10.0.0.1", False),
    ("0.0.0.0", False), ("localhost.evil.com", False), ("::ffff:127.0.0.1", True),
    ("::ffff:8.8.8.8", False), ("localhost.", True),
])
def test_local_host_classification(netguard, host, local):
    assert netguard.is_local_host(host) is local


def test_swallowed_block_in_a_module_fixture_fails_the_next_test(tmp_path):
    """모듈 fixture 에서 막혀 삼켜진 호출 — 시험 함수 밖이라도 다음 시험이 실패한다(xdist 일꾼에서도)."""
    import subprocess
    import sys
    guard = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "conftest.py")
    (tmp_path / "conftest.py").write_text(f"exec(open({guard!r}, encoding='utf-8').read())\n")
    (tmp_path / "test_inner.py").write_text(
        "import socket\nimport pytest\n\n"
        "@pytest.fixture(scope='module')\n"
        "def leaky():\n"
        "    try:\n"
        "        socket.getaddrinfo('example.com', 443)\n"
        "    except Exception:\n"
        "        pass\n\n"
        "def test_a(leaky):\n    pass\n\n"
        "def test_b():\n    pass\n")
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "no:xdist",
                        str(tmp_path)], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert r.returncode != 0, r.stdout
    assert "1 passed, 1 error" in r.stdout, r.stdout
    assert "example.com" in r.stdout


_LEAKY_SESSION = (
    "import socket\nimport pytest\n\n"
    "@pytest.fixture(scope='session')\n"
    "def leaky():\n"
    "    yield\n"
    "    try:\n"
    "        socket.getaddrinfo('example.com', 443)\n"
    "    except Exception:\n"
    "        pass\n\n"
    "def test_a(leaky):\n    pass\n\n"
    "def test_b(leaky):\n    pass\n")


@pytest.mark.parametrize("extra", [["-p", "no:xdist"], ["-n", "2"]], ids=["serial", "xdist"])
def test_swallowed_block_in_session_fixture_cleanup_fails_the_last_test(tmp_path, extra):
    """세션 fixture 정리(마지막 시험 뒤)에서 삼켜진 호출 — 일꾼의 종료 상태가 아니라 마지막 시험의
    teardown 오류로 드러나야 xdist 에서도 전체 실행이 실패한다(codex 구현 검토 2회)."""
    import subprocess
    import sys
    if extra[0] == "-n":
        pytest.importorskip("xdist")
    guard = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "conftest.py")
    (tmp_path / "conftest.py").write_text(f"exec(open({guard!r}, encoding='utf-8').read())\n")
    (tmp_path / "test_inner.py").write_text(_LEAKY_SESSION)
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *extra, str(tmp_path)],
                       cwd=tmp_path, capture_output=True, text=True, timeout=180)
    assert r.returncode != 0, r.stdout
    assert "2 passed" in r.stdout and "error" in r.stdout, r.stdout
    assert "example.com" in r.stdout
