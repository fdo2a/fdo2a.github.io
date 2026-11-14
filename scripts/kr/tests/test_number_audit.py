"""KR 일간 표 숫자 대조(`kr.number_audit`, CLI `scripts/check_numbers.py --market kr`) — 2026-11-13.

고정 자료: 2026-11-12·2026-10-20 발행본과 그 발행 커밋의 `kr/data/*`(`fixtures/number_audit/<D>`).
두 날 모두 적용일(`EFFECTIVE`) 전이라 시험은 적용일을 `OPEN` 으로 연다 — 열지 않으면 전부 skipped 로 통과한다.
git·네트워크를 쓰지 않는다(KR 수집 워크플로가 이 디렉터리를 먼저 돌린다).
"""
import copy
import json
import os
import re
import shutil
import subprocess
import sys
from decimal import Decimal

import pytest

from kr import number_audit as K
from us import number_audit as N

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'number_audit')
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
OPEN = '2026-01-01'
D12, D20 = '2026-11-12', '2026-10-20'


def html_of(day=D12):
    with open(os.path.join(FIX, day, 'post.html'), encoding='utf-8') as fh:
        return fh.read()


def data_of(day=D12):
    return K.load_inputs(os.path.join(FIX, day))


@pytest.fixture(scope='module')
def post():
    return html_of(D12)


@pytest.fixture()
def data():
    return data_of(D12)


def run(h, d, day=D12):
    r = K.audit(h, d, day, effective=OPEN)
    assert r.skipped is False
    return r


def sub(h, old, new, count=1):
    assert old in h, old
    return h.replace(old, new, count)


def has(r, *parts):
    return any(all(p in v for p in parts) for v in r.violations)


def warned(r, *parts):
    return any(all(p in w for p in parts) for w in r.warnings)


# ── 정상 글 ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize('day', [D12, D20])
def test_published_posts_pass(day):
    r = run(html_of(day), data_of(day), day)
    assert r.violations == [], r.violations
    assert r.warnings == [], r.warnings
    assert r.table_cells > 40 and r.prose_judged == 0


def test_counts_partition(post, data):
    r = run(post, data)
    # 11/12: 지수 2행×6 + 수급 6 + 거래대금(순위 10·금액 10·N종 1) + 금리 5행×3 = 54
    assert r.table_cells == 54
    assert r.tokens_seen == r.table_cells + r.unverified + r.delegated + r.excluded
    assert r.delegated > 0 and r.delegated_by == {'check_fund': r.delegated}
    assert r.excluded > 0                                    # 접힌 계산 근거
    assert set(r.unverified_by) <= N.UNVERIFIED_KINDS
    assert r.unverified_by.get('KR 문장', 0) > 100
    assert r.unverified_by.get('KR 업종 멀티기간', 0) > 0
    assert r.unverified_by.get('KR 표(지도 밖)', 0) > 0
    assert sum(r.unverified_by.values()) == r.unverified
    assert r.summary().startswith('number audit:')


def test_kr_kinds_are_registered_for_alerts():
    for k in K.UNVERIFIED_KINDS:
        assert k in N.UNVERIFIED_KINDS


def test_before_effective_is_skipped_without_judging(post, data):
    r = K.audit(post, data, D12)                 # 기본 적용일
    assert K.EFFECTIVE > D12 and r.skipped and not r.violations


# ── 지수 표 ──────────────────────────────────────────────────────────────

KOSPI = ('<tr><td>코스피</td><td>5,342.73</td><td class="down">-0.61%</td><td>5,385.94</td><td>5,458.84</td>'
         '<td>5,293.05</td><td>5,375.36</td></tr>')
KOSDAQ = ('<tr><td>코스닥</td><td>696.53</td><td class="down">-1.22%</td><td>703.22</td><td>711.86</td>'
          '<td>687.40</td><td>705.10</td></tr>')


@pytest.mark.parametrize('old,new,col', [
    ('5,342.73', '5,342.74', '종가'), ('-0.61%', '-0.62%', '등락률'), ('-0.61%', '+0.61%', '등락률'),
    ('5,385.94', '5,385.95', '시가'), ('5,375.36', '5,375.30', '전일 종가'),
])
def test_index_cell_value(post, data, old, new, col):
    r = run(sub(post, KOSPI, KOSPI.replace(old, new)), data)
    assert has(r, '[KR 지수]', '행=코스피', f'열={col}', f'인쇄=「{new}」')


@pytest.mark.parametrize('new', ['687.4', '687', '687.400'])
def test_index_two_decimals_fixed(post, data, new):
    r = run(sub(post, KOSDAQ, KOSDAQ.replace('687.40', new)), data)
    assert has(r, '행=코스닥', '열=저가', '형식')


def test_index_change_needs_percent(post, data):
    r = run(sub(post, KOSPI, KOSPI.replace('-0.61%', '-0.61')), data)
    assert has(r, '열=등락률', '형식')


def test_index_core_blank_is_violation(post, data):
    r = run(sub(post, KOSPI, KOSPI.replace('<td>5,342.73</td>', '<td>–</td>')), data)
    assert has(r, '열=종가', '비웠다')


def test_index_unknown_and_duplicate_row(post, data):
    r = run(sub(post, KOSDAQ, KOSDAQ.replace('코스닥', '코스닥150')), data)
    assert has(r, '[KR 지수]', '알 수 없는 행') and has(r, '[KR 지수]', '코스닥', '행이 없다')
    r = run(sub(post, KOSDAQ, KOSPI), data)
    assert has(r, '[KR 지수]', '두 번')


def test_index_rounding_half_up_once(post, data):
    data['kr_market_data']['indices']['KOSPI']['change_pct'] = Decimal('-0.605')
    assert not has(run(post, data), '열=등락률')                       # -0.605 → -0.61
    r = run(sub(post, KOSPI, KOSPI.replace('-0.61%', '-0.60%')), data)
    assert has(r, '열=등락률')


def test_intraday_missing_optional_cells_must_be_blank(post, data):
    data['kr_intraday'] = None
    r = run(post, data)
    assert has(r, '열=시가', '데이터에 값이 없다') and has(r, '열=전일 종가')
    blank = re.sub(r'(<td>코스[피닥]</td><td>[^<]+</td><td class="down">[^<]+</td>)(.*?)</tr>',
                   lambda m: m.group(1) + '<td>–</td>' * 4 + '</tr>', post)
    r = run(blank, data)
    assert not r.violations and not r.warnings


def test_intraday_present_but_blank_is_warning(post, data):
    r = run(sub(post, KOSPI, KOSPI.replace('<td>5,385.94</td>', '<td>-</td>')), data)
    assert not r.violations and warned(r, '열=시가')


def test_missing_index_data(post, data):
    del data['kr_market_data']['indices']['KOSDAQ']
    data['kr_intraday'].pop('KOSDAQ_ohlc')
    r = run(post, data)
    assert has(r, '행=코스닥', '열=종가', '데이터에 값이 없다')
    blank = sub(post, KOSDAQ, '<tr><td>코스닥</td>' + '<td>–</td>' * 6 + '</tr>')
    assert run(blank, data).violations == []
    gone = sub(post, KOSDAQ, '')
    assert run(gone, data).violations == []                            # 데이터에 없는 행은 빠져도 된다


# ── 수급 표 ──────────────────────────────────────────────────────────────

KQ_INST = '<tr><td>기관</td><td class="up">+416</td></tr>'


@pytest.mark.parametrize('new', ['+417', '-416', '+4,16'])
def test_flows_value(post, data, new):
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', new)), data)
    assert has(r, '[KR 수급]', '시장=코스닥', '행=기관')


@pytest.mark.parametrize('new', ['416억원', '약 416', '416 추정', '416.0', '+416 (잠정)'])
def test_flows_unparsable_number_is_violation(post, data, new):
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', new)), data)
    assert has(r, '[KR 수급]', '시장=코스닥', '행=기관', '형식')


@pytest.mark.parametrize('new', ['–', '', '자료 없음'])
def test_flows_blank_core_cell_is_violation(post, data, new):
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', new)), data)
    assert has(r, '[KR 수급]', '행=기관')


def test_flows_plain_positive_and_commas_ok(post, data):
    h = sub(post, '<td class="up">+3,674</td>', '<td class="up">3,674</td>')
    assert run(h, data).violations == []


def test_flows_rows_exactly_once(post, data):
    r = run(sub(post, KQ_INST, '<tr><td>개인</td><td class="up">+3,133</td></tr>'), data)
    assert has(r, '시장=코스닥', '두 번') and has(r, '시장=코스닥', '기관', '행이 없다')
    r = run(sub(post, KQ_INST, KQ_INST + '<tr><td>연기금</td><td>+1</td></tr>'), data)
    assert has(r, '시장=코스닥', '알 수 없는 행')


def test_flows_market_from_h3(post, data):
    r = run(sub(post, '<h3>코스닥 (당일 잠정치)</h3>', '<h3>코스피 (당일 잠정치)</h3>'), data)
    assert has(r, '[KR 수급]', '코스피', '표가 2개')
    assert has(r, '[KR 수급]', '코스닥', '표가 0개')
    r = run(sub(post, '<h3>코스닥 (당일 잠정치)</h3>', ''), data)
    assert has(r, '[KR 수급]', '시장을 정할 수 없다')


def test_flows_two_h3_in_one_block_is_ambiguous(post, data):
    h = sub(post, '<h3>코스닥 (당일 잠정치)</h3>', '')
    h = sub(h, '<h3>코스피 (당일 잠정치)</h3>', '<h3>코스피 (당일 잠정치)</h3><h3>코스닥 (당일 잠정치)</h3>')
    assert has(run(h, data), '시장을 정할 수 없다')


def test_flows_date_row_missing_or_duplicated_is_input_error(post, data):
    d = copy.deepcopy(data)
    d['kr_flows']['KOSPI']['rows'] = [x for x in d['kr_flows']['KOSPI']['rows'] if x['date'] != D12]
    with pytest.raises(K.InputError):
        run(post, d)
    d = copy.deepcopy(data)
    d['kr_flows']['KOSPI']['rows'].append(dict(d['kr_flows']['KOSPI']['rows'][0]))
    with pytest.raises(K.InputError):
        run(post, d)


def _stale(data):
    md = data['kr_market_data']
    md['flows_date'] = {'KOSPI': '2026-11-11', 'KOSDAQ': '2026-11-11'}
    md['flows_provisional'] = {'KOSPI': False, 'KOSDAQ': False}
    for k in ('KOSPI', 'KOSDAQ'):
        f = data['kr_flows'][k]
        f['rows'] = [x for x in f['rows'] if x['date'] != D12]
        f.update(flows_date='2026-11-11', flows_provisional=False, label='전 거래일 기준(2026-11-11)', stale=True)
    return data


STALE_TABLES = (('+3,674', '+6,729'), ('-2,132', '-7,145'), ('-6,772', '-5,034'),
                ('+3,133', '-1,838'), ('-3,563', '-1,354'), ('+416', '+3,130'))


def _stale_post(post, label):
    h = post
    for old, new in STALE_TABLES:
        h = sub(h, f'>{old}</td>', f'>{new}</td>')
    h = sub(h, '<h3>코스피 (당일 잠정치)</h3>', f'<h3>코스피 ({label})</h3>')
    return sub(h, '<h3>코스닥 (당일 잠정치)</h3>', f'<h3>코스닥 ({label})</h3>')


def test_stale_flows_label_meaning(post, data):
    d = _stale(data)
    ok = run(_stale_post(post, '전 거래일 기준(2026-11-11)'), d)
    assert ok.violations == [] and ok.warnings == []
    bad = run(_stale_post(post, '당일 잠정치'), d)
    assert has(bad, '[KR 수급]', '시장=코스피', '라벨') and has(bad, '시장=코스닥', '라벨')
    wrong_day = run(_stale_post(post, '전 거래일 기준(2026-11-10)'), d)
    assert has(wrong_day, '라벨', '2026-11-10')


def test_flows_label_spacing_only_is_warning(post, data):
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', '<h3>코스피 (당일잠정치)</h3>'), data)
    assert r.violations == [] and warned(r, '시장=코스피', '라벨')
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', '<h3>코스피</h3>'), data)
    assert has(r, '시장=코스피', '라벨')


@pytest.mark.parametrize('label', ['당일 잠정치 2026-11-11', '당일 잠정치(11월 11일)', '당일 잠정치 11/11'])
def test_flows_label_wrong_date_is_violation(post, data, label):
    """당일 라벨에 다른 날짜가 붙으면 뜻이 맞아도 막는다(codex 구현 검토 #2)."""
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', f'<h3>코스피 ({label})</h3>'), data)
    assert has(r, '시장=코스피', '라벨', '날짜')


def test_flows_label_right_date_is_only_warning(post, data):
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', '<h3>코스피 (당일 잠정치 2026-11-12)</h3>'), data)
    assert r.violations == [] and warned(r, '시장=코스피', '라벨')


@pytest.mark.parametrize('label', ['당일 잠정치, 전일 확정', '당일 잠정치·전 거래일'])
def test_flows_label_mixed_meaning_is_violation(post, data, label):
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', f'<h3>코스피 ({label})</h3>'), data)
    assert has(r, '시장=코스피', '라벨')


def test_confirmed_label_when_not_provisional(post, data):
    data['kr_market_data']['flows_provisional']['KOSPI'] = False
    data['kr_flows']['KOSPI'].update(flows_provisional=False, label='당일 확정')
    assert has(run(post, data), '시장=코스피', '라벨')
    r = run(sub(post, '<h3>코스피 (당일 잠정치)</h3>', '<h3>코스피 (당일 확정)</h3>'), data)
    assert r.violations == []


def test_flows_files_disagree_is_input_error(post, data):
    data['kr_flows']['KOSPI']['flows_date'] = '2026-11-11'
    with pytest.raises(K.InputError):
        run(post, data)


# ── 거래대금 표 ──────────────────────────────────────────────────────────

TOP1 = '<tr><td>1</td><td>SK하이닉스</td><td>개별주</td><td>5.18조원</td><td>-</td></tr>'
TOP3 = ('<tr><td>3</td><td>반도체 테마 ETF</td><td><span class="pill pill-long">테마·롱</span></td>'
        '<td>1.99조원</td><td>29종 합산</td></tr>')


@pytest.mark.parametrize('new,why', [('5.17조원', '데이터'), ('5.2조원', '형식'), ('5.18조', '형식'),
                                     ('5.18조 원', '형식'), ('51,834억원', '형식'), ('5.18', '형식')])
def test_top_value(post, data, new, why):
    r = run(sub(post, TOP1, TOP1.replace('5.18조원', new)), data)
    assert has(r, '[KR 거래대금]', '행=1위', '열=거래대금', why)


def test_top_value_rounding_boundary(post, data):
    data['kr_top_value'][0]['value'] = 5175000          # 5.175 → 5.18 만
    assert run(post, data).violations == []
    r = run(sub(post, TOP1, TOP1.replace('5.18조원', '5.17조원')), data)
    assert has(r, '행=1위', '열=거래대금')


def test_top_name_rank_members(post, data):
    assert has(run(sub(post, TOP1, TOP1.replace('SK하이닉스', 'SK 하이닉스')), data), '행=1위', '열=종목/ETF')
    assert has(run(sub(post, TOP3, TOP3.replace('29종', '28종')), data), '행=3위', '열=비고')
    assert has(run(sub(post, TOP3, TOP3.replace('29종 합산', '상위 3종')), data), '행=3위', '열=비고')
    r = run(sub(post, TOP1, TOP1.replace('<td>1</td>', '<td>2</td>')), data)
    assert has(r, '[KR 거래대금]', '순위')


def test_top_note_text_without_digits_is_fine(post, data):
    assert run(sub(post, TOP1, TOP1.replace('<td>-</td>', '<td>배당락일</td>')), data).violations == []


def test_top_rows_count(post, data):
    r = run(sub(post, TOP1, ''), data)
    assert has(r, '[KR 거래대금]')
    data['kr_top_value'] = data['kr_top_value'][:9]
    assert has(run(post, data), '[KR 거래대금]', '행')


# ── 금리 표 ──────────────────────────────────────────────────────────────

R3 = '<tr><td>국고채 3년</td><td>3.729%</td><td>0.0</td><td>2026-11-12</td></tr>'
RBASE = '<tr><td>한국은행 기준금리</td><td>3.00%</td><td>0.0</td><td>2026년 10월 기준</td></tr>'


@pytest.mark.parametrize('new,col', [('<td>3.73%</td>', '금리'), ('<td>3.728%</td>', '금리'),
                                     ('<td>3.729</td>', '금리'), ('<td>0</td>', '전일比(bp)'),
                                     ('<td>+0.1</td>', '전일比(bp)'), ('<td>2026-11-11</td>', '기준일'),
                                     ('<td>11월 12일</td>', '기준일')])
def test_rate_cells(post, data, new, col):
    cells = re.findall(r'<td>[^<]*</td>', R3)
    idx = {'금리': 1, '전일比(bp)': 2, '기준일': 3}[col]
    r = run(sub(post, R3, R3.replace(cells[idx], new)), data)
    assert has(r, '[KR 금리]', '행=국고채 3년', f'열={col}')


def test_rate_trailing_zero_allowed(post, data):
    h = sub(post, R3, R3.replace('3.729%', '3.7290%').replace('<td>0.0</td>', '<td>0.00</td>'))
    assert run(h, data).violations == []


def test_rate_original_notation_decimals(post, data):
    data['kr_econ']['series']['국고채 3년']['value'] = Decimal('3.7290')
    assert has(run(post, data), '행=국고채 3년', '열=금리', '자릿수')


def test_policy_rate_month_forms(post, data):
    for ok in ('2026-10', '2026년 10월 기준'):
        h = sub(post, RBASE, RBASE.replace('2026년 10월 기준', ok))
        assert run(h, data).violations == [], ok
    h = sub(post, RBASE, RBASE.replace('<td>0.0</td>', '<td>0.0(전월比)</td>'))
    assert run(h, data).violations == []
    for bad in ('2026-09', '2026년 9월 기준', '2026-10-01'):
        h = sub(post, RBASE, RBASE.replace('2026년 10월 기준', bad))
        assert has(run(h, data), '행=한국은행 기준금리', '열=기준일'), bad
    h = sub(post, R3, R3.replace('<td>0.0</td>', '<td>0.0(전월比)</td>'))
    assert has(run(h, data), '행=국고채 3년', '열=전일比(bp)')       # 일 단위 행에는 꼬리가 없다


def test_rate_rows(post, data):
    assert has(run(sub(post, R3, ''), data), '[KR 금리]', '국고채 3년', '행이 없다')
    assert has(run(sub(post, R3, R3.replace('국고채 3년', '국고채 5년')), data), '[KR 금리]', '알 수 없는 행')


def test_rate_missing_key_row_must_be_absent():
    h, d = html_of(D20), data_of(D20)
    assert '국고채 3년' in d['kr_econ']['missing']
    row = '<tr><td>국고채 3년</td><td>–</td><td>–</td><td>–</td></tr>'
    h2 = sub(h, '<tbody>\n      <tr><td>국고채 10년</td>', '<tbody>\n      ' + row + '<tr><td>국고채 10년</td>')
    assert has(run(h2, d, D20), '[KR 금리]', '국고채 3년', 'missing')


def test_rate_table_presence_follows_series(post, data):
    data['kr_econ'] = dict(data['kr_econ'], series={}, missing=list(data['kr_econ']['series']))
    assert has(run(post, data), '[KR 금리]', '표가 1개')
    no_table = re.sub(r'<table>\s*<thead><tr><th>지표</th>.*?</table>', '', post, flags=re.S)
    assert run(no_table, data).violations == []
    data['kr_econ'] = None
    assert run(no_table, data).violations == []
    assert has(run(no_table, data_of()), '[KR 금리]', '표가 0개')


# ── 표 구조 ─────────────────────────────────────────────────────────────

def test_renamed_section_is_violation(post, data):
    r = run(sub(post, '<h2>지수 &amp; 장중</h2>', '<h2>지수와 장중</h2>'), data)
    assert has(r, '「지수 & 장중」 섹션이 0개')


def test_deleted_table_is_violation(post, data):
    h = re.sub(r'<table>\s*<thead><tr><th>지수</th>.*?</table>', '', post, flags=re.S)
    assert has(run(h, data), '[KR 지수]', '표가 0개')


def test_moved_table_is_violation(post, data):
    m = re.search(r'<table>\s*<thead><tr><th>지표</th>.*?</table>', post, re.S)
    h = post.replace(m.group(0), '', 1)
    h = sub(h, '<h2>향후 확인 일정</h2>', '<h2>향후 확인 일정</h2>' + m.group(0))
    r = run(h, data)
    assert has(r, '[KR 금리]', '표가 0개') and has(r, '다른 섹션', '향후 확인 일정')


def test_extra_table_in_mapped_section(post, data):
    extra = '<table><thead><tr><th>시각</th><th>코스피(억원)</th></tr></thead><tbody><tr><td>10:00</td><td>+1</td></tr></tbody></table>'
    r = run(sub(post, '<h2>수급</h2>', '<h2>수급</h2>' + extra), data)
    assert has(r, '[KR 수급]', '지도에 없는 표')


def test_duplicate_section(post, data):
    r = run(sub(post, '<h2>정책·정치 촉매</h2>', '<h2>정책·정치 촉매</h2><h2>수급</h2>'), data)
    assert has(r, '「수급」', '소제목')


def test_colspan_is_violation(post, data):
    assert has(run(sub(post, KQ_INST, KQ_INST.replace('<td>기관</td>', '<td colspan="2">기관</td>')), data),
               '[KR 수급]', 'colspan')
    r = run(sub(post, KOSPI, KOSPI.replace('<td>코스피</td>', '<td rowspan="2">코스피</td>')), data)
    assert has(r, '[KR 지수]', 'colspan')


def test_mapped_table_in_closed_details_is_violation(post, data):
    m = re.search(r'<table>\s*<thead><tr><th>지수</th>.*?</table>', post, re.S)
    h = sub(post, m.group(0), '<details><summary>표</summary>' + m.group(0) + '</details>')
    assert has(run(h, data), '[KR 지수]')


def test_wrong_copy_of_mapped_table_in_open_details(post, data):
    # codex 설계 검토 #5 재현 — 열린 details 는 제외가 아니다. 지도 섹션 안이면 표 2개, 밖이면 「다른 섹션」
    m = re.search(r'<table>\s*<thead><tr><th>지수</th>.*?</table>', post, re.S)
    wrong = m.group(0).replace('5,342.73', '5,999.99')
    h = sub(post, '<h2>지수 &amp; 장중</h2>', '<h2>지수 &amp; 장중</h2><details open><summary>원자료</summary>'
            + wrong + '</details>')
    assert has(run(h, data), '[KR 지수]', '표가 2개')
    h = sub(post, '<h2>향후 확인 일정</h2>', '<h2>향후 확인 일정</h2><details open>' + wrong + '</details>')
    assert has(run(h, data), '[KR 지수]', '다른 섹션')


# ── 숨김·SVG·쪼갠 수치 ──────────────────────────────────────────────────

@pytest.mark.parametrize('cell', ['+416<span hidden>9</span>', '+416<span style="display:none">9</span>',
                                  '+416<svg><text>999</text></svg>'])
def test_hidden_digits_in_owned_cell(post, data, cell):
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', cell)), data)
    assert has(r, '[KR 수급]', '행=기관', '숨')


@pytest.mark.parametrize('cell', ['<span style="opacity:0">+416</span>', '<span style="opacity: 0.0;">+416</span>',
                                  '<span style="font-size:0">+416</span>', '<span style="color:transparent">+416</span>'])
def test_style_hidden_whole_value_in_owned_cell(post, data, cell):
    """US 파서가 보이는 글로 읽는 인라인 숨김 — 값이 맞아도 막는다(codex 구현 검토 #3)."""
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', cell)), data)
    assert has(r, '[KR 수급]', '행=기관', '숨')


def test_opacity_nonzero_is_not_hidden(post, data):
    r = run(sub(post, KQ_INST, KQ_INST.replace('+416', '<span style="opacity:0.8">+416</span>')), data)
    assert r.violations == []


def test_hidden_or_split_number_anywhere(post, data):
    h = sub(post, '<h2>수급</h2>', '<h2>수급</h2><p>외국인 <span hidden>9.99%</span></p>')
    assert has(run(h, data), '숨긴 요소')
    h = sub(post, KQ_INST, KQ_INST.replace('+416', '+4<b>16</b>'))
    assert has(run(h, data), '쪼개져')


def test_open_details_is_not_excluded(post, data):
    base = run(post, data)
    h = post.replace('<details data-provenance>', '<details data-provenance open>', 1)
    r = run(h, data)
    assert r.excluded < base.excluded and r.unverified > base.unverified
    assert r.tokens_seen == base.tokens_seen


# ── 펀드 위임 ────────────────────────────────────────────────────────────

def test_fund_delegation_needs_same_day_view(post, data):
    base = run(post, data)
    data['kr_fund_view'] = dict(data['kr_fund_view'], report_date='2026-11-11')
    r = run(post, data)
    assert r.delegated == 0 and r.unverified_by.get('KR 펀드 블록(위임 안 됨)') == base.delegated
    data['kr_fund_view'] = None
    r = run(post, data)
    assert r.delegated == 0 and r.unverified_by.get('KR 펀드 블록(위임 안 됨)') == base.delegated


def test_fund_delegation_fails_when_block_is_edited(post, data):
    h = sub(post, 'CD 91일 3.370%(11/12)', 'CD 91일 3.371%(11/12)')
    r = run(h, data)
    assert r.delegated == 0 and r.unverified_by.get('KR 펀드 블록(위임 안 됨)', 0) > 0


# ── 위반 줄 형식(정정기가 줄 단위로 비교) ───────────────────────────────

def test_violation_line_is_stable_when_positions_move(post, data):
    bad = sub(post, KQ_INST, KQ_INST.replace('+416', '+417'))
    a = run(bad, data).violations
    moved = sub(bad, '<h2>수급</h2>', '<h2>수급</h2><p>앞에 끼운 문단 1.5%.</p>')
    b = run(moved, data).violations
    assert a == b == ['[KR 수급] 시장=코스닥 행=기관 열=순매수(억원) 인쇄=「+417」 기대=+416 — 데이터와 다르다']
    for v in a:
        assert not v.startswith(('경고', 'number audit:', 'FATAL'))


# ── 입력 ────────────────────────────────────────────────────────────────

def test_report_date_mismatch_is_input_error(post, data):
    with pytest.raises(K.InputError):
        K.audit(post, data, '2026-11-13', effective=OPEN)


def _ws(tmp_path, day=D12, drop=(), corrupt=()):
    d = tmp_path / 'ws'
    d.mkdir(exist_ok=True)
    for name in os.listdir(os.path.join(FIX, day)):
        if name.endswith('.json') and name[:-5] not in drop:
            shutil.copy(os.path.join(FIX, day, name), d / name)
    for k in corrupt:
        (d / f'{k}.json').write_text('{', encoding='utf-8')
    return d


@pytest.mark.parametrize('drop', ['kr_market_data', 'kr_flows', 'kr_top_value'])
def test_required_inputs(tmp_path, drop):
    with pytest.raises(K.InputError):
        K.load_inputs(str(_ws(tmp_path, drop=(drop,))))


def test_optional_inputs(tmp_path):
    d = K.load_inputs(str(_ws(tmp_path, drop=('kr_econ', 'kr_intraday', 'kr_fund_view'))))
    assert d['kr_econ'] is None and d['kr_intraday'] is None and d['kr_fund_view'] is None


def test_corrupt_econ_is_input_error(tmp_path):
    with pytest.raises(K.InputError):
        K.load_inputs(str(_ws(tmp_path, corrupt=('kr_econ',))))


def test_decimal_notation_is_kept(data):
    assert str(data['kr_econ']['series']['한국은행 기준금리']['value']) == '3.0'
    assert isinstance(data['kr_fund_view'], dict)


# ── CLI ─────────────────────────────────────────────────────────────────

def cli(tmp_path, html, *extra, name=f'{D12}.html', ws=None):
    p = tmp_path / name
    p.write_text(html, encoding='utf-8')
    ws = ws or _ws(tmp_path)
    args = [sys.executable, os.path.join(SCRIPTS, 'check_numbers.py'), '--html', str(p), '--datadir', str(ws),
            '--market', 'kr', *extra]
    return subprocess.run(args, capture_output=True, text=True)


def test_cli_ok_json(tmp_path, post):
    r = cli(tmp_path, post, '--date', D12, '--effective', OPEN, '--json')
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert set(out) == {'skipped', 'warnings', 'violations', 'summary', 'counts', 'unverified_by'}
    assert out['skipped'] is False and out['counts']['table_cells'] == 54 and out['counts']['prose_judged'] == 0
    assert set(out['counts']) == {'tokens_seen', 'table_cells', 'prose_judged', 'unverified', 'delegated',
                                  'excluded'}


def test_cli_violation(tmp_path, post):
    r = cli(tmp_path, sub(post, KQ_INST, KQ_INST.replace('+416', '+417')), '--date', D12, '--effective', OPEN)
    assert r.returncode == 1 and '시장=코스닥 행=기관' in r.stdout
    assert r.stdout.strip().splitlines()[-1].startswith('number audit:')


def test_cli_kr_requires_date(tmp_path, post):
    r = cli(tmp_path, post, '--effective', OPEN)
    assert r.returncode == 2 and '--date' in r.stderr


def test_cli_date_must_match_filename_and_data(tmp_path, post):
    assert cli(tmp_path, post, '--date', '2026-11-13', '--effective', OPEN).returncode == 2
    r = cli(tmp_path, post, '--date', '2026-11-13', '--effective', OPEN, name='draft.html')
    assert r.returncode == 2 and 'report_date' in r.stderr
    r = cli(tmp_path, post, '--date', D12, '--effective', OPEN, name='kr_brief.html')
    assert r.returncode == 0, r.stderr                          # 날짜 없는 초안은 --date 로


def test_cli_skips_before_effective_without_reading_inputs(tmp_path, post):
    r = cli(tmp_path, post, '--date', D12, '--json', ws=tmp_path / 'nothing-here')
    assert r.returncode == 0 and json.loads(r.stdout) == {'skipped': True, 'effective': K.EFFECTIVE}


def test_cli_missing_required_input_is_2(tmp_path, post):
    r = cli(tmp_path, post, '--date', D12, '--effective', OPEN, ws=_ws(tmp_path, drop=('kr_flows',)))
    assert r.returncode == 2 and 'FATAL' in r.stderr


def test_cli_ignores_prose_flag(tmp_path, post):
    r = cli(tmp_path, post, '--date', D12, '--effective', OPEN, '--prose', 'block')
    assert r.returncode == 0, r.stdout + r.stderr


def test_production_config_does_not_override_effective():
    with open(os.path.join(os.path.dirname(SCRIPTS), 'config', 'prepub_gates.json'), encoding='utf-8') as fh:
        cfg = json.load(fh)
    g = next(x for x in cfg['markets']['kr']['gates'] if x['name'] == 'check_numbers')
    assert '--effective' not in g['argv']
    assert g['argv'] == ['scripts/check_numbers.py', '--html', '{html}', '--datadir', '{datadir}',
                         '--market', 'kr', '--date', '{date}']
    assert g['kind'] == 'numbers' and g['required'] is True and g['json'] is True
