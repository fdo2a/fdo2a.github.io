"""Candidate selection across channels (2026-11-12): individual-channel posts without a market
keyword, the corporate names added to KR_RE, and round-robin seats per channel.
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from common import telegram as tg
from common.tg_market import market_of

NOW = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
LONG = '가스터빈 제조 과정의 병목을 구체적으로 짚었다. 부품 조달과 숙련 인력이 모자라 증설이 수주를 따라가지 못한다는 설명이다. ' * 3


def post(i, text, links=(), at=None, fwd=None):
    return {'id': i, 'url': f'https://t.me/c/{i}', 'dt_utc': (at or NOW).isoformat(), 'text': text,
            'links': list(links), 'forwarded_from': fwd}


# ── market of a post ─────────────────────────────────────────────────────

def test_individual_post_without_market_keyword_goes_to_both_markets():
    assert market_of(LONG, 'both') == 'unknown' and len(LONG) >= tg.SUBSTANTIVE
    for market in ('us', 'kr'):
        it = tg.classify_post('d_ticker', post(1, LONG), market)
        assert it and it['kind'] == 'opinion' and it['market_basis'] == 'default'


def test_short_unknown_individual_post_is_still_dropped_unless_it_links_an_original():
    short = '지멘스에너지 실적에서 재밌는 얘기가 나왔는데 가스터빈 병목을 구체적으로 짚었다는 점이다'
    assert 40 <= len(short) < tg.SUBSTANTIVE and market_of(short, 'both') == 'unknown'
    assert tg.classify_post('d_ticker', post(2, short), 'us') is None
    linked = tg.classify_post('aethersemiconductor', post(3, short, ['https://www.reuters.com/technology/x']), 'us')
    assert linked and linked['kind'] == 'report' and linked['market_basis'] == 'default'


def test_unknown_post_from_a_firm_channel_is_dropped_as_before():
    assert tg.CHANNELS['lim_econ']['market'] == 'both'
    assert tg.classify_post('lim_econ', post(4, LONG), 'us') is None
    assert tg.classify_post('lim_econ', post(4, LONG), 'kr') is None


def test_market_basis_names_how_the_market_was_decided():
    kw = tg.classify_post('d_ticker', post(5, '엔비디아 실적 발표 뒤 나스닥 선물이 흔들렸다는 분석이 이어졌다는 얘기를 정리했다'), 'us')
    assert kw['market_basis'] == 'keyword'
    ch = tg.classify_post('FastStockNewsUSA', post(6, '버크셔 해서웨이가 한 달 동안 지수를 크게 웃돌았다는 소식이 전해졌다는 글이다'), 'us')
    assert ch['market_basis'] == 'channel'
    # a keyworded post still goes only to its own market
    assert tg.classify_post('d_ticker', post(5, '엔비디아 실적 발표 뒤 나스닥 선물이 흔들렸다는 분석이 이어졌다는 얘기를 정리했다'), 'kr') is None


@pytest.mark.parametrize('text', [
    '두산, SK실트론 인수 6개국 기업결합심사 완료 - 한·미·중 등 6개국 심사 마무리',
    '두산이 반도체 소재 회사를 인수한다는 소식',
    '삼성바이오로직스 4공장 가동률이 올랐다는 글',
    'LG이노텍과 삼성전기의 기판 증설 경쟁',
    'HD현대 조선 부문 수주가 늘었다',
    '한화에어로스페이스 수출 계약 소식',
    '한미반도체 본더 수주 공시',
])
def test_kr_names_route_a_post_to_kr(text):
    assert market_of(text, 'both') == 'kr'


@pytest.mark.parametrize('text', [
    '현대화에 필요한 미국 외 지역 반도체 설비 투자가 늘고 있다',
    '삼성바이오산업 관련 해외 투자 동향',
    '한화로 약 3조 원 규모의 유럽 전력기기 수주',
    '두산물 수입이 줄었다는 통계',
    '둘레길 옆두산책로',
    'SK온라인 게임 매출',
    'LG트윈스 우승 기념 할인',
    '포스코인터 이야기는 아니다',
])
def test_kr_name_prefixes_inside_other_words_do_not_match(text):
    assert market_of(text, 'both') == 'unknown'


def test_us_posts_keep_their_market_after_the_kr_additions():
    for text in ('엔비디아 실적과 나스닥 선물', '연준 금리 동결 전망', 'Nvidia and AMD rally', '$NVDA 급등'):
        assert market_of(text, 'both') == 'us'
    assert market_of('삼성전자와 엔비디아의 HBM 공급 협상', 'both') == 'both'


# ── seats per channel ────────────────────────────────────────────────────

def _cand(ch, i, text, minutes=0):
    p = post(i, text, at=NOW + timedelta(minutes=minutes))
    it = tg.classify_post(ch, p, 'us')
    assert it, (ch, text)
    return it, p


def test_every_channel_gets_a_seat_before_any_channel_gets_a_second():
    """11/12 실측: insidertracking 후보 109·FastStockNewsUSA 38 이 점수로 자리를 다 가져가
    d_ticker 후보 2건이 0건이 됐다."""
    hot = '나스닥 급락, 엔비디아 하락, 금리 상승, 반도체 실적 가이던스 하향이 겹쳤다는 속보가 이어졌다'
    cands = [_cand('insidertracking', i, f'{hot} {i}', i) for i in range(30)]
    cands += [_cand('FastStockNewsUSA', 100 + i, f'{hot} {i}', i) for i in range(30)]
    cands += [_cand('d_ticker', 200, LONG)]                         # no market word: lowest score
    cands += [_cand('aethersemiconductor', 300, LONG + ' 다른 글')]
    got = tg.select(cands)
    per = Counter(i['channel'] for i, _ in got)
    assert per['d_ticker'] == 1 and per['aethersemiconductor'] == 1
    assert per['insidertracking'] == tg.MAX_PER_CHANNEL and per['FastStockNewsUSA'] == tg.MAX_PER_CHANNEL
    assert len(got) == 2 * tg.MAX_PER_CHANNEL + 2 <= tg.MAX_OPINIONS


def test_round_robin_stops_at_the_cap_and_fills_round_by_round():
    hot = '나스닥 급락, 엔비디아 하락, 금리 상승, 반도체 실적이 겹쳤다는 얘기가 이어졌다는 글'
    chans = ['insidertracking', 'FastStockNewsUSA', 'd_ticker', 'aethersemiconductor', 'kwusa']
    cands = [_cand(ch, 1000 * k + i, f'{hot} {i}', i) for k, ch in enumerate(chans) for i in range(8)]
    got = tg.select(cands)
    per = Counter(i['channel'] for i, _ in got)
    # 2026-11-12 사용자 지시 「뉴스 개수를 한정하지 말고 … 분량은 좀 길어져도 괜찮아」 — 후보 자리를 넓혔다
    assert (tg.MAX_VIEWS, tg.MAX_OPINIONS, tg.MAX_PER_CHANNEL) == (10, 24, 5)
    assert len(got) == tg.MAX_OPINIONS
    assert sorted(per.values()) == [4, 5, 5, 5, 5]                  # four full rounds of 5, then 4


def test_a_channel_seats_its_best_keyword_post_then_its_best_default_post():
    """11/12 실측: keyword 글을 무조건 앞에 두면 상한(12) 때문에 두 바퀴쯤만 돌아 default 글은 한 건도
    자리를 못 얻었다. 점수만으로 세워도 진다 — 점수가 시장 낱말 수라 default 글은 원래 낮다."""
    kw = [_cand('d_ticker', i, f'엔비디아 실적 뒤 나스닥 선물이 흔들렸다는 분석 {i} — 금리와 반도체 수요를 함께 봐야 한다는 글', i)
          for i in range(8)]
    df = [_cand('d_ticker', 50 + i, LONG + f' 글 {i}', 60 + i) for i in range(3)]
    assert all(c[0]['market_basis'] == 'default' for c in df)
    assert max(tg._score(c[0], c[1], False) for c in df) < min(tg._score(c[0], c[1], False) for c in kw)
    seats = [i['market_basis'] for i, _ in tg.select(kw + df)]
    assert Counter(seats) == {'keyword': tg.MAX_PER_CHANNEL - 1, 'default': 1}
    # the default post takes the SECOND seat: when the cap ends the rounds early it is still in
    hot = '나스닥 급락, 엔비디아 하락, 금리 상승, 반도체 실적이 겹쳤다는 얘기가 이어졌다는 글'
    others = [_cand(ch, 1000 * k + i, f'{hot} {i}', i)
              for k, ch in enumerate(['insidertracking', 'FastStockNewsUSA', 'aethersemiconductor', 'kwusa', 'lim_econ'], 1)
              for i in range(8)]
    got = [i for i, _ in tg.select(kw + df + others) if i['channel'] == 'd_ticker']
    assert len(got) == 4 and Counter(i['market_basis'] for i in got) == {'keyword': 3, 'default': 1}
    # a channel with only default posts, or only keyword posts, is ranked by score as before
    assert len(tg.select(df)) == 3 and len(tg.select(kw)) == tg.MAX_PER_CHANNEL


def test_views_are_not_part_of_the_round_robin():
    views = [(tg.classify_post('hedgecat0301', post(i, f'[11/12, 장 시작 전 생각, 키움 한지영] 코스피와 나스닥 메모 {i}',
                                                    at=NOW + timedelta(minutes=i)), 'us'), {'text': 'x'}) for i in range(14)]
    assert all(v[0]['kind'] == 'view' for v in views)
    got = tg.select(views)
    assert len(got) == tg.MAX_VIEWS
