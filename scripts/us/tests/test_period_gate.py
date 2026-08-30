from us.period_gate import check

AGG = {"span": "weekly", "key": "2026-W34", "start_date": "2026-08-17",
       "end_date": "2026-08-21", "sessions": 5, "complete": True, "missing": [],
       "indices": {"S&P 500": {"pct": 2.0}},
       "sectors": {"Technology": {"pct": 20.0, "rank": 1}},
       "yields": {"10Y": {"chg_bp": -12.0}}}

SC = {"weighted": 0.33, "judged": 3, "neutral": 2, "neutral_share": 0.4,
      "assets": {"equities": {"verdict": "적중"}}}

RECAP = {"key": "2026-W34", "start_date": "2026-08-17", "end_date": "2026-08-21",
         "sessions": 5,
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
             "10년물은 12.0bp 내렸다. 5거래일을 정리했다. "
             "가중 점수 0.33, 무포지션 비율 0.4.</p>")


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

    축약형(8/21)은 가리지 않는다. 가리면 「적중은 3/4」 같은 비율까지 지워져 창작이
    통과한다 — 그래서 작성 스펙이 축약 날짜를 금지한다.
    """
    html = _html("<p>2026-08-17에 시작해 2026-08-21에 끝난 주간이다. "
                 "2026년 8월 20일도 같은 주다.</p>")
    assert not [x for x in check(html, AGG, SC, RECAP, "weekly") if '없는 수치' in x]


def test_small_integer_with_a_unit_is_still_checked():
    """「7% 올랐다」가 작은 정수라는 이유로 통과하던 구멍 — codex 검토 2026-08-30."""
    html = _html(f"{ALL_DAYS}주간으로 S&amp;P 500은 7% 올랐다.")
    assert any('7' in x and '없는 수치' in x for x in check(html, AGG, SC, RECAP, "weekly"))


def test_ratio_is_not_mistaken_for_a_date():
    """「적중은 3/4」를 날짜로 가리면 창작이 그대로 통과한다."""
    html = _html(f"{ALL_DAYS}주간으로 S&amp;P 500은 2.0%. 적중은 3/47이었다.")
    assert any('47' in x for x in check(html, AGG, SC, RECAP, "weekly"))


def test_a_daily_figure_cannot_authorise_a_wrong_entity():
    """어느 날 PMI가 57.3 이었다고 「S&P 500 +57.3%」가 통과하면 안 된다."""
    recap = dict(RECAP)
    html = _html(f"{ALL_DAYS}5거래일 동안 S&amp;P 500은 57.3% 올랐다. "
                 "Technology가 20.0%로 1위였다. 10년물은 12.0bp 내렸다. "
                 "가중 점수 0.33, 무포지션 비율 0.4.")
    v = check(html, AGG, SC, recap, "weekly")
    assert any('S&P 500' in x and '항목의 값이 아니다' in x for x in v)


def test_incomplete_aggregate_is_refused():
    agg = dict(AGG, complete=False, missing=['indices.Dow'])
    assert any('complete=false' in x for x in check(GOOD, agg, SC, RECAP, "weekly"))


def test_span_mismatch_is_refused():
    agg = dict(AGG, span='monthly')      # 월간 집계로 주간을 발행하려 한다
    assert any('span' in x for x in check(GOOD, agg, SC, RECAP, "weekly"))


def test_session_count_must_appear():
    html = GOOD.replace("5거래일을 정리했다. ", "")
    assert any('거래일 수' in x for x in check(html, AGG, SC, RECAP, "weekly"))


def test_aggregate_that_ends_before_the_last_post_is_refused():
    """야후 일별이 하루 늦으면 집계가 금요일을 빠뜨린 채 complete=true 로 나온다."""
    agg = dict(AGG, end_date="2026-08-20")
    assert any('통째로 빠진다' in x for x in check(GOOD, agg, SC, RECAP, "weekly"))


# ── 2026-08-30 회수분에서 실제로 통과했던 창작 셋 ────────────────────────────

AGG_W35 = {
    'span': 'weekly', 'key': '2026-W35', 'start_date': '2026-08-24',
    'end_date': '2026-08-28', 'sessions': 5, 'complete': True, 'missing': [],
    'indices': {'S&P 500': {'start': 7674.37, 'end': 7711.76, 'pct': 0.4872}},
    'yields': {'10Y': {'start': 4.738, 'end': 4.72, 'chg_bp': -1.8}},
}


def _wrap(sentence):
    return ('<html><body><p>2026-08-24부터 2026-08-28까지 5거래일을 정리한다. '
            f'{sentence}</p></body></html>')


def _recap(figures=()):
    return {'key': '2026-W35', 'posts': [{'date': '2026-08-24', 'headline': '',
                                          'figures': list(figures)}],
            'missing': []}


def _has(violations, needle):
    return any(needle in x for x in violations)


def test_a_rounding_may_not_erase_the_move():
    # +0.4872% 를 「0% 올랐다」로 적는 것은 반올림이 아니라 다른 말이다
    v = check(_wrap('S&P 500은 0% 올랐다.'), AGG_W35, None, _recap(), 'weekly')
    assert _has(v, '0'), v


def test_a_ordinary_rounding_still_passes():
    v = check(_wrap('S&P 500은 0.49% 올랐다.'), AGG_W35, None, _recap(), 'weekly')
    assert not _has(v, '창작 금지'), v
    assert not _has(v, '그 항목의 값이 아니다'), v


def test_b_a_price_level_may_not_be_quoted_as_a_return():
    # 7711.76 은 종가다. 허용 집합에 있다는 이유로 「% 올랐다」가 되면 안 된다
    v = check(_wrap('S&P 500은 7711.76% 올랐다.'), AGG_W35, None, _recap(), 'weekly')
    assert _has(v, '그 항목의 값이 아니다'), v


def test_b_the_level_itself_is_still_quotable():
    v = check(_wrap('S&P 500은 7711.76포인트로 마감했다.'), AGG_W35, None, _recap(), 'weekly')
    assert not _has(v, '그 항목의 값이 아니다'), v


def test_c_a_number_torn_out_of_a_date_is_not_a_quotable_figure():
    # 발행본에서 뜯긴 「-17」(2026-08-17)이 허용 토큰이 되면 -17% 창작이 통과한다
    from us.recap_source import post_figures
    figs = post_figures('<html><body><p>2026-08-17 발행본이다.</p></body></html>')
    assert '-17' not in figs, figs
