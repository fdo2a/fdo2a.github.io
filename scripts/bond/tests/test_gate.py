import re

from bond.gate import _numbers, check, data_tokens

MARKET = {'report_date': '2026-08-27', 'complete': True, 'missing': [],
          'us_curve': {'10Y': {'level': 4.67, 'date': '2026-08-27'}}}
METRICS = {'report_date': '2026-08-27',
           'curves': {'us': {'spread_2s10s_bp': 47.0, 'spread_5s30s_bp': 81.0}},
           'credit': {'us_hy': {'bp': 263.0}}}
EVAL = {'report_date': '2026-08-27',
        'assets': {'duration': {'allowed_grades': [0]},
                   'curve': {'allowed_grades': [0]},
                   'credit': {'allowed_grades': [0, 1]}}}
BOOK = {'report_date': '2026-08-27',
        'assets': {'duration': {'grade': 0}, 'curve': {'grade': 0},
                   'credit': {'grade': 0}}}


def _html(body, grades=(0, 0, 0)):
    marks = ''.join(
        f'<span data-axis-key="{k}" data-grade="{g}">{lbl}</span>'
        for (k, g, lbl) in [('duration', grades[0],
                             {0: '중립 듀레이션', 1: '롱 바이어스'}[grades[0]]),
                            ('curve', grades[1],
                             {0: '커브 중립', 1: '완만한 스티프너'}[grades[1]]),
                            ('credit', grades[2],
                             {0: '크레딧 중립', 1: '소폭 OW', 2: '크레딧 OW'}[grades[2]])])
    return ('<section id="b-2"><p data-standing="rates">2026-08-27 최근 2년 가운데 '
            '이보다 높았던 날이 나흘뿐이다. 노출을 역산했다</p>'
            + 'x' * 3200 + '</section>'
            '<section id="b-6"><p data-standing="credit">최근 2년 가운데 이보다 '
            '좁았던 날이 사흘뿐이다</p></section>'
            '<section id="b-7"><p data-standing="fx">2026-08-27</p></section>'
            f'<section id="b-9">{marks}{body}</section>')


class TestNumberExtraction:
    def test_dates_are_not_negative_numbers(self):
        assert -27.0 not in _numbers('2026-08-27에 발표됐다')

    def test_tenor_ranges_are_not_negative_numbers(self):
        # 「5년-30년」에서 -30 을 뜯어내면 안 된다
        assert -30.0 not in _numbers('5년-30년 81bp')

    def test_real_negatives_survive(self):
        assert -4.0 in _numbers('스프레드가 -4.0bp 좁아졌다')


class TestDataTokens:
    def test_unit_conversion_is_not_allowed(self):
        # 10년물 4.67 이 ×100 되어 「스프레드 467bp」를 통과시키던 세탁 경로를 막았다
        toks = data_tokens({'us10y': 4.67}, {}, {})
        assert 4.67 in toks and 467.0 not in toks

    def test_integer_rounding_is_not_allowed(self):
        # 달러지수 99.16 이 99 가 되어 「금리차 99bp」를 통과시키면 안 된다
        assert 99.0 not in data_tokens({'dxy': 99.16}, {}, {})

    def test_display_rounding_is_allowed(self):
        toks = data_tokens({'oas': 25.93652}, {}, {})
        assert 25.9 in toks and 25.94 in toks

    def test_tenor_labels_are_not_measurements(self):
        assert 30.0 not in _numbers('30년물은 5.19%였다')

    def test_three_decimals(self):
        assert 5.012 in data_tokens({'x': 5.0121}, {}, {})


class TestCheck:
    def test_clean_report_passes(self):
        assert check(_html('<p>47bp</p>'), MARKET, METRICS, EVAL, BOOK) == []

    def test_percentile_word_is_refused(self):
        # 계산에 맞는 말이 읽는 사람에게도 맞는 말은 아니다(2026-09-02 사용자 지적).
        errs = check(_html('<p>하이일드는 0.5 백분위다</p>'), MARKET, METRICS, EVAL, BOOK)
        assert any('백분위' in e for e in errs)

    def test_report_that_never_says_where_the_market_stands_is_refused(self):
        html = _html('<p>47bp</p>').replace(
            '최근 2년 가운데 이보다 높았던 날이 나흘뿐이다.', '금리가 올랐다.')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('어디에 서 있는지' in e for e in errs)

    def test_empty_cliche_does_not_count_as_saying_where_it_stands(self):
        # 「이보다 높았던 날을 확인한다」는 날 수를 말하지 않는다 — 통과하면 안 된다.
        html = _html('<p>47bp</p>').replace(
            '이보다 높았던 날이 나흘뿐이다.', '이보다 높았던 날을 확인한다.')
        assert any('금리 위치 문단' in e for e in check(html, MARKET, METRICS, EVAL, BOOK))

    def test_standing_sentence_in_another_section_does_not_cover_the_asset(self):
        # 다른 섹션의 상투구 하나로 그 자산의 위치 문단이 면제되면 안 된다.
        html = _html('<p>최근 2년 가운데 이보다 넓었던 날이 나흘뿐이다</p>').replace(
            '최근 2년 가운데 이보다 높았던 날이 나흘뿐이다.', '금리가 올랐다.')
        assert any('금리 위치 문단' in e for e in check(html, MARKET, METRICS, EVAL, BOOK))

    def test_tag_split_percentile_is_still_caught(self):
        errs = check(_html('<p>2년 표본에서 백<span></span>분위 상위다</p>'),
                     MARKET, METRICS, EVAL, BOOK)
        assert any('백분위' in e for e in errs)

    def test_invented_session_count_is_caught(self):
        errs = check(_html('<p>최근 999거래일 가운데 이보다 높았던 날이 777일뿐이다</p>'),
                     MARKET, METRICS, EVAL, BOOK)
        assert any('표본·날 수' in e for e in errs)

    def test_invented_number_is_caught(self):
        errs = check(_html('<p>스프레드는 999.5bp였다</p>'), MARKET, METRICS, EVAL, BOOK)
        assert any('데이터에 없는 수치' in e for e in errs)

    def test_wrong_label_for_grade(self):
        html = _html('<p>x</p>').replace('>커브 중립<', '>스티프너<')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('라벨은' in e for e in errs)

    def test_grade_outside_allowed(self):
        errs = check(_html('<p>x</p>', grades=(1, 0, 0)), MARKET, METRICS, EVAL, BOOK)
        assert any('허용되지 않는다' in e for e in errs)

    def test_two_step_move_is_caught(self):
        errs = check(_html('<p>x</p>', grades=(0, 0, 2)), MARKET, METRICS, EVAL, BOOK)
        assert any('두 칸' in e for e in errs)

    def test_incomplete_collection_fails_closed(self):
        mk = dict(MARKET, complete=False, missing=['credit'])
        errs = check(_html('<p>x</p>'), mk, METRICS, EVAL, BOOK)
        assert any('수집이 불완전' in e for e in errs)

    def test_report_date_mismatch_fails_closed(self):
        ev = dict(EVAL, report_date='2026-08-01')
        errs = check(_html('<p>x</p>'), MARKET, METRICS, ev, BOOK)
        assert any('기준일 불일치' in e for e in errs)

    def test_missing_allowed_grades_fails_closed(self):
        ev = {'report_date': '2026-08-27',
              'assets': {'duration': {}, 'curve': {}, 'credit': {}}}
        errs = check(_html('<p>x</p>'), MARKET, METRICS, ev, BOOK)
        assert any('허용 등급을 알 수 없다' in e for e in errs)

    def test_meta_description_is_checked(self):
        html = ('<meta name="description" content="스프레드는 888.8bp였다">'
                + _html('<p>x</p>'))
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('데이터에 없는 수치' in e for e in errs)

    def test_banned_vocabulary(self):
        errs = check(_html('<p>buy-side 관점</p>'), MARKET, METRICS, EVAL, BOOK)
        assert any('금지 어휘' in e for e in errs)

    def test_internal_token_leak(self):
        errs = check(_html('<p>bond_metrics.json 참조</p>'), MARKET, METRICS, EVAL, BOOK)
        assert any('내부 용어' in e for e in errs)

    def test_missing_standing_marker(self):
        html = _html('<p>x</p>').replace('data-standing="fx"', 'data-x="fx"')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('data-standing="fx"' in e for e in errs)

    def test_foreign_tables_may_not_outweigh_us(self):
        # 노출 8%인 축이 표 지면의 절반을 가져가면 막는다
        def tbl(scope, rows):
            return (f'<table data-scope="{scope}"><thead><tr><th>x</th></tr></thead>'
                    + '<tr><td>1</td></tr>' * rows + '</table>')
        html = _html('<p>x</p>').replace(
            '<section id="b-2">',
            '<section id="b-3">' + tbl('us', 3) + tbl('foreign', 9)
            + '</section><section id="b-2">')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('지면 배분 역전' in e for e in errs)

    def test_unscoped_table_fails_closed(self):
        html = _html('<p>x</p>').replace(
            '<section id="b-2">',
            '<section id="b-3"><table><thead><tr><th>x</th></tr></thead>'
            '<tr><td>1</td></tr></table></section><section id="b-2">')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('data-scope' in e for e in errs)

    def test_missing_exposure_basis_is_caught(self):
        html = _html('<p>x</p>').replace('노출을 역산했다', '그냥 봤다')
        assert any('역산했는지' in e for e in check(html, MARKET, METRICS, EVAL, BOOK))

    def test_weight_inversion_is_caught(self):
        html = _html('<p>' + 'y' * 9000 + '</p>')
        errs = check(html, MARKET, METRICS, EVAL, BOOK)
        assert any('무게중심 역전' in e for e in errs)


def test_a_number_split_by_markup_is_refused():
    """「4.<span>47</span>bp」는 화면에 4.47bp 로 보이는데 검사에는 47bp 로 들어간다."""
    from bond import gate
    errs = gate._split_numbers('<p>스프레드는 4.<span>47</span>bp입니다.</p>')
    assert errs
