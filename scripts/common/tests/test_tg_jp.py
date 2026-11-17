"""common/tg_jp.py — which posts of the one channel belong to the Japan daily (2026-11-15).
Synthetic sentences only: post text is never committed.
Design: docs/superpowers/specs/2026-11-15-telegram-japan-daily.md"""
from datetime import datetime, timedelta, timezone

import pytest

from common import tg_jp as J

S, P = '2026-11-13', '2026-11-12'
JST = timezone(timedelta(hours=9))
FILL = ' 반도체 검사 장비 수요가 늘어 내년 실적 전망을 올렸다는 내용이다. 메모리 투자도 이어진다고 봤고 고객사 증설 일정은 그대로라고 덧붙였다.'


def post(i, text, when, links=()):
    """`when` = JST 'MM-DD HH:MM' of 2026."""
    dt = datetime.strptime('2026-' + when, '%Y-%m-%d %H:%M').replace(tzinfo=JST)
    return {'id': i, 'url': f'https://t.me/{J.JP_CHANNEL}/{i}', 'dt_utc': dt.astimezone(timezone.utc).isoformat(),
            'text': text, 'links': list(links), 'forwarded_from': None, 'doc_title': None}


# ── jp_basis ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize('text', [
    'JP모건) 어드반테스트 목표가 상향' + FILL,
    '도요타가 미국 공장 증설을 발표했다' + FILL,
    '토요타 3분기 실적' + FILL,
    '후루카와 전기 광섬유 증설' + FILL,
    '일본은행이 12월 회의에서 금리를 올릴 수 있다는 관측' + FILL,
    'BOJ 우에다 총재 발언' + FILL,
    '닛케이 225 가 사상 최고치를 다시 썼다' + FILL,
    '달러/엔 환율이 157엔을 넘었다' + FILL,
    '6857.T 실적 요약' + FILL,
    '8035 JP 목표가' + FILL,
    '(TDK) 배터리 사업 호조' + FILL,
    '소니로 넘어간 이미지센서 물량' + FILL,
    '소니와의 협력' + FILL,
    '소니께서' + FILL,
    '소니의 게임 사업' + FILL,
    '디스코의 그라인더 출하' + FILL,
    '혼다는 전기차 계획을 늦췄다' + FILL,
])
def test_keyword_posts(text):
    assert J.jp_basis(text) == 'keyword'


@pytest.mark.parametrize('text', [
    '일은 많고 시간은 없다' + FILL,                               # 「일은」 is not 일본은행
    '노무라) 엔비디아 목표가 상향' + FILL,                         # a broker is a note's author
    '미즈호) 마이크론 커버리지 개시' + FILL,
    '닛케이) 대만 TSMC 가 미국 공장을 늘린다' + FILL,               # the newspaper as an outlet
    '니케이 보도에 따르면 삼성전자가' + FILL,
    '디스코드 서버 접속 장애' + FILL,
    '디스코텍 조명 업체' + FILL,
    '소니아 간디 전 총재' + FILL,
    '결혼다운 결혼' + FILL,
    '알박기 논란이 다시 불거졌다' + FILL,
    '로체스터 대학 연구진' + FILL,
    '추가이익이 발생했다' + FILL,
    '멘토와 함께' + FILL,
    'STDKX 펀드' + FILL,
    '엔비디아 실적 발표' + FILL,
    '',
    None,
])
def test_non_japan_posts(text):
    assert J.jp_basis(text) is None


def test_keyword_must_open_the_post_or_repeat():
    late = '엔비디아 실적 요약.' + FILL * 3 + ' 참고로 도요타도 언급됐다.'
    assert J.jp_basis(late) is None
    many = '엔비디아 실적 요약.' + FILL * 3 + ' 엔화 약세, 일본 국채 금리 상승, BOJ 회의가 변수다.'
    assert J.jp_basis(many) == 'keyword'


@pytest.mark.parametrize('text', ['엔화약세가 이어지며 수입 물가 부담이 커진다는 분석이다.', '엔고에도 수출주는 버텼다.',
                                  '엔저현상이 길어진다.', '엔화 약세가 이어진다.'])
def test_yen_words_run_on_into_the_next_word(text):
    """구현 검토 3회 — a lookahead refused 「엔화약세」; on the 2,280 real posts it only ever refused
    「엔고에도」 and 「엔고라면」."""
    assert J.jp_basis(text + FILL) == 'keyword'


def test_the_channels_own_name_is_not_the_country():
    assert J.jp_basis('에테르의 일본&미국 리서치 안내.' + FILL + ' 일본&미국 채널을 옮긴다.') is None


def test_country_basis_needs_the_word_early_and_twice():
    assert J.jp_basis('일본 전력 수요가 늘고 있다.' + FILL + ' 일본 정부도 지원한다.') == 'country'
    assert J.jp_basis('일본 전력 수요가 늘고 있다.' + FILL) is None                       # once
    assert J.jp_basis('전력 수요.' + FILL * 3 + ' 일본에서도 같다. 일본 정부도 지원한다.') is None   # late


# ── who the note is from ─────────────────────────────────────────────────

@pytest.mark.parametrize('head,firm', [
    ('JP모건) 어드반테스트', 'JP모건'), ('JPM) 어드반테스트', 'JP모건'), ('모간스탠리) 키옥시아', '모건스탠리'),
    ('모건 스탠리) 키옥시아', '모건스탠리'), ('골드만삭스) 도쿄일렉트론', '골드만삭스'), ('Citi) 소니', '씨티'),
    ('노무라) 디스코', '노무라'), ('UBS) 도요타', 'UBS'), ('J.P. 모건) 소니', 'JP모건'), ('미즈호 증권) 소니', '미즈호'),
    ('📱 Citi) 소니', '씨티'), ('TD Cowen) 소니', 'TD코웬'), ('Evercore ISI) 소니', '에버코어'),
])
def test_broker_prefix_is_relay_firm(head, firm):
    assert J.title_prefix(head + FILL) == (firm, None)


def test_outlet_prefix_is_a_credit():
    assert J.title_prefix('닛케이) 키옥시아 증설' + FILL) == (None, '니혼게이자이')
    assert J.title_prefix('블룸버그) 일본은행 인사' + FILL) == (None, '블룸버그')
    assert J.title_prefix('닛케이 아시아) 라피더스 증자' + FILL) == (None, '닛케이아시아')
    assert J.title_prefix('교도통신) 일본은행 인사' + FILL) == (None, '교도통신')


@pytest.mark.parametrize('text', [
    '어드반테스트 목표가 상향' + FILL,
    '참고) 어드반테스트' + FILL,                       # not a known name
    '어드반테스트가 JP모건) 이라는' + FILL,             # not at the start of the title line
])
def test_no_prefix(text):
    assert J.title_prefix(text) == (None, None)


def test_prefix_is_read_past_the_date_line():
    assert J.title_prefix('🗓 2026.08.05 원문\nJP모건) 어드반테스트' + FILL) == ('JP모건', None)


# ── note_date ────────────────────────────────────────────────────────────

def test_note_date_markers():
    assert J.note_date('🗓 2026.08.05 원문\n도요타' + FILL) == '2026-08-05'
    assert J.note_date('↪️ 다른 방에서 전달 · 2026.8.21\n도요타' + FILL) == '2026-08-21'
    assert J.note_date('도요타' + FILL) is None
    assert J.note_date('도요타' + FILL * 3 + '\n🗓 2026.08.05 원문') is None       # not at the head
    assert J.note_date('🗓 2026.13.45 원문') is None                              # not a date


# ── window ───────────────────────────────────────────────────────────────

def test_window_is_the_two_cuts():
    floor, ceiling = J.window(S, P)
    assert ceiling == datetime(2026, 11, 13, 16, 30, tzinfo=JST)
    assert floor == datetime(2026, 11, 12, 16, 30, tzinfo=JST)


def test_window_rejects_a_prev_that_is_not_earlier():
    with pytest.raises(ValueError):
        J.window(S, S)


def _ids(cands):
    return [it['id'].split('/')[1] for it, _ in cands]


def test_posts_at_the_cuts_belong_to_the_earlier_session():
    floor, ceiling = J.window(S, P)
    posts = [post(1, '도요타 실적' + FILL, '11-12 16:30'), post(2, '도요타 증설' + FILL, '11-12 16:31'),
             post(3, '소니 실적' + FILL, '11-13 16:30'), post(4, '혼다 실적' + FILL, '11-13 16:31')]
    cands, stats = J.candidates(posts, S, floor, ceiling)
    assert _ids(cands) == ['2', '3'] and stats['outside'] == 2
    # the next session takes 4 and never 3
    f2, c2 = J.window('2026-11-16', S)
    assert _ids(J.candidates(posts, '2026-11-16', f2, c2)[0]) == ['4']


def test_filters_and_counts():
    floor, ceiling = J.window(S, P)
    posts = [post(1, '도요타 ㅎㅎ', '11-13 09:00'),                                       # chatter
             post(6, '소프트뱅크가 터빈 주문 계약을 이행하지 않고 있다는 주장이 나왔다. 못 돌릴 듯.', '11-13 09:05'),   # a remark
             post(7, '에테르의 일본&미국 리서치 pinned «도요타 실적' + FILL + '»', '11-13 09:06'),                    # service line
             post(2, '엔비디아 실적' + FILL, '11-13 09:01'),                              # not Japan
             post(3, '🗓 2026.08.05 원문\n도요타 실적' + FILL, '11-13 09:02'),            # stale
             post(4, '🗓 2026.11.12 원문\n소니 실적' + FILL, '11-13 09:03'),              # dated yesterday: kept
             post(5, '키옥시아 증설' + FILL, '11-13 09:04')]
    cands, stats = J.candidates(posts, S, floor, ceiling)
    assert _ids(cands) == ['4', '5']
    assert (stats['chatter'], stats['not_japan'], stats['stale'], stats['burst']) == (3, 1, 1, 0)
    it = cands[0][0]
    assert it['note_date'] == '2026-11-12' and it['channel'] == J.JP_CHANNEL and it['kind'] == 'opinion'
    assert it['market_basis'] == 'keyword' and it['id'] == f'{J.JP_CHANNEL}/4'


def test_duplicate_original_keeps_the_earliest():
    floor, ceiling = J.window(S, P)
    u = 'https://www.reuters.com/markets/asia/toyota-2026-11-13/'
    posts = [post(1, '도요타 증설' + FILL, '11-13 09:00', [u]), post(2, '도요타 증설 재전송' + FILL, '11-13 10:00', [u + '?utm_source=x'])]
    cands, stats = J.candidates(posts, S, floor, ceiling)
    assert _ids(cands) == ['1'] and stats['dup'] == 1
    assert cands[0][0]['kind'] == 'report' and cands[0][0]['source']['name'] == '로이터'


def test_paywalled_link_is_an_opinion_with_the_outlet():
    floor, ceiling = J.window(S, P)
    posts = [post(1, '일본은행 인사' + FILL, '11-13 09:00', ['https://www.bloomberg.com/news/articles/2026-11-13/boj'])]
    it = J.candidates(posts, S, floor, ceiling)[0][0][0]
    assert it['kind'] == 'opinion' and it['source'] == {'name': '블룸버그', 'url': None, 'basis': 'paywalled_link'}


def test_prefix_fields_reach_the_item():
    floor, ceiling = J.window(S, P)
    posts = [post(1, 'JP모건) 어드반테스트 목표가 상향' + FILL, '11-13 09:00'),
             post(2, '닛케이) 키옥시아 증설' + FILL, '11-13 09:01')]
    a, b = (it for it, _ in J.candidates(posts, S, floor, ceiling)[0])
    assert a['relay_firm'] == 'JP모건' and a['source'] is None
    assert b['relay_firm'] is None and b['source'] == {'name': '니혼게이자이', 'url': None, 'basis': 'credit'}


# ── bulk re-upload ───────────────────────────────────────────────────────

def _burst(start_id, when, n=20, gap_s=5):
    base = datetime.strptime('2026-' + when, '%Y-%m-%d %H:%M').replace(tzinfo=JST)
    out = []
    for k in range(n):
        p = post(start_id + k, '🗓 2026.08.05 원문\n엔비디아 메모' + FILL, when)
        p['dt_utc'] = (base + timedelta(seconds=k * gap_s)).astimezone(timezone.utc).isoformat()
        out.append(p)
    return out


def test_burst_takes_unmarked_posts_inside_and_right_after():
    floor, ceiling = J.window(S, P)
    burst = _burst(100, '11-13 03:00')                       # 03:00:00 … 03:01:35
    inside = post(50, '도요타 실적 이어서' + FILL, '11-13 03:01')
    trailing = post(51, '소니 실적 이어서' + FILL, '11-13 03:03')     # 85 s after the last marked post
    later = post(52, '혼다 실적' + FILL, '11-13 03:05')               # 205 s after
    before = post(53, '키옥시아 증설' + FILL, '11-13 02:59')
    cands, stats = J.candidates(burst + [inside, trailing, later, before], S, floor, ceiling)
    assert sorted(_ids(cands)) == ['52', '53'] and stats['burst'] == 2 and stats['stale'] == 20


def test_fewer_stale_marks_are_not_a_burst():
    floor, ceiling = J.window(S, P)
    few = _burst(100, '11-13 03:00', n=19)
    inside = post(50, '도요타 실적' + FILL, '11-13 03:01')
    cands, stats = J.candidates(few + [inside], S, floor, ceiling)
    assert _ids(cands) == ['50'] and stats['burst'] == 0


def test_burst_straddling_the_floor_still_guards_the_window():
    floor, ceiling = J.window(S, P)
    burst = _burst(100, '11-12 16:29', n=19, gap_s=3)        # 19 marked just before the floor
    last = post(200, '🗓 2026.08.05 원문\n엔비디아 메모' + FILL, '11-12 16:31')   # one marked just after
    cont = post(201, '도요타 실적 이어서' + FILL, '11-12 16:32')                  # its unmarked continuation
    cands, stats = J.candidates(burst + [last, cont], S, floor, ceiling)
    assert cands == [] and stats['burst'] == 1


# ── valve ────────────────────────────────────────────────────────────────

def test_valve_keeps_keyword_posts_first_and_reports_the_rest():
    floor, ceiling = J.window(S, P)
    posts = [post(i, '일본 전력 수요가 늘고 있다.' + FILL + f' 일본 정부도 지원한다 {i}.', '11-13 09:00') for i in range(1, 6)]
    posts += [post(100 + i, f'도요타 실적 {i}' + FILL, '11-13 10:00') for i in range(J.JP_VALVE)]
    cands, _ = J.candidates(posts, S, floor, ceiling)
    kept, dropped = J.valve(cands)
    assert len(kept) == J.JP_VALVE and dropped == 5
    assert all(it['market_basis'] == 'keyword' for it, _ in kept)
    assert [it['dt_utc'] for it, _ in kept] == sorted(it['dt_utc'] for it, _ in kept)


def test_valve_leaves_a_normal_day_alone():
    floor, ceiling = J.window(S, P)
    cands, _ = J.candidates([post(1, '도요타 실적' + FILL, '11-13 09:00')], S, floor, ceiling)
    assert J.valve(cands) == (cands, 0)


def test_a_short_post_with_a_link_is_still_a_note():
    floor, ceiling = J.window(S, P)
    posts = [post(1, '도요타 미국 공장 증설 발표, 원문 참고', '11-13 09:00', ['https://www.reuters.com/markets/asia/toyota-plant/'])]
    assert _ids(J.candidates(posts, S, floor, ceiling)[0]) == ['1']


def test_firms_in_finds_variants_and_whole_latin_words():
    assert J.firms_in('모간 스탠리가 목표가를 올렸고 Citi 도 같았다') == {'모건스탠리', '씨티'}
    assert J.firms_in('clubs 와 hubs 는 은행이 아니다') == set()
    assert J.firms_in('JP모건이 봤다는 내용') == {'JP모건'}


def test_stale_is_measured_from_the_day_the_post_was_made():
    """Monday's window: a note dated Friday and forwarded on Saturday is not a re-upload."""
    mon, fri = '2026-11-16', '2026-11-13'
    floor, ceiling = J.window(mon, fri)
    posts = [post(1, '↪️ 다른 방에서 전달 · 2026.11.13\n도요타 실적' + FILL, '11-14 10:00'),
             post(2, '🗓 2026.11.10 원문\n소니 실적' + FILL, '11-14 10:01')]            # four days old when posted
    cands, stats = J.candidates(posts, mon, floor, ceiling)
    assert _ids(cands) == ['1'] and stats['stale'] == 1 and cands[0][0]['note_date'] == '2026-11-13'


def test_fresh_dated_forwards_do_not_make_a_burst():
    floor, ceiling = J.window('2026-11-16', '2026-11-13')
    fwd = [post(100 + k, '↪️ 다른 방에서 전달 · 2026.11.13\n엔비디아 메모' + FILL, '11-14 10:00') for k in range(25)]
    inside = post(50, '도요타 실적' + FILL, '11-14 10:00')
    cands, stats = J.candidates(fwd + [inside], '2026-11-16', floor, ceiling)
    assert _ids(cands) == ['50'] and stats['burst'] == 0
