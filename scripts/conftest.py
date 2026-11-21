import ipaddress
import os
import socket
import sys

import pytest

sys.path.insert(0, os.path.dirname(__file__))

# ── 1a 「자료 누락 차단」의 켠 뒤 판정을 시험하는 모듈 ─────────────────────────────────────────────
# `verification.inputs.EFFECTIVE` 가 None 인 동안 실제 판정은 1a 전과 같다. 아래 모듈은 켠 뒤의 판정(자료 없음 = 미완료,
# 2판 기록, 산출 범위 규칙, 재검사 경계)을 시험하므로 시험 전용 환경 변수로 스위치를 켠다 — 검사기가 하위 프로세스로
# 돌아 monkeypatch 가 닿지 않는다. 경계 날짜 `ENFORCE_FROM` 은 1a 시험들이 쓰던 2026-11-17 그대로다.
# 여기 없는 모듈은 전부 꺼진 채(= 운영과 같은 상태) 돈다.
ENFORCE_FROM = '2026-11-17'
ENFORCED_MODULES = frozenset((
    'test_checker_exit2', 'test_impl_review_r1', 'test_impl_review_r2', 'test_impl_review_r3',
    'test_input_mutations', 'test_inputs', 'test_inputs_policy', 'test_run_binding',
    'test_impl_review_r1_review', 'test_impl_review_r2_review',
    'test_impl_review_r4', 'test_impl_review_r5', 'test_macro_coverage',
))


@pytest.fixture(autouse=True)
def _input_health_switch(request, monkeypatch):
    name = request.module.__name__.rsplit('.', 1)[-1]
    if name in ENFORCED_MODULES or name.endswith('_1a'):
        monkeypatch.setenv('PREPUB_INPUTS_TEST_STRICT_FROM', ENFORCE_FROM)
        # 켠 뒤의 기록은 2판이다 — 알림 시험의 작은 레포도 2판 기록을 쓴다. 격리 사본용 날짜 사본도 같은 날로
        import review.corrector, review.style_pass, review.tests.prepub_fixture  # noqa: E401,F401
        for mod_name, mod in list(sys.modules.items()):      # `review.x` 와 `scripts.review.x` 두 이름으로 실릴 수 있다
            if mod_name.endswith('review.tests.prepub_fixture'):
                monkeypatch.setattr(mod, 'FORMAT', 'prepub-record/2')
            elif mod_name.endswith(('review.corrector', 'review.style_pass')):
                monkeypatch.setattr(mod, 'STRICT_FROM', ENFORCE_FROM)
    else:
        monkeypatch.delenv('PREPUB_INPUTS_TEST_STRICT_FROM', raising=False)


# ── 시험은 바깥 네트워크에 나가지 않는다 ──────────────────────────────────────
# 이 프로세스 안의 소켓 연결·이름 풀이를 막는다. 로컬(localhost·127.0.0.1·::1)과 유닉스 소켓만 통과.
# curl_cffi(libcurl)는 주소를 가리지 않고 전송 자체를 전부 거절한다 — 로컬 주소도 안 된다.
# 막힌 호출은 NetworkBlocked 를 내고, 코드가 그 예외를 삼켜도 그 시험을 실패로 만든다
# (시험 함수 밖 — 모듈·세션 fixture 정리 — 에서 삼켜진 것은 그 정리를 일으킨 시험의 teardown 오류).
# 정말 바깥이 필요한 시험은 @pytest.mark.network 를 달고, 기본으로는 건너뛴다(--run-network 로만 돈다).
# 알려진 한계(가드 밖):
#   - 자식 프로세스(subprocess 로 띄운 python 등).
#   - curl_cffi 의 cffi 바인딩(`curl_cffi._wrapper.lib`)을 직접 부르는 코드 — 이 저장소에는 없다.
#   - 모든 시험의 teardown 이 끝난 뒤(pytest_sessionfinish·atexit·플러그인 정리)에 삼켜진 호출:
#     한 프로세스 실행은 종료 상태로 실패하지만, xdist 일꾼의 종료 상태는 전달되지 않는다.

class NetworkBlocked(RuntimeError):
    """시험 중 바깥 네트워크 호출 — 원인 함수를 시험에서 바꿔 끼운다(monkeypatch)."""


_LOCAL_NAMES = {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
_violations = []      # (nodeid, 설명)
_allow = [False]      # network 표시 시험을 --run-network 로 돌릴 때만 True
_orig = {}


def _is_local_host(host):
    if host is None:
        return True
    if isinstance(host, (bytes, bytearray)):
        host = host.decode("ascii", "replace")
    h = str(host).strip().lower().rstrip(".")
    if h in _LOCAL_NAMES or h.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(h.strip("[]").split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None) is not None:      # ::ffff:127.0.0.1
        ip = ip.ipv4_mapped
    return ip.is_loopback


def _is_local_addr(sock, addr):
    fam = getattr(sock, "family", None)
    if getattr(socket, "AF_UNIX", None) is not None and fam == socket.AF_UNIX:
        return True
    if isinstance(addr, (str, bytes, bytearray)):   # 유닉스 소켓 경로
        return True
    if isinstance(addr, tuple) and addr:
        return _is_local_host(addr[0])
    return False


def _record(what):
    test = os.environ.get("PYTEST_CURRENT_TEST", "(수집 중)").split(" (")[0]
    _violations.append((test, what))


def _block(what):
    _record(what)
    raise NetworkBlocked(
        f"시험이 바깥 네트워크에 나가려 했다: {what} — 그 호출을 monkeypatch 로 바꿔 끼우거나, "
        f"정말 필요하면 @pytest.mark.network 를 단다(기본 건너뜀).")


def _wrap_sock(name):
    orig = getattr(socket.socket, name)

    def guarded(self, *args, **kwargs):
        addr = args[-1] if name == "sendto" and args else (args[0] if args else kwargs.get("address"))
        if not _allow[0] and not _is_local_addr(self, addr):
            _block(f"socket.{name}({addr!r})")
        return orig(self, *args, **kwargs)

    guarded.__wrapped__ = orig
    return orig, guarded


def _wrap_resolver(name):
    orig = getattr(socket, name)

    def guarded(host, *args, **kwargs):
        if not _allow[0] and not _is_local_host(host):
            _block(f"socket.{name}({host!r})")
        return orig(host, *args, **kwargs)

    guarded.__wrapped__ = orig
    return orig, guarded


def _wrap_curl_cffi():
    """yfinance 는 curl_cffi(libcurl)로 나간다 — 파이썬 socket 을 거치지 않는다.

    libcurl 안에서 일어나는 일(리디렉트·프록시·이름 풀이)은 파이썬에서 볼 수 없으므로 주소를 가려
    통과시키지 않는다. 전송이 시작되는 두 자리 — 동기 `Curl.perform`(curl_easy_perform), 비동기
    `AsyncCurl.add_handle`(curl_multi_add_handle) — 에서 **로컬 주소를 포함해 전부** 거절한다.
    Session·AsyncSession·`curl_cffi.requests.get` 류·WebSocket 연결은 모두 이 둘 중 하나를 거친다
    (curl_cffi 0.16 확인). --run-network 로 도는 network 표시 시험에서만 통과한다.
    """
    try:
        from curl_cffi.aio import AsyncCurl
        from curl_cffi.curl import Curl
    except Exception:
        return

    def _url(handle):      # 알림에 붙일 주소 — 판정에는 쓰지 않는다
        try:
            from curl_cffi.const import CurlInfo
            return handle.getinfo(CurlInfo.EFFECTIVE_URL).decode("utf-8", "replace")[:120]
        except Exception:
            return "?"

    def _guard(cls, name, label, handle_of):
        orig = getattr(cls, name)

        def guarded(self, *args, **kwargs):
            if not _allow[0]:
                _block(f"curl_cffi {label} {_url(handle_of(self, args, kwargs))}")
            return orig(self, *args, **kwargs)

        guarded.__wrapped__ = orig
        _orig[("curl", name)] = orig
        setattr(cls, name, guarded)

    _guard(Curl, "perform", "전송(Curl.perform)", lambda self, a, k: self)
    _guard(AsyncCurl, "add_handle", "비동기 전송(AsyncCurl.add_handle)",
           lambda self, a, k: a[0] if a else k.get("curl"))


def _install():
    if _orig:
        return
    for name in ("connect", "connect_ex", "sendto"):
        _orig[("sock", name)], g = _wrap_sock(name)
        setattr(socket.socket, name, g)
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex"):
        _orig[("mod", name)], g = _wrap_resolver(name)
        setattr(socket, name, g)
    _wrap_curl_cffi()


_install()


def pytest_addoption(parser):
    parser.addoption("--run-network", action="store_true", default=False,
                     help="@pytest.mark.network 시험도 돌린다(바깥 네트워크 허용)")


def pytest_configure(config):
    config.addinivalue_line("markers", "network: 바깥 네트워크가 꼭 필요한 시험 — 기본 건너뜀, --run-network 로 돈다")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-network"):
        return
    skip = pytest.mark.skip(reason="바깥 네트워크 시험 — --run-network 로만 돈다")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


_reported = [0]   # 시험 밖 기록 가운데 이미 알린 개수


@pytest.fixture(autouse=True)
def _network_guard(request):
    # 수집 중이거나 앞 시험의 teardown 뒤에 막혀 삼켜진 호출 — 이 시험의 setup 을 실패시켜 알린다.
    stray = _take_stray()
    if stray:
        pytest.fail("시험 함수 밖(fixture·수집)에서 바깥 네트워크 호출이 막혔다:\n  "
                    + "\n  ".join(f"{t}: {w}" for t, w in stray[:10]), pytrace=False)
    allow = "network" in request.node.keywords and request.config.getoption("--run-network")
    _allow[0] = bool(allow)
    start = len(_violations)
    request.node._netguard_start = start
    try:
        yield
    finally:
        _allow[0] = False
    caught = [w for _, w in _violations[start:]]
    del _violations[start:]
    if caught:
        pytest.fail("바깥 네트워크 호출이 막혔다(코드가 예외를 삼켰어도 실패로 친다):\n  "
                    + "\n  ".join(caught[:10]), pytrace=False)


def _take_stray():
    stray = _violations[_reported[0]:]
    _reported[0] = len(_violations)
    return stray


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """모듈·세션 fixture 정리에서 삼켜진 호출 — 그 정리를 일으킨 시험의 teardown 을 실패시킨다.

    마지막 시험(nextitem 없음)의 teardown 에서 세션 fixture 까지 다 정리되므로, xdist 일꾼에서도
    보통의 시험 오류로 전달된다(일꾼의 종료 상태에 기대지 않는다).
    """
    exc = None
    try:
        res = yield
    except BaseException as e:      # 앞선 teardown 오류는 아래에서 그대로 다시 낸다
        exc = e
        res = None
    stray = _take_stray()
    if stray:
        pytest.fail("시험 함수 밖(fixture 정리)에서 바깥 네트워크 호출이 막혔다:\n  "
                    + "\n  ".join(f"{t}: {w}" for t, w in stray[:10])
                    + (f"\n(같은 teardown 의 다른 오류: {exc!r})" if exc is not None else ""), pytrace=False)
    if exc is not None:
        raise exc
    return res


def pytest_sessionfinish(session, exitstatus):
    """모든 teardown 뒤에 막혀 삼켜진 호출 — 종료 상태로만 알릴 수 있다(xdist 일꾼에서는 전달 안 됨)."""
    if len(_violations) > _reported[0]:
        lines = "\n  ".join(f"{t}: {w}" for t, w in _violations[_reported[0]:][:20])
        sys.stderr.write(f"\n[network guard] 시험 함수 밖에서 바깥 네트워크 호출이 막혔다:\n  {lines}\n")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.fixture
def netguard(request):
    """가드 자체를 시험할 때만 — 이 시험에서 막힌 호출을 꺼내 가고, 꺼낸 것은 실패로 치지 않는다."""
    class _G:
        Blocked = NetworkBlocked
        is_local_host = staticmethod(_is_local_host)

        @staticmethod
        def consume():
            start = getattr(request.node, "_netguard_start", len(_violations))
            got = [w for _, w in _violations[start:]]
            del _violations[start:]
            return got
    return _G
