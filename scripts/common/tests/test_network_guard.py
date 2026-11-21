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


def test_curl_cffi_external_url_is_blocked(netguard):
    curl = pytest.importorskip("curl_cffi.curl")
    from curl_cffi.const import CurlOpt
    c = curl.Curl()
    try:
        with pytest.raises(netguard.Blocked):
            c.setopt(CurlOpt.URL, b"https://query2.finance.yahoo.com/v8/finance/chart/%5EN225")
        c.setopt(CurlOpt.URL, b"http://127.0.0.1:9/")   # 로컬은 통과
    finally:
        c.close()
    assert len(netguard.consume()) == 1


def test_curl_cffi_schemeless_url_is_blocked(netguard):
    curl = pytest.importorskip("curl_cffi.curl")
    from curl_cffi.const import CurlOpt
    c = curl.Curl()
    try:
        with pytest.raises(netguard.Blocked):
            c.setopt(CurlOpt.URL, b"example.com/x")
        with pytest.raises(netguard.Blocked):
            c.setopt(CurlOpt.PROXY, b"http://proxy.example.com:8080")
    finally:
        c.close()
    assert len(netguard.consume()) == 2


def _local_http(handler_body):
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            handler_body(self)

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def test_curl_cffi_local_get_passes():
    creq = pytest.importorskip("curl_cffi.requests")

    def ok(h):
        h.send_response(200)
        h.send_header("Content-Length", "2")
        h.end_headers()
        h.wfile.write(b"ok")
    srv = _local_http(ok)
    try:
        r = creq.get(f"http://127.0.0.1:{srv.server_port}/", timeout=10)
        assert r.status_code == 200 and r.content == b"ok"
    finally:
        srv.shutdown()


def test_curl_cffi_redirect_from_localhost_to_outside_does_not_leave(netguard):
    """libcurl 이 혼자 따라가는 리디렉트 — 파이썬 setopt 를 다시 부르지 않는다(codex 구현 검토 1회)."""
    creq = pytest.importorskip("curl_cffi.requests")

    def redirect(h):
        h.send_response(302)
        h.send_header("Location", "http://example.com/leak")
        h.send_header("Content-Length", "0")
        h.end_headers()
    srv = _local_http(redirect)
    try:
        with pytest.raises(Exception):
            creq.get(f"http://127.0.0.1:{srv.server_port}/", timeout=10, allow_redirects=True)
    finally:
        srv.shutdown()
    got = netguard.consume()
    assert any("example.com" in w for w in got), got


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
