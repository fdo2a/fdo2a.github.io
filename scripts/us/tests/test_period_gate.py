from us.period_gate import check

AGG = {"span": "weekly", "key": "2026-W34", "start_date": "2026-08-17",
       "end_date": "2026-08-21", "sessions": 5,
       "indices": {"S&P 500": {"pct": 2.0}},
       "sectors": {"Technology": {"pct": 20.0, "rank": 1}},
       "yields": {"10Y": {"chg_bp": -12.0}}}

SC = {"weighted": 0.33, "judged": 3, "neutral": 2, "neutral_share": 0.4,
      "assets": {"equities": {"verdict": "적중"}}}

RECAP = {"start_date": "2026-08-17", "end_date": "2026-08-21", "sessions": 5,
         "posts": [
             {"date": "2026-08-17", "headline": "월요일", "sections": [], "figures": ["0.31%"]},
             {"date": "2026-08-18", "headline": "화요일", "sections": [], "figures": ["1.42%"]},
             {"date": "2026-08-19", "headline": "수요일", "sections": [], "figures": ["0.88%"]},
             {"date": "2026-08-20", "headline": "목요일", "sections": [], "figures": ["57.3"]},
             {"date": "2026-08-21", "headline": "금요일", "sections": [], "figures": ["3.22%"]}],
         "missing": []}


def _html(body):
    return f"<html><body><main>{body}</main></body></html>"


ALL_DAYS = ("2026-08-17에 0.31% 밀렸고, 2026-08-18에 1.42% 되돌렸다. "
            "2026-08-19은 0.88%, 2026-08-20에 지표가 57.3으로 나왔고 "
            "2026-08-21에 3.22% 올랐다. ")

GOOD = _html(f"<p>{ALL_DAYS}주간으로 S&amp;P 500은 2.0%, Technology가 20.0%로 1위였다. "
             "10년물은 12.0bp 내렸다. 가중 점수 0.33, 무포지션 비율 0.4.</p>")


def test_clean_report_passes():
    assert check(GOOD, AGG, SC, RECAP, "weekly") == []


def test_number_absent_from_every_source_is_caught():
    html = GOOD.replace("2.0%", "2.7%")
    assert any("2.7" in x for x in check(html, AGG, SC, RECAP, "weekly"))


def test_number_quoted_from_a_daily_post_is_allowed():
    # 발행본에 있던 수치는 총정리에 인용해도 창작이 아니다
    html = GOOD.replace("3.22%", "3.22%").replace("1위였다", "1위였다. 금 3.22% 급등")
    assert check(html, AGG, SC, RECAP, "weekly") == []


def test_scorecard_number_must_match_the_file():
    html = GOOD.replace("0.33", "0.51")
    assert any("0.51" in x for x in check(html, AGG, SC, RECAP, "weekly"))


def test_unconfirmed_marker_is_banned():
    v = check(_html(f"<p>{ALL_DAYS}[확인필요]</p>"), AGG, SC, RECAP, "weekly")
    assert any("확인필요" in x for x in v)


def test_buyside_wording_is_banned():
    v = check(GOOD + "<p>buy-side 관점</p>", AGG, SC, RECAP, "weekly")
    assert any("buy-side" in x for x in v)


def test_internal_filenames_must_not_leak():
    for term in ("weekly.json", "recap_source.json", "_sessions", "scorecard.json"):
        v = check(GOOD + f"<p>{term} 참조</p>", AGG, SC, RECAP, "weekly")
        assert any(term in x for x in v), term


def test_coverage_window_must_be_stated():
    v = check(_html("<p>S&amp;P 500은 2.0% 올랐다.</p>"), AGG, SC, RECAP, "weekly")
    assert any("커버 기간" in x for x in v)


def test_every_trading_day_must_be_mentioned():
    # 총정리인데 하루를 통째로 빠뜨리면 그날 사건이 사라진다
    html = GOOD.replace("2026-08-19은 0.88%, ", "")
    v = check(html, AGG, SC, RECAP, "weekly")
    assert any("2026-08-19" in x for x in v)


def test_missing_source_post_is_reported():
    recap = {**RECAP, "missing": ["2026-08-18"]}
    v = check(GOOD, AGG, SC, recap, "weekly")
    assert any("발행본이 없다" in x and "2026-08-18" in x for x in v)


def test_thin_sample_must_be_disclosed():
    sc = {**SC, "rollup": {"last_4": {"insufficient": True, "periods": 1}}}
    assert any("표본 부족" in x for x in check(GOOD, AGG, sc, RECAP, "weekly"))
    ok = GOOD.replace("0.4.", "0.4. 누적 표본 부족으로 당기만 싣는다.")
    assert check(ok, AGG, sc, RECAP, "weekly") == []


def test_dates_are_not_read_as_negative_numbers():
    """「2026-08-18」에서 -18 이 뜯겨 나오면 날짜를 부를 때마다 발행이 막힌다.

    한글도 단어문자라 \\b 로는 「2026-08-17에」의 경계가 서지 않는다 — 실행 중 발견.
    """
    html = _html("<p>2026-08-17에 시작해 2026-08-21에 끝난 주간이다. "
                 "2026년 8월 20일과 8/21도 같은 주다.</p>")
    assert not [x for x in check(html, AGG, SC, RECAP, "weekly") if '없는 수치' in x]
