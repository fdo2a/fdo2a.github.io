import os

from kr.flows_intraday import ANCHORS, build_series, collect_pages, parse_intraday_flows

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "intraday_flows_kospi.html")


def _html():
    with open(FIX, encoding="utf-8") as f:
        return f.read()


def _row(t, individual=0, foreign=0, institution=0, **kw):
    base = {"t": t, "individual": individual, "foreign": foreign,
            "institution": institution, "fin_invest": 0, "insurance": 0,
            "trust": 0, "bank": 0, "other_fin": 0, "pension": 0, "other_corp": 0}
    base.update(kw)
    return base


# --- 파싱 -------------------------------------------------------------------

def test_parse_maps_columns_in_header_order():
    rows = parse_intraday_flows(_html())
    assert len(rows) == 10
    top = rows[0]
    assert top["t"] == "13:21"
    assert top["individual"] == -17281
    assert top["foreign"] == -4468
    assert top["institution"] == 21678
    assert top["fin_invest"] == 14964
    assert top["insurance"] == 397
    assert top["trust"] == 5573
    assert top["bank"] == -46
    assert top["other_fin"] == -19
    assert top["pension"] == 809
    assert top["other_corp"] == 72


def test_parse_institution_equals_sum_of_subcategories():
    """컬럼 매핑이 어긋나면 기관계 항등식이 깨진다 — 매핑 회귀 방어.

    Naver가 주체별로 따로 반올림해 ±1억 드리프트가 난다(실측 13:18 행). 매핑이
    밀리면 오차가 천 단위로 벌어지므로 이 허용치로도 회귀는 잡힌다.
    """
    subs = ("fin_invest", "insurance", "trust", "bank", "other_fin", "pension")
    for r in parse_intraday_flows(_html()):
        assert abs(r["institution"] - sum(r[k] for k in subs)) <= 2, r["t"]


def test_parse_empty_html():
    assert parse_intraday_flows("<html><body>no table</body></html>") == []


# --- 페이지 순회 -------------------------------------------------------------

def test_collect_pages_stops_on_repeated_last_page():
    p1 = [_row("10:00"), _row("09:58")]
    p2 = [_row("09:30"), _row("09:03")]
    calls = []

    def fetch(n):
        calls.append(n)
        return p1 if n == 1 else p2  # 3페이지부터 마지막 페이지가 반복된다

    rows = collect_pages(fetch, max_pages=10)
    assert calls == [1, 2, 3]
    assert [r["t"] for r in rows] == ["09:03", "09:30", "09:58", "10:00"]


def test_collect_pages_stops_on_empty_page():
    def fetch(n):
        return [_row("10:00")] if n == 1 else []

    assert [r["t"] for r in collect_pages(fetch, max_pages=10)] == ["10:00"]


def test_collect_pages_dedupes_by_time():
    def fetch(n):
        return {1: [_row("10:00", foreign=5)],
                2: [_row("10:00", foreign=9), _row("09:30", foreign=1)]}.get(n, [])

    rows = collect_pages(fetch, max_pages=5)
    assert [r["t"] for r in rows] == ["09:30", "10:00"]
    assert rows[1]["foreign"] == 5  # 먼저 본 값(최신 페이지)을 유지


def test_collect_pages_respects_max_pages():
    calls = []

    def fetch(n):
        calls.append(n)
        return [_row(f"1{n}:00")]

    collect_pages(fetch, max_pages=3)
    assert calls == [1, 2, 3]


# --- 시계열 가공 -------------------------------------------------------------

def test_build_series_snaps_last_observation_at_or_before_anchor():
    rows = [_row("09:28", foreign=10), _row("09:29", foreign=20),
            _row("09:31", foreign=30), _row("10:00", foreign=40)]
    s = build_series(rows)
    pts = {p["t"]: p["foreign"] for p in s["points"]}
    assert pts["09:30"] == 20   # 09:29가 앵커 이하 마지막
    assert pts["10:00"] == 40   # 정확히 앵커에 걸린 관측


def test_build_series_omits_anchors_without_observation():
    s = build_series([_row("14:05", foreign=7)])
    assert [p["t"] for p in s["points"]] == ["14:30", "15:00", "15:30"]
    assert all(p["foreign"] == 7 for p in s["points"])
    assert "09:30" not in [p["t"] for p in s["points"]]


def test_build_series_drops_after_hours_rows():
    rows = [_row("15:30", foreign=-100), _row("15:31", foreign=-999),
            _row("18:06", foreign=-777)]
    s = build_series(rows)
    assert s["last_t"] == "15:30"
    assert s["obs_count"] == 1
    assert s["session_last"]["foreign"] == -100
    assert s["extremes"]["foreign"]["min"]["v"] == -100  # 시간외 값이 극값에 안 들어간다


def test_build_series_extremes_carry_time_and_value():
    rows = [_row("09:30", foreign=100), _row("10:00", foreign=500),
            _row("11:00", foreign=-300), _row("15:30", foreign=-50)]
    ex = build_series(rows)["extremes"]["foreign"]
    assert ex["max"] == {"t": "10:00", "v": 500}
    assert ex["min"] == {"t": "11:00", "v": -300}


def test_build_series_extremes_keep_first_on_tie():
    rows = [_row("09:30", foreign=100), _row("10:00", foreign=100),
            _row("11:00", foreign=50)]
    assert build_series(rows)["extremes"]["foreign"]["max"]["t"] == "09:30"


def test_build_series_turns_detect_sign_flips():
    rows = [_row("09:30", foreign=500), _row("11:00", foreign=-200),
            _row("13:00", foreign=300), _row("15:00", foreign=-400)]
    turns = build_series(rows)["turns"]["foreign"]
    assert [(x["t"], x["from"], x["to"]) for x in turns] == [
        ("11:00", "순매수", "순매도"),
        ("13:00", "순매도", "순매수"),
        ("15:00", "순매수", "순매도"),
    ]


def test_build_series_zero_is_not_a_turn():
    rows = [_row("09:30", foreign=100), _row("10:00", foreign=0),
            _row("11:00", foreign=200)]
    assert build_series(rows)["turns"]["foreign"] == []


def test_build_series_turns_ignore_opening_noise():
    """개장 직후 0 근처 잡음 전환(그날 최대치의 5% 미만)은 세지 않는다."""
    rows = [_row("09:03", foreign=20), _row("09:04", foreign=-15),
            _row("10:00", foreign=3000), _row("14:00", foreign=-9000)]
    turns = build_series(rows)["turns"]["foreign"]
    assert [(x["t"], x["from"], x["to"]) for x in turns] == [
        ("14:00", "순매수", "순매도")]


def test_build_series_turn_carries_run_peak():
    rows = [_row("09:30", foreign=3000), _row("11:31", foreign=-500),
            _row("15:04", foreign=-9000), _row("15:30", foreign=-8000)]
    turn = build_series(rows)["turns"]["foreign"][0]
    assert turn["t"] == "11:31"
    assert turn["peak"] == {"t": "15:04", "v": -9000}


def test_build_series_tracks_all_three_investors():
    rows = [_row("09:30", individual=-1, foreign=2, institution=3),
            _row("15:00", individual=-9, foreign=-8, institution=7)]
    s = build_series(rows)
    assert set(s["extremes"]) == {"individual", "foreign", "institution"}
    assert set(s["turns"]) == {"individual", "foreign", "institution"}
    assert s["extremes"]["institution"]["max"]["v"] == 7
    assert s["turns"]["foreign"][0]["t"] == "15:00"


def test_build_series_metadata():
    rows = [_row("09:03"), _row("12:00"), _row("15:29")]
    s = build_series(rows)
    assert s["first_t"] == "09:03"
    assert s["last_t"] == "15:29"
    assert s["obs_count"] == 3


def test_build_series_empty_rows():
    s = build_series([])
    assert s["points"] == [] and s["session_last"] is None
    assert s["first_t"] is None and s["obs_count"] == 0
    assert s["extremes"]["foreign"] is None
    assert s["turns"]["foreign"] == []


def test_anchors_cover_regular_session_in_order():
    assert ANCHORS[0] == "09:30" and ANCHORS[-1] == "15:30"
    assert ANCHORS == sorted(ANCHORS)
    assert len(ANCHORS) == 13
