"""US 일간 수치 전수 대조(`us.number_audit`, CLI `scripts/check_numbers.py`).

고정 자료: 2026-11-05 발행본과 그 발행 커밋의 데이터(`fixtures/number_audit/2026-11-05`).
정상 글은 통과하고, 일부러 틀린 숫자는 자리째 걸려야 한다.
"""
import json
import os
import subprocess
import sys

import pytest

from us import number_audit as N

HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures', 'number_audit', '2026-11-05')
SCRIPTS = os.path.dirname(os.path.dirname(HERE))


def load(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return fh.read() if name.endswith('.html') else json.load(fh)


@pytest.fixture(scope='module')
def post():
    return load('post.html')


@pytest.fixture()
def data():
    return {k: load(f'{k}.json') for k in ('market_data', 'econ_indicators', 'macro_metrics',
                                            'fund_board')}


def run(html, data, prose='block'):
    return N.audit(html, data, prose=prose)


def sub(html, old, new, count=1):
    assert html.count(old) >= 1, old
    return html.replace(old, new, count)


# ── 토크나이저 ───────────────────────────────────────────────────────────

@pytest.mark.parametrize('text,value,unit,dec', [
    ('4.477%', 4.477, '%', 3), ('-10.4bp', -10.4, 'bp', 1), ('+11.57p', 11.57, 'p', 2),
    ('1.6배', 1.6, '배', 1), ('189,000건', 189000, '건', 0), ('12.6억 달러', 12.6, '억', 1),
    ('$90.71', 90.71, '$', 2), ('1,356원', 1356, '원', 0), ('157.81엔', 157.81, '엔', 2),
    ('-3.644%p', -3.644, '%p', 3), ('−0.5%', -0.5, '%', 1), ('101.595', 101.595, '', 3),
    ('51,523.06', 51523.06, '', 2), ('3.2%포인트', 3.2, '%p', 1), ('99K', 99, 'K', 0),
    ('7,523K', 7523, 'K', 0), ('-99B', -99, 'B', 0),
])
def test_tokens_units(text, value, unit, dec):
    toks = N.tokens(text)
    assert len(toks) == 1, toks
    t = toks[0]
    assert (t.value, t.unit, t.decimals) == (value, unit, dec)


@pytest.mark.parametrize('text', [
    '2026-11-05', '11월 5일', '08:30', '2Y', '10년물', 'S&P500', 'FTSE100', '20개 구간',
    '5세션', '50/200일선', '2s10s', '러셀2000', '504거래일', '2025년', '3pm',
])
def test_tokens_exclude(text):
    assert N.tokens(text) == []


def test_tokens_range_hyphen_is_not_sign():
    assert [t.value for t in N.tokens('5년-30년 구간이 4.5bp')] == [4.5]


def test_tokens_comma_after_number():
    assert [t.raw for t in N.tokens('S&P는 4.36% 내린 7,354, 나스닥은')] == ['4.36%', '7,354']


def test_tokens_keep_positions():
    s = 'S&P는 4.36% 내린 7,354'
    toks = N.tokens(s)
    assert [s[t.start:t.end] for t in toks] == ['4.36%', '7,354']


# ── 정상 발행본 ──────────────────────────────────────────────────────────

def test_published_post_passes(post, data):
    r = run(post, data)
    assert r.violations == [], r.violations
    assert r.table_cells == 69      # 7×2 + 6×2 + 11 + 4×4 + 4×2 + 4×2 (기준일 칸은 날짜라 수치가 아니다)
    assert r.prose_judged >= 20


def test_report_counts_every_token(post, data):
    r = run(post, data)
    total = (r.table_cells + r.prose_judged + r.unverified + r.delegated + r.excluded)
    assert total == r.tokens_seen
    assert r.unverified > 0          # 숨기지 않는다 — 판정 못 한 수치를 센다


# ── 층 1: 표 칸 ──────────────────────────────────────────────────────────

YIELD_2Y = ('<td data-label="만기">2Y</td><td data-label="종가">4.477%</td>'
            '<td data-label="전일 변화" class="sc-up">-10.4</td>'
            '<td data-label="1주 전">4.656%</td><td data-label="주간 변화" class="sc-up">-17.9</td>')


def test_table_last_digit(post, data):
    bad = sub(post, YIELD_2Y, YIELD_2Y.replace('4.477%', '4.478%'))
    v = run(bad, data).violations
    assert any('2Y' in x and '종가' in x for x in v), v


def test_table_sign_flip(post, data):
    bad = sub(post, YIELD_2Y, YIELD_2Y.replace('>-10.4<', '>+10.4<'))
    assert any('2Y' in x and '전일' in x for x in run(bad, data).violations)


def test_table_weekly_change_is_computed(post, data):
    bad = sub(post, YIELD_2Y, YIELD_2Y.replace('>-17.9<', '>-17.8<'))
    assert any('2Y' in x and '주간' in x for x in run(bad, data).violations)


def test_table_row_swap(post, data):
    # S&P 값을 나스닥 행에 — 둘 다 데이터 어딘가에는 있는 값이다
    sp = '<td data-label="지수">S&amp;P500</td>'
    nq = '<td data-label="지수">나스닥</td>'
    a, b = post.index(sp), post.index(nq)
    assert a != b
    bad = post.replace(sp, '@@SP@@').replace(nq, sp).replace('@@SP@@', nq)
    v = run(bad, data).violations
    assert any('나스닥' in x or 'Nasdaq' in x for x in v), v


def test_table_rounding(post, data):
    # S&P pct -4.3557 → -4.36% 는 맞고 -4.35% 는 틀리다
    cell = '<td data-label="등락률" class="sc-dn">-4.36%</td>'
    assert cell in post
    assert any('S&P' in x for x in run(post.replace(cell, cell.replace('-4.36', '-4.35')),
                                         data).violations)


def test_double_rounding_only_in_prose():
    # 0.5849 → 0.58 만 맞다. 0.585 를 거친 0.59 는 문장에서만 받는다
    assert N.close_enough(0.58, 2, 0.5849) and not N.close_enough(0.59, 2, 0.5849)
    assert N.close_enough(0.59, 2, 0.5849, double=True)


def test_rounding_half_both_sides():
    assert N.close_enough(1.12, 2, 1.125) and N.close_enough(1.13, 2, 1.125)
    assert not N.close_enough(1.14, 2, 1.125)
    assert N.close_enough(7354, 0, 7353.73)
    assert not N.close_enough(7355, 0, 7353.73)


def test_table_unknown_row(post, data):
    bad = sub(post, '<td data-label="만기">5Y</td>', '<td data-label="만기">7Y</td>')
    v = run(bad, data).violations
    assert any('7Y' in x for x in v) and any('5Y' in x and '없다' in x for x in v), v


def test_table_duplicate_row(post, data):
    row = '<tr>' + YIELD_2Y + '</tr>'
    assert row in post
    bad = post.replace(row, row + row)
    assert any('두 번' in x for x in run(bad, data).violations)


def test_table_header_label_mismatch(post, data):
    bad = sub(post, '<td data-label="주간 변화" class="sc-up">-17.9</td>',
              '<td data-label="1주 전" class="sc-up">-17.9</td>')
    assert any('열' in x for x in run(bad, data).violations)


def test_table_unknown_column(post, data):
    bad = sub(post, '<th>주간 변화(bp)</th>', '<th>주간 변화(bp)</th><th>메모</th>')
    assert any('메모' in x for x in run(bad, data).violations)


def test_table_header_date(post, data):
    bad = sub(post, '<th>종가(11월 5일)</th>', '<th>종가(11월 4일)</th>')
    assert any('11월 4일' in x for x in run(bad, data).violations)


def test_table_basis_date_cell(post, data):
    bad = sub(post, '<td data-label="지수">항셍</td><td data-label="종가">23,919.50</td>'
                    '<td data-label="등락" class="sc-up">+1.67%</td><td data-label="기준일">11월 4일</td>',
              '<td data-label="지수">항셍</td><td data-label="종가">23,919.50</td>'
              '<td data-label="등락" class="sc-up">+1.67%</td><td data-label="기준일">11월 5일</td>')
    assert any('항셍' in x and '기준일' in x for x in run(bad, data).violations)


def test_table_dash_when_data_exists_warns(post, data):
    # 지우기는 창작보다 낫다(규칙 3) — 막지 않고 경고한다
    bad = sub(post, '<td data-label="종가">$90.71</td>', '<td data-label="종가">—</td>')
    r = run(bad, data)
    assert r.violations == [] and any('WTI' in x for x in r.warnings)


def test_table_text_cell_with_digit_blocks(post, data):
    bad = sub(post, '<td data-label="종가">$90.71</td>', '<td data-label="종가">약 90달러</td>')
    assert any('WTI' in x for x in run(bad, data).violations)


def test_vix_unit_follows_data(post, data):
    m = data['market_data']
    m['price_context']['moves']['VIX']['unit'] = '%'       # 10/23 이전 자료
    assert any('VIX' in x and '단위' in x for x in run(post, data).violations)
    bad = sub(post, '+11.57p', '+11.57%')
    assert not any('VIX' in x for x in run(bad, data).violations)


@pytest.mark.parametrize('sentence', [
    '2s10s가 1주 사이 18.0bp 벌어졌다.', '브렌트가 크게 오른 날에도 10년 기대인플레가 2.36%에서 멈췄다.',
    'S&amp;P는 7,726에 열어 7,722에 끝났다.', 'S&amp;P500이 처음으로 7,800선 위에서 마감했다.',
    '다우는 보잉이 10.69% 급락한 날 0.03% 올랐다.', 'WTI는 아침에 100.40달러까지 올랐다.',
    '엔/달러는 157.50~158.37엔 사이를 오갔다.', '금이 4,000달러 아래로 밀렸다.',
    'S&amp;P 성장주가 1.46% 내리는 동안 가치주는 올랐다.', '그날 10년물 5bp 하락은 전부 실질금리 몫이다.',
    '러셀2000만 보합(+0.03%)에서 열렸다.', '브렌트가 3%대 오른 날이다.',
    '로이터는 WTI가 2.7% 오른 92.87달러에 정산했다고 전했다.', '9월 29일 36.6bp였던 2s10s가 11.4bp 넓어졌다.',
])
def test_prose_known_false_alarms_are_unverified(sentence):
    m = {'report_date': '2026-11-05',
         'indices': {k: {'last': 7722.7, 'pct': 0.31, 'date': '2026-11-05'}
                     for k in ('S&P 500', 'Dow', 'Russell 2000')},
         'spread_2s10s_bp': 44.7, 'yields': {'10Y': {'level': 4.8, 'bp': 1.0, 'week_ago': 4.7}},
         'commodities': {k: {'last': 91.26, 'pct': -1.0, 'date': '2026-11-05'}
                         for k in ('WTI', 'Brent', 'Gold')},
         'fx': {'USD/JPY': {'last': 158.06, 'pct': 0.1, 'date': '2026-11-05'}}}
    html = f'<html><body><section><h2>주식</h2><p>{sentence}</p></section></body></html>'
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == [], r.violations


def test_table_unit_swap(post, data):
    bad = sub(post, '<td data-label="종가">4.477%</td>', '<td data-label="종가">4.477bp</td>')
    assert any('단위' in x for x in run(bad, data).violations)


def test_table_missing(post, data):
    start = post.index('<table', post.index('<h2>원자재'))
    end = post.index('</table>', start) + len('</table>')
    bad = post[:start] + post[end:]
    assert any('원자재' in x and '표' in x for x in run(bad, data).violations)


def test_vix_is_points(post, data):
    bad = sub(post, '+11.57p', '+11.57%')
    assert any('VIX' in x for x in run(bad, data).violations)


# ── 층 2: 문장 ───────────────────────────────────────────────────────────

def test_prose_wrong_value(post, data):
    bad = sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.37% 내린')
    v = run(bad, data).violations
    assert any('S&P' in x and '4.37' in x for x in v), v


def test_prose_direction_flip(post, data):
    bad = sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.36% 오른')
    assert any('4.36' in x for x in run(bad, data).violations)


def test_prose_carry_level(post, data):
    bad = sub(post, '4.36% 내린 7,354', '4.36% 내린 7,364')
    assert any('7,364' in x for x in run(bad, data).violations)


def test_prose_warn_mode_does_not_block(post, data):
    bad = sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.37% 내린')
    r = run(bad, data, prose='warn')
    assert r.violations == []
    assert any('4.37' in x for x in r.warnings)


def test_prose_field_mixing():
    # 가격 4.5 가 등락률 4.5% 를 통과시키면 안 된다
    m = {'report_date': '2026-11-05',
         'indices': {'S&P 500': {'last': 4.5, 'pct': 1.2, 'chg': 0.05, 'date': '2026-11-05'}}}
    html = '<html><body><section><h2>주식</h2><p>S&amp;P는 4.5% 올랐다.</p></section></body></html>'
    v = N.audit(html, {'market_data': m}, prose='block', tables=False).violations
    assert any('4.5' in x for x in v), v


def test_prose_two_assets_is_unverified():
    m = {'report_date': '2026-11-05',
         'indices': {'S&P 500': {'last': 7000.0, 'pct': -1.0, 'date': '2026-11-05'},
                     'Nasdaq': {'last': 24000.0, 'pct': -2.0, 'date': '2026-11-05'}}}
    html = ('<html><body><section><h2>주식</h2><p>S&amp;P와 나스닥은 3.1% 내렸다.</p>'
            '</section></body></html>')
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == [] and r.unverified == 1


def test_prose_temporal_cue_is_unverified():
    m = {'report_date': '2026-11-05',
         'indices': {'Dow': {'last': 51523.0, 'pct': -3.44, 'date': '2026-11-05'}}}
    html = ('<html><body><section><h2>주식</h2><p>전날 다우가 3.1% 올랐다.</p>'
            '</section></body></html>')
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == [] and r.unverified == 1


def test_prose_blocker_alias():
    # 「나스닥 100」은 나스닥 종합이 아니다
    m = {'report_date': '2026-11-05',
         'indices': {'Nasdaq': {'last': 24000.0, 'pct': -2.0, 'date': '2026-11-05'}}}
    html = ('<html><body><section><h2>주식</h2><p>나스닥 100은 3.1% 내렸다.</p>'
            '</section></body></html>')
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == []


def test_gold_alias_not_in_rate_word():
    m = {'report_date': '2026-11-05',
         'commodities': {'Gold': {'last': 4108.9, 'pct': 0.85, 'date': '2026-11-05'}}}
    html = ('<html><body><section><h2>원자재</h2><p>금리가 4.5% 근처다. 금은 0.85% 올랐다.</p>'
            '</section></body></html>')
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == [] and r.prose_judged == 1


def test_meta_description_is_audited(post, data):
    assert '<meta name="description"' in post
    i = post.index('<meta name="description"')
    j = post.index('>', i)
    meta = post[i:j]
    bad = post[:i] + meta.replace('content="', 'content="S&amp;P는 9.99% 내렸다. ') + post[j:]
    assert any('9.99' in x for x in run(bad, data).violations)


# ── 숨김·쪼갬 ─────────────────────────────────────────────────────────────

def test_hidden_number_blocks(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><p hidden>10년물 9.99%</p>')
    assert any('숨' in x for x in run(bad, data).violations)


def test_display_none_number_blocks(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><span style="display:none">12.34%</span>')
    assert any('숨' in x for x in run(bad, data).violations)


def test_split_number_blocks(post, data):
    bad = sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.<span>36</span>% 내린')
    assert any('쪼개' in x for x in run(bad, data).violations)


# ── 층 3: 위임 ───────────────────────────────────────────────────────────

def test_fund_section_delegated(post, data):
    r = run(post, data)
    assert r.delegated_by.get('check_fund', 0) > 0


def test_fund_tampered_is_not_delegated(post, data):
    i = post.index('data-fund-board')
    j = post.index('%', i)
    k = j - 1
    while post[k].isdigit() or post[k] == '.':
        k -= 1
    bad = post[:k + 1] + '99.99' + post[j:]
    r = run(bad, data)
    assert r.delegated_by.get('check_fund', 0) == 0


def test_sector_perf_delegated(post, data):
    assert run(post, data).delegated_by.get('check_sector_perf', 0) > 0


def test_macro_marked_rows_delegated(post, data):
    r = run(post, data)
    assert r.delegated_by.get('macro_table_gate', 0) > 0


def test_provenance_excluded(post, data):
    assert run(post, data).excluded > 0


# ── 적용일·입력 ──────────────────────────────────────────────────────────

def test_before_effective_is_skipped(post, data):
    data['market_data'] = dict(data['market_data'], report_date='2026-09-30')
    r = run(post, data)
    assert r.skipped and r.violations == []


def test_missing_report_date_fails(post, data):
    data['market_data'] = dict(data['market_data'])
    data['market_data'].pop('report_date')
    with pytest.raises(N.InputError):
        run(post, data)


# ── CLI ─────────────────────────────────────────────────────────────────

def cli(tmp_path, html, prose=None, drop=()):
    p = tmp_path / 'morning_brief_2026-11-05.html'
    p.write_text(html, encoding='utf-8')
    d = tmp_path / 'ws'
    d.mkdir(exist_ok=True)
    for k in ('market_data', 'econ_indicators', 'macro_metrics', 'fund_board'):
        if k not in drop:
            (d / f'{k}.json').write_text(json.dumps(load(f'{k}.json')), encoding='utf-8')
    args = [sys.executable, os.path.join(SCRIPTS, 'check_numbers.py'), '--html', str(p),
            '--datadir', str(d)]
    if prose:
        args += ['--prose', prose]
    return subprocess.run(args, capture_output=True, text=True)


def test_cli_ok(tmp_path, post):
    r = cli(tmp_path, post)
    assert r.returncode == 0, r.stdout + r.stderr
    assert '표 칸' in r.stdout


def test_cli_violation(tmp_path, post):
    r = cli(tmp_path, post.replace('>4.477%<', '>4.478%<', 1))
    assert r.returncode == 1 and '2Y' in r.stdout


def test_cli_missing_market_is_2(tmp_path, post):
    assert cli(tmp_path, post, drop=('market_data',)).returncode == 2


def test_cli_prose_warn(tmp_path, post):
    r = cli(tmp_path, sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.37% 내린'), prose='warn')
    assert r.returncode == 0 and '경고' in r.stdout


def test_cli_default_mode_reads_config(tmp_path, post):
    r = cli(tmp_path, sub(post, 'S&amp;P는 4.36% 내린', 'S&amp;P는 4.37% 내린'))
    with open(os.path.join(os.path.dirname(SCRIPTS), 'config', 'number_audit.json')) as fh:
        mode = json.load(fh)['prose']
    assert r.returncode == (1 if mode == 'block' else 0)


def test_cli_date_mismatch_is_2(tmp_path, post):
    p = tmp_path / 'morning_brief_2026-11-06.html'
    p.write_text(post, encoding='utf-8')
    d = tmp_path / 'ws'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps(load('market_data.json')), encoding='utf-8')
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_numbers.py'), '--html', str(p),
                        '--datadir', str(d)], capture_output=True, text=True)
    assert r.returncode == 2 and '다르다' in r.stderr


def test_cli_old_post_skips_before_reading_inputs(tmp_path):
    p = tmp_path / '2026-09-10.html'
    p.write_text('<p>x</p>', encoding='utf-8')
    r = subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_numbers.py'), '--html', str(p),
                        '--datadir', str(tmp_path / 'none')], capture_output=True, text=True)
    assert r.returncode == 0 and '적용일' in r.stdout


# ── codex 구현 검토 1차(2026-11-07) 재현 ─────────────────────────────────

def test_c1_renamed_section_title_blocks(post, data):
    bad = post.replace('<h2>채권</h2>', '<h2>채권 동향</h2>').replace('>4.477%<', '>9.999%<', 1)
    assert any('채권' in x and '섹션' in x for x in run(bad, data).violations)


def test_c1_extra_subheading_is_allowed(post, data):
    # 소제목 h2 는 막지 않는다(codex 재검토 #6) — 섹션 제목은 첫 h2
    assert run(sub(post, '<h2>채권</h2>', '<h2>채권</h2><h2>장중 흐름</h2>'), data).violations == []


def test_c1_market_title_as_subheading_blocks(post, data):
    # 「장중 흐름」 섹션 안에 「채권」 소제목을 넣어 경계를 흐리면 막는다
    bad = sub(post, '<h2>채권</h2>', '<h2>장중 흐름</h2><h2>채권</h2>')
    v = run(bad, data).violations
    assert any('소제목' in x for x in v) and any('「채권」 섹션이 0개' in x for x in v), v


def test_c2_extra_table_in_market_section_blocks(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><table><tr><th>상품</th><th>종가</th></tr>'
                                    '<tr><td>2Y</td><td>9.999%</td></tr></table>')
    assert any('지도에 없는 표' in x for x in run(bad, data).violations)


def test_c3_header_paren_must_be_date_or_unit(post, data):
    bad = sub(post, '<th>종가(11월 5일)</th>', '<th>종가(11월 6일 기준)</th>')
    assert any('괄호' in x for x in run(bad, data).violations)


def test_c3_colspan_blocks(post, data):
    bad = sub(post, '<th>종가(11월 5일)</th>', '<th colspan="2">종가(11월 5일)</th>')
    assert any('colspan' in x for x in run(bad, data).violations)


@pytest.mark.parametrize('title', ['섹터 기간별 수익률', '트렌드 유닛 점검'])
def test_c4_prose_in_delegated_section_is_not_delegated(post, data, title):
    base = run(post, data)
    bad = sub(post, f'<h2>{title}</h2>', f'<h2>{title}</h2><p>나스닥은 99.99% 올랐다.</p>')
    r = run(bad, data)
    assert r.delegated == base.delegated
    assert any('99.99' in x for x in r.violations), r.violations


def test_c5_yield_percent_binds_close_only():
    m = {'report_date': '2026-11-05', 'yields': {'10Y': {'level': 4.0, 'week_ago': 5.0, 'bp': 1.0}}}
    html = '<html><body><section><h2>채권</h2><p>10Y 5.0%다.</p></section></body></html>'
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert any('5.0' in x for x in r.violations)


def test_c6_alt_and_meta_attribute_order(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><img alt="S&amp;P는 9.99% 내렸다.">')
    assert any('9.99' in x for x in run(bad, data).violations)
    bad = sub(post, '<meta name="description" content="', '<meta content="S&amp;P는 9.98% 내렸다. " name="x" ')
    bad = bad.replace('name="x" ', 'name="description" ', 1)
    assert any('9.98' in x for x in run(bad, data).violations)


def test_c7_summary_of_closed_details_is_visible(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><details><summary>S&amp;P는 9.99% 내렸다.</summary>'
                                    '<p>접힌 글 1.23%</p></details>')
    r = run(bad, data)
    assert any('9.99' in x for x in r.violations)
    assert r.excluded == run(post, data).excluded + 1


def test_c9_failed_rows_and_header_numbers_are_counted(post, data):
    base = run(post, data)
    bad = sub(post, '<td data-label="지수">나스닥</td>', '<td data-label="지수">가짜</td>')
    r = run(bad, data)
    assert r.tokens_seen == base.tokens_seen and r.independent == r.tokens_seen


def test_independent_count_matches_on_published_post(post, data):
    r = run(post, data)
    assert r.independent == r.tokens_seen


# ── codex 구현 재검토(2차) 재현 ─────────────────────────────────────────

def test_r1_spf_val_class_on_prose_is_not_delegated(post, data):
    base = run(post, data)
    bad = sub(post, '<h2>섹터 기간별 수익률</h2>',
              '<h2>섹터 기간별 수익률</h2><p class="spf-val">나스닥은 99.99% 올랐다.</p>')
    r = run(bad, data)
    assert r.delegated == base.delegated and any('99.99' in x for x in r.violations)


def test_r1_sector_values_are_rechecked(post, data):
    r = run(post, data)
    assert r.delegated_by.get('check_sector_perf') == 55       # 11 업종 × 5 기간


def test_r2_forecast_cell_with_actual_label_is_not_delegated(post, data):
    base = run(post, data)
    i = post.index('data-indicator="JOLTS Job Openings"')
    j = post.index('<td data-label="Forecast">—</td>', i)
    bad = post[:j] + '<td data-label="Actual">99.99%</td>' + post[j + len('<td data-label="Forecast">—</td>'):]
    r = run(bad, data)
    assert r.delegated == base.delegated
    assert r.unverified == base.unverified + 1


def test_r3_svg_number_blocks(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><svg><text>나스닥은 99.99% 올랐다.</text></svg>')
    assert any('SVG' in x for x in run(bad, data).violations)


def test_r4_hidden_details_is_hidden_not_excluded(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><details hidden><summary>제목</summary><p>10Y 99.99%</p></details>')
    assert any('숨긴' in x for x in run(bad, data).violations)


def test_r7_nested_closed_details_inside_summary(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><details><summary>요약 <details><summary>S&amp;P는 9.99% '
                                    '내렸다.</summary>속</details></summary>본문</details>')
    assert any('9.99' in x for x in run(bad, data).violations)


def test_independent_count_sees_raw_text(post, data):
    r = run(post, data)
    assert r.independent == r.tokens_seen


# ── codex 구현 3차 재현 ─────────────────────────────────────────────────

def test_c3r1_duplicate_actual_header_is_not_delegated(post, data):
    base = run(post, data)
    i = post.index('data-indicator="JOLTS Job Openings"')
    h = post.rfind('<th>Forecast</th>', 0, i)
    bad = post[:h] + '<th>Actual</th>' + post[h + len('<th>Forecast</th>'):]
    j = bad.index('<td data-label="Forecast">—</td>', bad.index('data-indicator="JOLTS Job Openings"'))
    bad = bad[:j] + '<td data-label="Actual">99.99%</td>' + bad[j + len('<td data-label="Forecast">—</td>'):]
    assert run(bad, data).delegated == base.delegated


@pytest.mark.parametrize('sentence', ['10Y 5.0%였다.', '10Y 5.0%가 될 수 있다.', '10Y가 5.0%라면 부담이다.'])
def test_c3r2_past_or_possible_is_unverified(sentence):
    m = {'report_date': '2026-11-05', 'yields': {'10Y': {'level': 4.0, 'week_ago': 4.1, 'bp': 1.0}}}
    html = f'<html><body><section><h2>채권</h2><p>{sentence}</p></section></body></html>'
    r = N.audit(html, {'market_data': m}, prose='block', tables=False)
    assert r.violations == [] and r.unverified == 1


def test_c4r1_header_normalization_bypass(post, data):
    # 첫 Actual 을 「Act ual」로(게이트는 공백을 지우고 여전히 첫 열로 읽는다), Forecast 를 Actual 로
    base = run(post, data)
    i = post.index('data-indicator="JOLTS Job Openings"')
    a = post.rfind('<th>Actual</th>', 0, i)
    bad = post[:a] + '<th>Act ual</th>' + post[a + len('<th>Actual</th>'):]
    h = bad.rfind('<th>Forecast</th>', 0, bad.index('data-indicator="JOLTS Job Openings"'))
    bad = bad[:h] + '<th>Actual</th>' + bad[h + len('<th>Forecast</th>'):]
    j = bad.index('<td data-label="Forecast">—</td>', bad.index('data-indicator="JOLTS Job Openings"'))
    bad = bad[:j] + '<td data-label="Actual">99.99%</td>' + bad[j + len('<td data-label="Forecast">—</td>'):]
    assert run(bad, data).delegated == base.delegated


def test_c5r1_extra_number_in_macro_actual_cell_is_not_delegated(post, data):
    base = run(post, data)
    bad = sub(post, '<td data-label="Actual" class="sc-up">7,523K</td>',
              '<td data-label="Actual" class="sc-up">7,523K / 99.99%</td>')
    r = run(bad, data)
    # 수치가 둘인 칸은 위임하지 않는다 — 원래 7,523K 까지 칸째 미검증(6차에서 「첫 수치만」을 버렸다)
    assert r.delegated == base.delegated - 1 and r.unverified == base.unverified + 2


@pytest.mark.parametrize('cell', ['7,523K<br>99.99%', '(99.99%) 7,523K', '7523K / 99.99%',
                                  '7,523K / 99K', '7,523K / 999M', '7,523K / -99B', '− 7,523K', '- 7,523K'])
def test_c6_macro_cell_delegated_only_when_single_clean_number(post, data, cell):
    base = run(post, data)
    bad = sub(post, '<td data-label="Actual" class="sc-up">7,523K</td>',
              f'<td data-label="Actual" class="sc-up">{cell}</td>')
    r = run(bad, data)
    assert r.delegated == base.delegated - 1       # 원래 7,523K 하나가 위임에서 빠지고, 새 수치는 위임되지 않는다


def test_c9_small_m_b_are_counted(post, data):
    # 「9B」는 금액이다 — 이름(3M)과 글자로 가를 수 없어 둘 다 센다
    assert [t.raw for t in N.tokens('9B 3M')] == ['9B', '3M']
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><span hidden>9B</span>')
    assert any('숨긴' in x for x in run(bad, data).violations)


def test_c10_number_right_after_hangul_is_counted(post, data):
    assert [t.raw for t in N.tokens('약9B 매출9.5% 러셀2000은')] == ['9B', '9.5%']
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><span hidden>약9B</span>')
    assert any('숨긴' in x for x in run(bad, data).violations)


@pytest.mark.parametrize('text,value', [('.5%', 0.5), ('-.5%', -0.5), ('９９．９９％', 99.99), ('1，234%', 1234)])
def test_c11_leading_dot_and_fullwidth(text, value):
    toks = N.tokens(text)
    assert len(toks) == 1 and toks[0].value == value


def test_c11_hidden_leading_dot_blocks(post, data):
    bad = sub(post, '<h2>채권</h2>', '<h2>채권</h2><span hidden>.5%</span>')
    assert any('숨긴' in x for x in run(bad, data).violations)


def test_c12_fullwidth_table_cell_same_value_passes(post, data):
    bad = sub(post, '<td data-label="종가">4.477%</td>', '<td data-label="종가">４．４７７％</td>')
    assert run(bad, data).violations == []


def test_c12_period_then_digit_is_not_a_decimal():
    assert [(t.raw, t.value) for t in N.tokens('상승했다.5% 올랐다. 4.5% 와 .5%')] == \
        [('5%', 5.0), ('4.5%', 4.5), ('.5%', 0.5)]
