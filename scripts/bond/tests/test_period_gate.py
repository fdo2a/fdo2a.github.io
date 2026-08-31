from bond.period_gate import check

AGG = {
    'start': '2026-08-24', 'end': '2026-08-30',
    'first_session': '2026-08-24', 'last_session': '2026-08-27',
    'sessions': 4, 'complete': True, 'coverage_gap_days': (0, 1),
    'rates': {'us/10Y': {'start': 4.70, 'end': 4.67, 'bp': -3.0}},
    'credit': {'us_hy': {'start_bp': 269.0, 'end_bp': 263.0, 'bp': -6.0}},
    'stance_changes': [],
    'posts': [{'date': '2026-08-27', 'headline': 'x'}],
}


def _html(extra=''):
    return ('<p>2026-08-24부터 2026-08-30까지, 실제 세션은 2026-08-24 ~ 2026-08-27.</p>'
            '<p>미국 10년물은 4.70%에서 4.67%로 -3.0bp 내렸다.</p>'
            '<p><a href="../posts/2026-08-27.html">2026-08-27</a></p>' + extra)


class TestPeriodGate:
    def test_clean_passes(self):
        assert check(_html(), AGG) == []

    def test_missing_cover_range_is_caught(self):
        html = _html().replace('2026-08-30까지', '까지')
        assert any('종료일' in e for e in check(html, AGG))

    def test_missing_session_boundary_is_caught(self):
        # 실제 첫 세션이 커버 기간 시작과 다른 경우 — 그 사실이 본문에 없으면 걸린다
        agg = dict(AGG, first_session='2026-08-25')
        assert any('세션 경계' in e for e in check(_html(), agg))

    def test_incomplete_period_must_disclose(self):
        agg = dict(AGG, complete=False, coverage_gap_days=(0, 2))
        assert any('덮지 못했' in e for e in check(_html(), agg))

    def test_disclosure_satisfies_incomplete(self):
        agg = dict(AGG, complete=False, coverage_gap_days=(0, 2))
        html = _html('<p>구간 뒤로 2 영업일이 비어 있습니다.</p>')
        assert not any('덮지 못했' in e for e in check(html, agg))

    def test_hit_rate_without_sample_disclosure(self):
        html = _html('<p>적중률은 70%였다.</p>')
        assert any('표본' in e for e in check(html, AGG))

    def test_hit_rate_with_sample_disclosure_passes(self):
        html = _html('<p>누적 표본이 부족해 적중률은 내지 않는다.</p>')
        assert not any('표본' in e for e in check(html, AGG))

    def test_dropped_post_is_caught(self):
        # 커버 기간 표기에 같은 날짜가 들어 있어도 «링크가 없으면» 빠뜨린 것이다
        html = ('<p>2026-08-24부터 2026-08-30까지, 실제 세션은 '
                '2026-08-24 ~ 2026-08-27.</p>')
        assert any('빠졌다' in e for e in check(html, AGG))

    def test_invented_number_is_caught(self):
        html = _html('<p>스프레드는 512.5bp였다.</p>')
        assert any('집계에 없는 수치' in e for e in check(html, AGG))

    def test_internal_token_leak(self):
        html = _html('<p>allowed_grades 참조</p>')
        assert any('내부 용어' in e for e in check(html, AGG))

    def test_banned_vocabulary(self):
        assert any('금지 어휘' in e for e in check(_html('<p>buy-side</p>'), AGG))
