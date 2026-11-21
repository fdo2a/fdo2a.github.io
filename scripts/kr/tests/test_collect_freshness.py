"""KR 수집 상태 칸의 `as_of`·성공 표시는 **원천이 말한 거래일**을 따른다(2026-11-17, 1a 구현 검토 1회차 #3·#4).

전에는 분봉 API 가 지난 거래일 봉을 돌려줘도 날짜를 버리고 시간만 남긴 뒤 그날 수집 성공으로 적었고(#3),
수급의 최신 행이 지난 날이어도 `as_of` 는 발행일이었다(#3). 세션 자료는 원자료가 비어 있지만 않으면 선물·환율·
해외 지수가 모두 지난 날 것이어도 성공이었다(#4). 오래된 원천을 오늘 날짜로 찍는 오류는 검사 쪽 오류 주입
시험(손으로 붙인 표시로 돈다)이 증명하지 못한다 — 그래서 여기 수집 쪽 단위 시험으로 둔다.
"""
import collect_kr_data
from kr import session as S
from kr import sources

D = "2026-11-16"
PREV = "2026-11-13"


def bar(day, hhmm, price):
    return {"localDateTime": day.replace("-", "") + hhmm + "00", "currentPrice": price}


# ── #3 분봉 ──────────────────────────────────────────────────────────────

def test_intraday_points_are_unchanged_until_the_switch_is_on():
    # 1a 를 켜기 전: 원천 거래일은 돌려주되(수집 상태가 쓴다) 실리는 점은 1a 전과 같다 — 앞 세션 꼬리도 그대로
    bars = [bar(PREV, "1500", 1.0), bar(PREV, "1530", 2.0), bar(D, "0900", 10.0), bar(D, "0930", 11.0)]
    day, pts = sources.dated_30min(bars)
    assert day == D
    assert pts == [{"t": "15:00", "close": 1.0}, {"t": "15:30", "close": 2.0},
                   {"t": "09:00", "close": 10.0}, {"t": "09:30", "close": 11.0}]


def test_intraday_keeps_the_source_date_and_drops_the_prior_session_tail(monkeypatch):
    # count=400 은 한 세션(390분)보다 길다 — 정상 응답에도 앞 세션 꼬리가 섞인다. 날짜는 마지막 봉의 것.
    from verification import inputs as I
    monkeypatch.setenv(I.TEST_ENV, "2026-11-17")                    # 켠 뒤의 동작
    bars = [bar(PREV, "1500", 1.0), bar(PREV, "1530", 2.0), bar(D, "0900", 10.0), bar(D, "0930", 11.0)]
    day, pts = sources.dated_30min(bars)
    assert day == D
    assert pts == [{"t": "09:00", "close": 10.0}, {"t": "09:30", "close": 11.0}]   # 앞 세션 15:30 이 섞이지 않는다
    assert sources.downsample_30min(bars) == pts
    assert sources.dated_30min([]) == (None, [])


def test_intraday_collect_is_partial_when_the_bars_are_from_another_day():
    pts = [{"t": "15:30", "close": 1.0}]
    ok = collect_kr_data.intraday_collect(D, {"KOSPI": pts, "KOSDAQ": pts}, {"KOSPI": D, "KOSDAQ": D})
    assert ok["status"] == "ok" and ok["as_of"] == D
    c = collect_kr_data.intraday_collect(D, {"KOSPI": pts, "KOSDAQ": pts}, {"KOSPI": PREV, "KOSDAQ": D})
    assert c["status"] == "partial" and c["as_of"] == PREV and "stale:KOSPI:2026-11-13" in c["missing"]
    c = collect_kr_data.intraday_collect(D, {"KOSPI": pts, "KOSDAQ": pts}, {"KOSPI": PREV, "KOSDAQ": PREV})
    assert c["status"] == "failed" and c["as_of"] == PREV                       # 재현: 전에는 ok·as_of=발행일
    c = collect_kr_data.intraday_collect(D, {"KOSPI": pts, "KOSDAQ": pts}, {})    # 날짜를 모르면 오늘 것이 아니다
    assert c["status"] == "failed"


# ── #3 수급 ──────────────────────────────────────────────────────────────

def test_flows_as_of_is_the_older_latest_row():
    checks = {"KOSPI": {"state": "ok"}, "KOSDAQ": {"state": "ok"}}
    same = {"KOSPI": {"latest_date": D, "stale": False}, "KOSDAQ": {"latest_date": D, "stale": False}}
    assert collect_kr_data.flows_collect(D, checks, same)["as_of"] == D
    old = {"KOSPI": {"latest_date": "2026-11-02", "stale": True}, "KOSDAQ": {"latest_date": D, "stale": False}}
    c = collect_kr_data.flows_collect(D, checks, old)
    assert c["as_of"] == "2026-11-02"                                            # 재현: 전에는 발행일
    assert c["status"] == "ok"                                                    # 수집 실패는 아니다 — 검사 쪽이 stale 로 본다


# ── #4 세션 ──────────────────────────────────────────────────────────────

HOL = {"us": {"dates": [], "valid_through": "2027-12-31"}, "jp": {"dates": [], "valid_through": "2027-12-31"}}


def ctx(us_as_of=PREV, fut=True, fx=True, peer_dates=None):
    peer_dates = peer_dates or {n: D for n, _ in S.PEERS}
    return {"report_date": D,
            "us_prev": {"as_of": us_as_of, "rows": {"S&P 500": 0.1}} if us_as_of else None,
            "us_futures_during_kr": {lab: ({"pct": 0.1, "last_t": "15:30"} if fut else None) for lab, _ in S.FUTURES},
            "asia_peers": {"rows": {n: 0.1 for n in peer_dates}, "dates": peer_dates},
            "usdkrw_intraday": {"close": 1400.0, "last_t": "15:30"} if fx else None}


def test_session_ok_only_when_every_window_is_that_day():
    assert collect_kr_data.session_collect(D, ctx(), HOL)["status"] == "ok"
    # 원자료는 있는데 그날 장중 창이 비었다 = 지난 날 봉뿐(재현: 전에는 원자료만 보고 ok)
    c = collect_kr_data.session_collect(D, ctx(fut=False, fx=False), HOL)
    assert c["status"] in ("partial", "failed") and "usdkrw" in c["missing"]
    assert any(m.startswith("futures:") for m in c["missing"])


def test_session_us_prev_must_be_the_prior_us_session():
    c = collect_kr_data.session_collect(D, ctx(us_as_of="2026-11-12"), HOL)
    assert c["status"] == "partial" and "us_prev:2026-11-12≠2026-11-13" in c["missing"]
    # 미국 휴장 — 달력이 말하는 직전 세션이면 정상
    hol = {**HOL, "us": {"dates": ["2026-11-13"], "valid_through": "2027-12-31"}}
    assert collect_kr_data.session_collect(D, ctx(us_as_of="2026-11-12"), hol)["status"] == "ok"
    # 달력이 그날을 덮지 않으면 판정할 수 없다 — 성공으로 두지 않는다
    c = collect_kr_data.session_collect(D, ctx(), {**HOL, "us": {"dates": [], "valid_through": "2026-10-31"}})
    assert c["status"] == "partial" and any(m.startswith("us_prev:") for m in c["missing"])


def test_session_peers_need_that_day():
    stale_all = {n: PREV for n, _ in S.PEERS}                                    # 11/16 실측: 네 시장 모두 11/13
    c = collect_kr_data.session_collect(D, ctx(peer_dates=stale_all), HOL)
    assert c["status"] == "partial" and f"peers:none_on_{D}" in c["missing"]
    # 일본은 달력이 있다 — 휴장이 아닌데 지난 날이면 결측
    one = dict({n: D for n, _ in S.PEERS}, **{"닛케이": PREV})
    c = collect_kr_data.session_collect(D, ctx(peer_dates=one), HOL)
    assert "peer:닛케이:2026-11-13" in c["missing"]
    hol = {**HOL, "jp": {"dates": [D], "valid_through": "2027-12-31"}}
    assert collect_kr_data.session_collect(D, ctx(peer_dates=one), hol)["status"] == "ok"
    # 달력이 없는 시장(항셍·상해·대만)의 한 곳만 지난 날이면 휴장과 가를 수 없어 detail 에만 남긴다
    hk = dict({n: D for n, _ in S.PEERS}, **{"항셍": PREV})
    c = collect_kr_data.session_collect(D, ctx(peer_dates=hk), HOL)
    assert c["status"] == "ok" and "항셍" in (c.get("detail") or "")


def test_session_without_market_data_or_holidays():
    c = collect_kr_data.session_collect(D, ctx(us_as_of=None), HOL)
    assert "us_market_data" in c["missing"]
    c = collect_kr_data.session_collect(D, ctx(), None)                            # 달력을 못 읽었다
    assert c["status"] == "partial" and any(m.startswith("calendar") for m in c["missing"])
