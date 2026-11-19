"""일본 일간 v2 — codex 구현 검토 1회차 지적 5·6·7·8·9 재현 (2026-11-19)."""
import copy
import json
import os
from datetime import datetime, timezone

import pytest

from japan import daily_calendar as C
from japan import daily_render as R
from japan.tests import jpx_fixture as F
from japan.tests.test_daily_v2_gate import NEWS, _blocked, body, gate, page
from japan.tests.test_daily_v2_render import v2
from us import readability as RD
from us.news_expand import expand

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
S = '2026-11-18'


# ── 5. 빈 요소가 아닌 태그의 `/>` — 브라우저는 닫지 않는다 ─────────────────────────

@pytest.mark.parametrize('ph', ['<!--G:topix-->', '<!--T:indices-->', '<!--G:curve-->'])
def test_self_closing_details_before_placeholder_rejected_at_assembly(ph):
    b = body().replace(ph, '<details/>' + ph, 1)
    errs = R.validate_body(b, R.SECTIONS, schema=2)
    assert any(ph in e and '바로 아래 자식' in e for e in errs), errs


def test_self_closing_details_blocked_at_gate_on_assembled_page():
    """조립 검사를 건너뛴 판(조립본을 손으로 고침)도 게이트가 같은 규칙으로 막는다."""
    h = page()
    g = '<p data-gen="topix">'
    h2 = h.replace(g, '<details/>' + g, 1)
    _blocked(h2, needle='data-gen="topix"')
    t = R.render_tables(v2())['indices']
    _blocked(h.replace(t, '<details/>' + t, 1), needle='코드 표 indices')


def test_void_self_closing_still_fine():
    b = body().replace('<!--G:topix-->', '<br/><!--G:topix-->', 1)
    assert R.validate_body(b, R.SECTIONS, schema=2) == []


# 2회차 #3: main 의 숨김 판정 공용 모듈(common/hidden.py)과 어긋나지 않는다 — 빈 요소 목록은 하나이고,
# 숨긴 요소로 생성 문장·코드 표를 감싸면(자기닫힘 꼴 포함) 조립과 게이트가 둘 다 막는다.

def test_void_list_is_the_shared_one():
    from common import hidden as H
    assert R.VOID == H.VOID


@pytest.mark.parametrize('wrap', ['<div hidden/>', '<div hidden>', '<div style="display:none">', '<span inert/>'])
def test_hidden_wrapper_before_generated_elements_blocked_by_body_and_gate(wrap):
    import re
    assert R.validate_body(body({'equity': wrap + '<p>반등이 넓지 않았다.</p>'}), R.SECTIONS, schema=2)
    h = page()
    gen = re.search(r'<p data-gen="[^"]*"[^>]*>.*?</p>', h, re.S).group(0)
    assert any('바로 아래' in m for m in gate(h.replace(gen, wrap + gen, 1)))


# ── 6. 잘못된 일정 날짜·없는 cov 가 부재 캡션을 만든다 ───────────────────────────

def _repo_cal():
    with open(os.path.join(ROOT, C.PATH), encoding='utf-8') as fh:
        return json.load(fh)


def test_iso_week_date_row_does_not_yield_absence():
    cal = _repo_cal()
    row = next(e for e in cal['events'] if e.get('cov') == 'machinery_orders' and e['date'] == '2026-11-19')
    row['date'] = '2026-W47-4'                 # fromisoformat 은 이것을 11월 19일로 읽는다
    got = C.coverage(cal, '2026-11-19')
    assert got['today_missing'] and got['upcoming_missing']
    assert C.today_events(cal, '2026-11-19') == []


def test_unknown_cov_row_blocks_absence_in_its_range():
    cal = _repo_cal()
    row = next(e for e in cal['events'] if e.get('cov') == 'machinery_orders' and e['date'] == '2026-11-19')
    row['cov'] = 'no_such_series'
    got = C.coverage(cal, '2026-11-19')
    assert C.UNLINKED in got['today_missing'] and C.UNLINKED in got['upcoming_missing']


def test_unknown_cov_outside_range_does_not_block():
    cal = _repo_cal()
    cal['events'].append({'date': '2027-01-28', 'kind': 'release', 'name_ko': 'x', 'cov': 'no_such'})
    assert C.coverage(cal, '2026-11-19')['today_missing'] == []
    assert C.UNLINKED in C.coverage(cal, '2027-01-28')['today_missing']


def test_row_without_cov_blocks_absence():
    cal = _repo_cal()
    cal['events'].append({'date': '2026-11-19', 'kind': 'release', 'name_ko': 'x'})
    assert C.UNLINKED in C.coverage(cal, '2026-11-19')['today_missing']


def test_unlinked_row_named_in_daily_alert():
    from review import digest as D
    from datetime import date
    cal = _repo_cal()
    cal['events'].append({'date': '2026-11-25', 'kind': 'release', 'name_ko': 'x', 'cov': 'no_such'})
    notes = D.jp_calendar_notes({'일간': cal}, date(2026, 11, 19))
    assert any(C.UNLINKED in n for n in notes) and D.safe_notes(notes) == notes


def test_strict_date_used_for_today_and_upcoming():
    cal = {'events': [{'date': '2026-W47-4', 'kind': 'release'}, {'date': '2026-11-19 ', 'kind': 'release'}]}
    assert C.today_events(cal, '2026-11-19') == [] and C.upcoming(cal, '2026-11-18') == []
    assert len(C.malformed(cal)) == 2


# ── 7. 뉴스 제목·연결 문장의 한 자리 수치 ───────────────────────────────────────

def test_news_title_single_digit_with_unit_blocked():
    v = _blocked(page({'news': '<!--NEWS:g2|TOPIX 7포인트 상승-->'}))
    assert any('7' in m and '뉴스 블록' in m for m in v), v


@pytest.mark.parametrize('link', ['3% 올랐다.', '5bp 내렸다.', '2엔 올랐다.'])
def test_news_link_single_digit_with_unit_blocked(link):
    _blocked(page({'news': f'<!--NEWS:g1|반도체주 매수에 닛케이 반등|{link}-->'}), needle='뉴스 블록')


def test_news_title_number_in_article_passes():
    """기사 필드에 있는 수치(「10月」 의 10 은 날짜라 가린다 — 요약의 「10월」)는 그대로."""
    assert gate(page({'news': '<!--NEWS:g3|10월 방일객 역대 최대-->'})) == []


# 2회차: 단위 없는 12 이하 정수도 그 기사(제목·요약)에 있어야 한다 — 「TOPIX 7 상승」 이 통과했다.

@pytest.mark.parametrize('news', [
    '<!--NEWS:g2|TOPIX 7 상승-->',                               # 제목, 단위 없음
    '<!--NEWS:g2|TOPIX ７ 상승-->',                              # 전각
    '<!--NEWS:g2|TOPIX 7.0 상승-->', '<!--NEWS:g2|TOPIX -7 하락-->',
    '<!--NEWS:g1|반도체주 매수에 닛케이 반등|지수는 7 올랐다.-->',    # 연결 문장
    '<!--NEWS:g1|반도체주 매수에 닛케이 3거래일 연속 반등-->',        # 기사에 없는 날수
    '<!--NEWS:g2|10월 최고치 경신-->',                            # 10 은 g3 기사에만 있다 — 다른 기사의 수는 안 된다
])
def test_news_block_small_number_not_in_its_article_blocked(news):
    _blocked(page({'news': news}), needle='뉴스 블록')


def test_news_block_hand_written_block_small_number_blocked():
    import re
    hand = '<div class="news-item" data-news="g2"><p>TOPIX 7 상승</p></div>'
    h = re.sub(r'(<section\b[^>]*data-section="news"[^>]*>.*?)(</section>)',
               lambda m: m.group(1) + hand + m.group(2), page(), count=1, flags=re.S)
    assert hand in h
    assert any('뉴스 블록' in m and ' 7 ' in m for m in gate(h)), gate(h)


@pytest.mark.parametrize('field,value,news', [
    ('summary_ko', '통신 3사가 요금을 함께 올렸다. ', '<!--NEWS:g2|통신 3사 요금 인상-->'),
    ('summary_ko', '7월 이후 처음으로 최고치를 썼다. ', '<!--NEWS:g2|7월 이후 첫 최고치-->'),
    ('title', 'TOPIX ３日続伸、最高値', '<!--NEWS:g2|TOPIX 3일 연속 올라 최고치-->'),
    ('title', '日銀9月会合の議事要旨', '<!--NEWS:g2|일본은행 9월 회의 의사요지-->'),       # 「9月」 은 날짜로 가려지던 달
])
def test_news_block_small_number_in_its_article_passes(monkeypatch, field, value, news):
    it = NEWS['items'][1]
    monkeypatch.setitem(it, field, value + it[field] if field == 'summary_ko' else value)
    assert gate(page({'news': news})) == []


def test_month_in_title_does_not_license_the_same_number_elsewhere(monkeypatch):
    """제목의 「9月」 은 본문의 「9월」 만 허락한다 — 「9% 상승」 의 9 는 아니다."""
    monkeypatch.setitem(NEWS['items'][1], 'title', '日銀9月会合の議事要旨')
    _blocked(page({'news': '<!--NEWS:g2|일본은행 회의 뒤 9% 상승-->'}), needle='뉴스 블록')
    _blocked(page({'news': '<!--NEWS:g2|일본은행 회의 뒤 9 상승-->'}), needle='뉴스 블록')
    _blocked(page({'news': '<!--NEWS:g2|일본은행 회의 9일 만에 상승-->'}), needle='뉴스 블록')    # 9月 ≠ 9일


def test_day_in_title_licenses_only_the_day_token(monkeypatch):
    monkeypatch.setitem(NEWS['items'][1], 'title', 'TOPIX ３日続伸、最高値')
    for bad in ('TOPIX 3 일본 기업 주도 상승', 'TOPIX 3일본 상승', 'TOPIX 3% 상승', 'TOPIX 13일 연속 상승'):
        _blocked(page({'news': f'<!--NEWS:g2|{bad}-->'}), needle='뉴스 블록')


# ── 8. JPX·네이버 전체 60초 상한을 마지막 호출이 넘는다 ─────────────────────────

def test_last_call_overrunning_deadline_invalidates(tmp_path):
    from japan.tests.test_collect_daily_v2 import Fake2, _run

    class Late(Fake2):
        def naver_topix_basic(self, **kw):
            self.t = 70.0                      # 응답이 돌아올 때 70초
            return super().naver_topix_basic()
    snap = _run(tmp_path, Late())
    assert snap['facts']['blocks']['topix'] == 'invalid'


def test_request_timeout_shrinks_to_remaining_budget(tmp_path):
    from japan.tests.test_collect_daily_v2 import Fake2, _run
    seen = []

    class Rec(Fake2):
        def jpx(self, url, timeout=None):
            seen.append(timeout)
            self.t += 5.0
            return super().jpx(url)
    _run(tmp_path, Rec())
    assert seen and seen[0] == 10 and min(seen) < 10 and all(t > 0 for t in seen)


# ── 9. 달력 연도 ≠ 채권 만기 ────────────────────────────────────────────────

@pytest.mark.parametrize('text,blocked', [
    ('2026년 주가가 가파르게 올랐다.', False), ('3년 만에 가장 가파르게 올랐다.', False),
    ('2026년 미일 금리차가 확대됐다.', False),
    ('10-30년 구간은 가팔라졌다.', True), ('30년 금리가 가파르게 올랐다.', True), ('10년과 30년 금리차가 커졌다.', True),
])
def test_calendar_year_vs_maturity(text, blocked):
    v = gate(page({'today': f'<p>{text}</p>'}))
    assert bool([m for m in v if '곡선' in m]) is blocked, v


# 3회차: 제목의 「3日」 이 발표 **날짜**면 글의 「3일 연속」(기간)을 허락하지 않는다 — 날짜는 날짜만, 기간은 기간만.

@pytest.mark.parametrize('title,news,ok', [
    ('日銀3日発表', '엔화 3일 연속 상승', False), ('日銀3日発表', '엔화 3일간 상승', False),
    ('日銀3日発表', '엔화 3일째 상승', False), ('日銀3日発表', '엔화 3일 만에 반등', False),
    ('日銀3日発表', '일본은행 3일 발표', True), ('日銀、3日に発表', '일본은행, 3일에 발표', True),
    ('TOPIX ３日続伸、最高値', 'TOPIX 3일 연속 올라 최고치', True), ('TOPIX 3日連続で上昇', 'TOPIX 3일째 상승', True),
    ('TOPIX 3日ぶり反発', 'TOPIX 3일 만에 반등', True),
    ('TOPIX ３日続伸、最高値', 'TOPIX 3거래일 연속 올라 최고치', True), ('日銀3日発表', '엔화 3거래일 연속 상승', False),
    ('日銀3日発表', '엔화 3일 내리 상승', False), ('日銀3日発表', '엔화 3일 잇달아 상승', False),
    ('TOPIX ３日続伸、最高値', 'TOPIX 3일 최고치', False),             # 기간을 날짜로 옮겨도 안 된다
    ('日銀9月会合の議事要旨', '일본은행 9월 회의 의사요지', True),
    ('日銀9月会合', 'TOPIX 9개월 만에 고점', False), ('日銀9月会合', 'TOPIX 9월 연속 고점', False),
])
def test_date_and_duration_do_not_license_each_other(monkeypatch, title, news, ok):
    monkeypatch.setitem(NEWS['items'][1], 'title', title)
    v = [m for m in gate(page({'news': f'<!--NEWS:g2|{news}-->'})) if '수집 필드에 없는 수치' in m]
    assert (v == []) is ok, v
