"""백분위를 사람이 알아듣는 말로 바꾸는 규칙."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from common import standing as S  # noqa: E402


def test_window_label_names_the_span_it_actually_has():
    assert S.window_label(522) == '2년'
    assert S.window_label(300) == '1년'
    assert S.window_label(120) == '120거래일'


def test_missing_input_gives_nothing():
    assert S.plain(None, 500) is None
    assert S.plain(96.0, 0) is None
    assert S.plain(96.0, None) is None


def test_extreme_high_counts_the_days_instead_of_naming_a_percentile():
    p = S.plain(99.3, 522)
    assert p['side'] == 'high'
    assert p['days'] == 4
    assert p['text'] == '최근 2년(522거래일) 가운데 이보다 높았던 날이 나흘뿐'
    assert '백분위' not in p['text']


def test_ninety_six_reads_as_a_day_count():
    p = S.plain(96.0, 504)
    assert p['days'] == 20
    assert '이보다 높았던 날이 20일뿐' in p['text']


def test_top_of_the_sample_says_so_rather_than_zero_days():
    p = S.plain(100.0, 504)
    assert p['days'] == 0
    assert p['text'] == '최근 2년(504거래일)을 통틀어 가장 높은 자리'


def test_one_day_is_spoken_not_counted():
    p = S.plain(99.9, 504)
    assert p['days'] == 1
    assert '하루뿐' in p['text']


def test_high_but_not_extreme_uses_a_share():
    p = S.plain(80.0, 504)
    assert p['side'] == 'high'
    assert p['share_pct'] == 20
    assert p['days'] is None
    assert p['text'] == '최근 2년(504거래일) 가운데 높은 쪽 20% 안'


def test_middle_says_middle():
    assert S.plain(50.0, 504)['side'] == 'mid'
    assert '한가운데' in S.plain(50.0, 504)['text']
    assert S.plain(41.0, 504)['text'] == '최근 2년(504거래일)의 한가운데쯤'


def test_low_side_mirrors_the_high_side():
    p = S.plain(20.0, 504)
    assert p['side'] == 'low'
    assert p['share_pct'] == 20
    assert p['text'] == '최근 2년(504거래일) 가운데 낮은 쪽 20% 안'
    q = S.plain(0.5, 504)
    assert q['days'] == 3
    assert '이보다 낮았던 날이 사흘뿐' in q['text']


def test_spread_speaks_of_width_not_height():
    p = S.plain(0.5, 504, kind='spread')
    assert '좁았던' in p['text']
    assert S.plain(99.0, 504, kind='spread')['text'].count('넓었던') == 1
    assert '가장 넓은 자리' in S.plain(100.0, 504, kind='spread')['text']


def test_caller_can_name_the_window_itself():
    p = S.plain(96.0, 270, window='1년')
    assert p['text'].startswith('최근 1년(270거래일)')


def test_share_is_rounded_up_never_away_to_zero():
    # 「N% 안」은 상한 주장이다 — 10.4% 를 「10% 안」이라 쓰면 실제보다 좁게 말한다.
    assert S.plain(89.6, 504)['share_pct'] == 11
    # 그리고 상위 0.4% 를 「0% 안」이라 쓰면 아무 말도 아니다.
    assert S.plain(75.4, 504)['share_pct'] == 25


def test_numbers_the_prose_prints_are_carried_as_numbers():
    # 게이트는 metrics 안의 «수»만 허용 토큰으로 삼는다. 문장 안에만 있는 숫자는
    # 창작으로 걸린다(2026-08-31 채권 게이트 규칙).
    p = S.plain(99.3, 522)
    assert isinstance(p['days'], int) and isinstance(p['sessions'], int)
    assert p['percentile'] == 99.3


def test_short_sample_does_not_say_two_years_twice():
    p = S.plain(96.0, 120)
    assert p['text'].startswith('최근 120거래일 가운데')
    assert '(120거래일)' not in p['text']


def test_short_form_drops_the_span_for_table_cells():
    # 기간이 머리글에 이미 적힌 표 칸에서는 「최근 2년(504거래일)」을 매 줄 반복하지 않는다.
    assert S.plain(96.0, 504)['short'] == '이보다 높았던 날이 20일뿐'
    assert S.plain(80.0, 504)['short'] == '높은 쪽 20% 안'
    assert S.plain(50.0, 504)['short'] == '한가운데쯤'
    assert S.plain(0.2, 504, kind='spread')['short'] == '이보다 좁았던 날이 하루뿐'
    assert S.plain(100.0, 504)['short'] == '통틀어 가장 높은 자리'


def test_span_drops_a_year_name_that_undersells_the_sample():
    # 497거래일은 「1년」으로 불린다(아래로 반올림). 그 이름과 거래일 수를 나란히
    # 쓰면 「최근 1년(497거래일)」이라는 자기모순이 된다 — 2026-09-01 MOVE 실측.
    assert S.plain(50.0, 497)['text'] == '최근 497거래일의 한가운데쯤'
    # 이름과 표본이 맞으면 그대로 함께 쓴다.
    assert S.plain(50.0, 523)['text'] == '최근 2년(523거래일)의 한가운데쯤'


def test_say_picks_the_ending_the_fragment_needs():
    # 받침에 따라 서술격 조사가 갈린다 — 「자리예요」와 「뿐이에요」.
    assert S.say(S.plain(100.0, 504), 'soft') == '최근 2년(504거래일)을 통틀어 가장 높은 자리예요'
    assert S.say(S.plain(96.0, 504), 'soft').endswith('20일뿐이에요')
    assert S.say(S.plain(96.0, 504)).endswith('20일뿐입니다')
    assert S.say(S.plain(50.0, 504), 'and').endswith('한가운데쯤이고요')
    assert S.say(S.plain(80.0, 504), 'and').endswith('높은 쪽 20% 안이고요')
    assert S.say(S.plain(100.0, 504), 'and').endswith('가장 높은 자리고요')
    assert S.say(S.plain(96.0, 504), 'clause').endswith('20일뿐이고')
    assert S.say(S.plain(100.0, 504), 'clause').endswith('가장 높은 자리고')
    assert S.say(None) == ''


def test_a_sample_too_short_says_nothing_at_all():
    # 2거래일 표본에 「한가운데쯤」은 문장만 성립하고 뜻이 없다.
    assert S.plain(50.0, 2) is None
    assert S.plain(50.0, 29) is None
    assert S.plain(50.0, 30) is not None


def test_counted_days_beat_a_rounded_percentile():
    # 504개 표본의 최댓값은 백분위 99.9 로 반올림된다 — 되돌리면 「하루뿐」이지만
    # 실제로 위에 있는 날은 0일이다. 세어 준 값이 있으면 그것을 쓴다.
    assert S.plain(99.9, 504)['days'] == 1
    p = S.plain(99.9, 504, above=0, below=503)
    assert p['days'] == 0 and '가장 높은 자리' in p['text']


def test_counted_share_is_used_when_given():
    p = S.plain(80.0, 500, above=104, below=396)
    assert p['share_pct'] == 21  # 20.8% 를 올림
