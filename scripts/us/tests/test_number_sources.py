"""숫자 출처 검사(2026-11-20) — 숫자열·수량 문법, 배타 칸, 표식 경계, 칸 상태, 기사 목록, 수정 이력, 불변식."""
import copy
import json
import os
import subprocess
import sys

import pytest

from common import article_numbers as AN
from common import numsrc as S
from us import number_audit as N
from us import number_sources as U

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(SCRIPTS)
FIX = os.path.join(HERE, 'fixtures', 'number_audit', '2026-11-05')
D = '2026-11-18'

MD = {'report_date': D, 'complete': True, 'missing': [],
      'indices': {'S&P 500': {'last': 7323.6298828125, 'chg': -16.9, 'pct': -0.2302, 'date': D},
                  'Nasdaq': {'last': 24429.88, 'chg': 101.5, 'pct': 0.4172, 'date': D}},
      'commodities': {'WTI': {'last': 81.88, 'prev': 84.39, 'chg': -2.51, 'pct': -2.974, 'date': D, 'prev_date': '2026-11-17',
                              'basis': 'close_1600_et'},
                      'Brent': {'last': 88.76, 'prev': 90.15, 'chg': -1.39, 'pct': -1.542, 'date': D,
                                'prev_date': '2026-11-17', 'basis': 'close_1600_et'}},
      'yields': {'10Y': {'level': 5.066, 'bp': -4.3, 'date': D, 'week_ago': 4.983, 'week_ago_date': '2026-11-10'},
                 '2Y': {'level': 4.8, 'bp': -0.6, 'date': D, 'week_ago': 4.727, 'week_ago_date': '2026-11-10'}},
      'sectors': {'Energy': {'last': 61.29, 'chg': -2.07, 'pct': -3.267, 'date': D},
                  'Technology': {'last': 163.81, 'chg': 0.55, 'pct': 0.337, 'date': D}},
      'spread_2s10s_bp': 26.6}
MM = {'report_date': D, 'book_state': 'ok', 'growth_score': 0.225,
      'indicators': [{'name': 'Initial Jobless Claims', 'units': '', 'actual': 200000.0, 'previous': 191000.0}]}
EI = {'indicators': [{'name': 'Initial Jobless Claims', 'actual': 200000.0}]}


def page(body, url='posts', date=D, title='제목'):
    return (f'<html><head><link rel="canonical" href="https://fdo2a.github.io/{url}/{date}.html">'
            f'<title>{title}</title></head><body data-register="da"><main>{body}</main></body></html>')


@pytest.fixture()
def wd(tmp_path):
    d = tmp_path / 'w'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps(MD), encoding='utf-8')
    (d / 'macro_metrics.json').write_text(json.dumps(MM), encoding='utf-8')
    (d / 'econ_indicators.json').write_text(json.dumps(EI), encoding='utf-8')
    return d


def run(wd, body, market='us', first=None, ledger=(), **kw):
    inp = U.Inputs(market, D, str(wd), REPO, ledger=list(ledger), **kw)
    return U.result(inp, page(body, 'posts' if market == 'us' else 'news'), first)


def items(wd, body, market='us'):
    inp = U.Inputs(market, D, str(wd), REPO, ledger=[])
    return U.classify(inp, page(body, 'posts' if market == 'us' else 'news'))[1]


def one(wd, body, market='us'):
    got = [it for it in items(wd, body, market) if it.where == 'body' and not it.q.code]
    assert len(got) == 1, [(i.q.raw, i.cls, i.why) for i in got]
    return got[0].cls, got[0].why


# ── 문법 ──

@pytest.mark.parametrize('text,raw,value,unit', [
    ('2억8200만달러', '2억8200만달러', 282e6, '달러'),
    ('265억 3천만 달러', '265억 3천만 달러', 26.53e9, '달러'),
    ('80만 3000원', '80만 3000원', 803000.0, '원'),
    ('-0.5%', '-0.5%', -0.5, '%'),
    ('$5.2B', '$5.2B', 5.2e9, '달러'),
    ('1,234.5포인트', '1,234.5포인트', 1234.5, 'p'),
])
def test_quantity_values(text, raw, value, unit):
    q = [x for x in S.quantities(text) if not x.code]
    assert len(q) == 1 and q[0].raw == raw and q[0].value == pytest.approx(value) and q[0].unit == unit


def test_leading_dot_decimal_reads_half_percent():
    q = [x for x in S.quantities('금리 차는 .5% 였다') if not x.code]
    assert q[0].value == pytest.approx(0.5) and q[0].raw == '.5%' and q[0].lead_dot
    # 한글+마침표 뒤는 문장 끝이다 — 「했다.5%」의 5% 는 5%(us/number_audit 규칙 그대로)
    q = [x for x in S.quantities('올랐다.5% 가 넘는') if not x.code]
    assert q[0].value == pytest.approx(5.0) and q[0].raw == '5%'


def test_range_shares_unit_and_counts_each_run():
    qs = S.quantities('3~6개월')
    assert [q.unit for q in qs] == ['개월', '개월'] and qs[0].unit_inherited
    assert len(S.runs('3~6개월')) == 2


def test_every_old_token_inside_one_quantity():
    """기존 토크나이저 구간은 모두 한 수량 안에 든다(_TOK 는 바꾸지 않는다)."""
    with open(os.path.join(FIX, 'post.html'), encoding='utf-8') as fh:
        html = fh.read()
    doc = N._Stream(html)
    for b in S.blocks_of(doc.stream):
        qs = S.quantities(b.text, U.fixed_terms())
        for t in N.tokens(b.text):
            inside = [q for q in qs if q.start <= t.start and t.end <= q.end]
            # 날짜 가림(_MASKS) 뒤 토큰만 있다 — 날짜·이름 X-코드 안에 드는 것도 「한 수량 안」이다
            assert len(inside) == 1, (t.raw, b.text[max(0, t.start - 20):t.end + 10])


def test_codes_are_excluded():
    qs = S.quantities('11월 18일 13:30 10년물 2s10s CLF27 4분기 2029년', U.fixed_terms())
    assert all(q.code for q in qs)


# ── 칸 ──

def test_data_ref_match_and_mismatch(wd):
    got = [(i.q.raw, i.cls) for i in items(wd, '<p>S&amp;P 500은 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸다.</p>')]
    assert got == [('S&P 500', 'excluded'), ('-0.23%', 'data')]
    # S&P 500 은 고정 이름 — 그 숫자열은 X 다. 확인할 값은 -0.23% 하나
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">-0.24%</span> 내렸다.</p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">+0.23%</span> 내렸다.</p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">0.23%p</span> 내렸다.</p>') == ('unknown', '자료와 다름')
    # 부호 있는 음수 칸을 부호 없이 — |abs 를 달아야 한다
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">0.23%</span> 내렸다.</p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct|abs">0.23%</span> 내렸다.</p>')[0] == 'data'


def test_level_and_unknown_cell(wd):
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last|lvl">7,300선</span>에 있다.</p>')[0] == 'level'   # 어림선은 따로 센다(11/21)
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last|lvl">7,500선</span>에 있다.</p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.foo">7,300</span>이다.</p>') == ('unknown', '칸 없음')
    assert one(wd, '<p>지수는 <span data-ref="zz:indices.SP500.last">7,323.63</span>이다.</p>') == ('unknown', '칸 없음')


def _bad(wd, mutate, name='market_data.json'):
    d = copy.deepcopy(MD if name == 'market_data.json' else MM)
    mutate(d)
    (wd / name).write_text(json.dumps(d), encoding='utf-8')


@pytest.mark.parametrize('mutate,name,ref,text', [
    (lambda d: d.update(complete=False), 'market_data.json', 'md:indices.SP500.pct', '-0.23%'),
    (lambda d: d.update(missing=['indices/S&P 500']), 'market_data.json', 'md:indices.SP500.pct', '-0.23%'),
    (lambda d: d.update(book_state='stale'), 'macro_metrics.json', 'mm:growth_score', '0.225'),
    (lambda d: d.pop('complete'), 'market_data.json', 'md:indices.SP500.pct', '-0.23%'),
    (lambda d: d.update(complete='true'), 'market_data.json', 'md:indices.SP500.pct', '-0.23%'),
    (lambda d: None, 'market_data.json', 'ei:indicators[InitialJoblessClaims].actual', '200000'),
    (lambda d: d['commodities']['WTI'].update(basis='daily'), 'market_data.json', 'md:commodities.WTI.last', '81.88달러'),
])
def test_invalid_state_is_unknown_even_when_value_matches(wd, mutate, name, ref, text):
    _bad(wd, mutate, name)
    assert one(wd, f'<p>값은 <span data-ref="{ref}">{text}</span>였다.</p>') == ('unknown', '칸 무효')


def test_stale_counts_as_data_but_is_counted(wd):
    r = run(wd, '<p>2년물 1주 전은 <span data-ref="md:yields.2Y.week_ago">4.727%</span>였다.</p>')
    assert r['counts']['data'] == 1 and r['detail']['stale_refs'] == 1


def test_dv_same_group_same_field_and_two_dates(wd):
    assert one(wd, '<p>격차는 <span data-ref="dv:diff(md:commodities.Brent.last,md:commodities.WTI.last)">6.88달러</span>다.'
                   '</p>')[0] == 'data'
    assert one(wd, '<p>낙폭은 <span data-ref="dv:diff(md:commodities.WTI.last,md:commodities.WTI.prev)">-2.51달러</span>다.'
                   '</p>')[0] == 'data'
    # 다른 필드끼리(종가 − 등락률)는 계산하지 않는다
    assert one(wd, '<p>값은 <span data-ref="dv:diff(md:commodities.WTI.last,md:commodities.Brent.pct)">83.42</span>다.</p>') \
        == ('unknown', '칸 없음')
    # 이력 연산은 상태 칸이 없어 받지 않는다(설계 §3.1)
    assert one(wd, '<p>값은 <span data-ref="dv:ret(SP500,2026-11-01,2026-11-18)">1.2%</span>다.</p>') == ('unknown', '칸 무효')
    # 깊이 1
    assert one(wd, '<p>값은 <span data-ref="dv:diff(dv:diff(md:a,md:b),md:c)">1</span>다.</p>')[1] == '칸 없음'
    # 금리 수준 차는 %p 와 bp 둘 다
    assert one(wd, '<p>2s10s 는 <span data-ref="dv:diff(md:yields.10Y.level,md:yields.2Y.level)">26.6bp</span>다.</p>')[0] \
        == 'data'


def test_rank(wd):
    assert one(wd, '<p>기술은 <span data-ref="dv:rank(md:sectors,pct,Technology)">1위</span>였다.</p>')[0] == 'data'
    assert one(wd, '<p>기술은 <span data-ref="dv:rank(md:sectors,pct,Technology)">2위</span>였다.</p>')[0] == 'unknown'


# ── 표식 문법 ──

def test_marker_boundary_split_decimal(wd):
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last">7,323</span>.63이다.</p>') == ('unknown', '표식 오류')
    # 앞 0 생략 소수를 쪼갠 것 — 보이는 수는 0.5% 다
    assert one(wd, '<p>차이는 .<span data-ref="md:indices.Nasdaq.pct">5%</span> 다.</p>') == ('unknown', '표식 오류')
    # 「했다.」 뒤 5% 는 쪼갠 소수가 아니다 — 표식은 수량 전체를 싼다(값이 달라 「자료와 다름」)
    assert one(wd, '<p>올랐다.<span data-ref="md:indices.Nasdaq.pct">5%</span> 다.</p>') == ('unknown', '자료와 다름')


def test_marker_unit_outside_two_inside_nested(wd):
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23</span>% 내렸다.</p>') == ('unknown', '표식 오류')
    got = items(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23% · 0.42%</span>였다.</p>')
    assert [i.why for i in got if i.where == 'body'] == ['표식 오류', '표식 오류']
    assert one(wd, '<p><span data-ref="md:indices.SP500.pct"><span data-ref="md:indices.SP500.pct">-0.23%</span></span></p>')\
        == ('unknown', '표식 오류')


def test_empty_marker_counted(wd):
    r = run(wd, '<p>지수 <span data-ref="md:indices.SP500.pct">내림</span>.</p>')
    assert r['detail']['marker_empty'] == 1


def test_enum_declaration(wd):
    assert one(wd, '<p>지수 <span data-nx="enum">6종</span>을 본다.</p>') == ('excluded', 'enum')
    assert one(wd, '<p>지수 <span data-nx="enum">6.5%</span>를 본다.</p>') == ('unknown', '선언 무효')
    assert one(wd, '<p>지수 <span data-nx="enum">1,200개</span>를 본다.</p>') == ('unknown', '선언 무효')
    assert one(wd, '<p>지수 <span data-nx="level">7,300</span>을 본다.</p>') == ('unknown', '선언 무효')


def test_zones_and_code_blocks(wd):
    assert one(wd, '<section data-contested="x"><p>주장은 5.5%였다.</p></section>') == ('excluded', 'zone_contested')
    assert one(wd, '<section data-editor-note="1"><p>내 생각에 5.5%다.</p></section>') == ('excluded', 'zone_note')
    assert one(wd, '<div data-release="cpi"><p>근원 0.3% 올랐다.</p></div>') == ('unknown', '코드 블록(표식 없음)')
    assert one(wd, '<p>그냥 0.3% 올랐다.</p>') == ('unknown', '표식 없음')


def test_title_inherits_only_from_checked_body(wd):
    r = run(wd, '<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸다.</p>')
    assert r['counts']['data'] == 1
    inp = U.Inputs('us', D, str(wd), REPO, ledger=[])
    got = U.classify(inp, page('<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸다.</p>',
                               title='S&amp;P -0.23%, 나스닥 9.9%'))[1]
    t = [i for i in got if i.where == 'title']
    assert [(i.q.raw, i.cls) for i in t if not i.q.code] == [('-0.23%', 'data'), ('9.9%', 'unknown')]


# ── 표 대조(T) ──

def _fix():
    with open(os.path.join(FIX, 'post.html'), encoding='utf-8') as fh:
        html = fh.read()
    data = {}
    for k in ('market_data', 'econ_indicators', 'macro_metrics', 'fund_board'):
        with open(os.path.join(FIX, f'{k}.json'), encoding='utf-8') as fh:
            data[k] = json.load(fh)
    return html, data


def test_trace_does_not_change_verdicts():
    html, data = _fix()
    a = N.audit(html, copy.deepcopy(data))
    trace = {}
    b = N.audit(html, copy.deepcopy(data), trace=trace)
    assert (a.violations, a.warnings, a.summary(), a.unverified_by, a.delegated_by) == \
           (b.violations, b.warnings, b.summary(), b.unverified_by, b.delegated_by)
    assert 'T' in set(trace['kinds'].values())


def test_wrong_table_cell_is_not_T():
    html, data = _fix()
    bad = html.replace('>4.477%<', '>4.478%<', 1)
    assert bad != html
    trace = {}
    N.audit(bad, data, trace=trace)
    doc = trace['doc']
    hit = [i for i, it in enumerate(doc.stream) if it is not None and '4.478%' in it[0]]
    assert hit and trace['kinds'][hit[0]] == 'owned_bad'


# ── 기사 · 텔레그램 ──

def _news(wd, items_):
    (wd / 'news').mkdir(exist_ok=True)
    (wd / 'news' / f'{D}.json').write_text(json.dumps({'report_date': D, 'items': [
        {'guid': g, 'summary_ko': s} for g, s, _ in items_]}), encoding='utf-8')
    AN.write_day(AN.numbers_path(str(wd), 'news', D), D, [(g, s, 'T', b) for g, s, b in items_])


def test_article_list_only_that_article(wd):
    _news(wd, [('g1', '매출이 6.5% 늘었다.', 'Sales rose 6.5%.'), ('g2', '순익이 9.1% 늘었다.', 'Profit rose 9.1%.')])
    blk = ('<div class="news-item" data-news="g1"><p class="news-head">매출 6.5% 증가<span class="sub">AP · 11월 18일</span></p>'
           '<p data-summary="g1">매출이 6.5% 늘었다. 주가는 2.89% 내렸다.</p></div>'
           '<p>산업 쪽에서 순익 <span data-src="news:g2">9.1%</span> 증가, 다른 기사 숫자 <span data-src="news:g1">9.1%</span>.</p>')
    got = [(i.q.raw, i.cls, i.why) for i in items(wd, blk, 'us-news') if not i.q.code]
    assert got == [('6.5%', 'article', ''), ('6.5%', 'article', ''), ('2.89%', 'unknown', '표식 없음'),
                   ('9.1%', 'article', ''), ('9.1%', 'unknown', '기사 목록에 없음')]


def test_article_list_unusable_when_summary_changed(wd):
    _news(wd, [('g1', '매출이 6.5% 늘었다.', 'Sales rose 6.5%.')])
    (wd / 'news' / f'{D}.json').write_text(json.dumps({'items': [{'guid': 'g1', 'summary_ko': '매출이 6.5% 늘었다고 한다.'}]}),
                                          encoding='utf-8')
    assert one(wd, '<div data-news="g1"><p>매출 <span data-src="news">6.5%</span></p></div>', 'us-news') == \
        ('unknown', '목록 없음')


def test_news_marker_outside_block_is_error(wd):
    _news(wd, [('g1', '6.5% 늘었다.', 'up 6.5%')])
    assert one(wd, '<p>매출 <span data-src="news">6.5%</span></p>', 'us-news') == ('unknown', '표식 오류')


def test_telegram_list(wd):
    (wd / 'telegram.json').write_text(json.dumps({'items': [{'id': 'ch/1', 'summary_ko': '2년물이 5%에 이를 수 있다.'}]}),
                                      encoding='utf-8')
    AN.write_day(AN.numbers_path(str(wd), 'telegram', D), D, [('ch/1', '2년물이 5%에 이를 수 있다.', '', '2년물 5% 전망')])
    assert one(wd, '<p><span data-tg="ch/1">BofA 는 2년물이 5%에 이를 수 있다고 봤다.</span></p>')[0] == 'telegram'
    assert one(wd, '<p><span data-tg="ch/1">BofA 는 2년물이 6%에 이를 수 있다고 봤다.</span></p>') == \
        ('unknown', '기사 목록에 없음')


# ── 불변식 ──

def test_sums_hold_on_fixture(wd):
    html, _ = _fix()
    r = run(wd, '<p>0.3% 올랐다.</p>')
    for k in ('counts', 'runs'):
        assert S.check_sums(r[k])


def test_tally_raises_on_broken_class():
    q = S.quantities('1%')[0]
    it = S.Item(q, 'nonsense')
    with pytest.raises(KeyError):
        S.tally([it])


def test_check_sums_rejects_bad_shapes():
    good = {**{c: 0 for c in S.CLASSES}, 'unknown': 2, 'total': 2}
    assert S.check_sums(good)
    assert not S.check_sums(dict(good, total=3))
    assert not S.check_sums(dict(good, unknown=True))
    assert not S.check_sums(dict(good, data=-1, unknown=3))


# ── 수정 이력(문장 단위) ──

def hist(wd, first_body, final_body, market='us'):
    url = 'posts' if market == 'us' else 'news'
    return run(wd, final_body, market, first=page(first_body, url))['history']


def test_history_paragraph_deleted_and_same_number_readded_elsewhere(wd):
    h = hist(wd, '<p>에너지는 5% 뛰었다.</p><p>둘째 문단은 그대로다.</p>',
             '<p>둘째 문단은 그대로다. 유틸리티도 <span data-ref="md:sectors.Energy.pct">5%</span> 바뀌었다.</p>')
    assert h['first_unknown'] == 1 and h['gone'] == 1 and h['fixed'] == 0


def test_history_same_paragraph_numbers_reshuffled(wd):
    h = hist(wd, '<p>A 업종 5%, B 업종 5% 같은 폭으로 움직였고 긴 공통 문장이 그대로 이어진다.</p>',
             '<p>B 업종 5%, C 업종 5% 같은 폭으로 움직였고 긴 공통 문장이 그대로 이어진다.</p>')
    assert h['first_unknown'] == 2 and h['gone'] == 2 and h['still'] == 0     # 「변경 없음」이 아니다


def test_history_fixed_by_marker_and_value(wd):
    h = hist(wd, '<p>지수는 0.24% 내렸다.</p><p>나스닥은 0.4% 올랐다.</p>',
             '<p>지수는 <span data-ref="md:indices.SP500.pct|abs">0.23%</span> 내렸다.</p><p>나스닥은 0.4% 올랐다.</p>')
    assert (h['first_unknown'], h['fixed'], h['still'], h['gone']) == (2, 1, 1, 0)


def test_history_duplicate_sentence_is_ambiguous(wd):
    h = hist(wd, '<p>0.3% 올랐다.</p><p>0.3% 올랐다.</p>', '<p>0.3% 올랐다.</p>')
    assert h['ambiguous'] == 2 and h['first_unknown'] == 2


def test_history_missing_or_other_post(wd):
    assert run(wd, '<p>0.3% 올랐다.</p>')['history'] == 'unverifiable'
    inp = U.Inputs('us', D, str(wd), REPO, ledger=[])
    other = page('<p>0.3% 올랐다.</p>', date='2026-11-17')
    r = U.result(inp, page('<p>0.3% 올랐다.</p>'), other)
    assert r['history'] == 'unverifiable' and '날짜' in r['history_why']
    news_first = page('<p>0.3% 올랐다.</p>', url='news')
    assert U.result(inp, page('<p>0.3% 올랐다.</p>'), news_first)['history'] == 'unverifiable'


def test_history_record_has_no_sentence_text(wd):
    h = hist(wd, '<p>비공개 초안 문장 비밀단어 5% 였다.</p>', '<p>다른 문장.</p>')
    assert '비밀단어' not in json.dumps(h, ensure_ascii=False)
    assert S.valid_history(h)


# ── CLI ──

def _cli(*args):
    return subprocess.run([sys.executable, os.path.join(SCRIPTS, 'check_number_sources.py'), *args],
                          capture_output=True, text=True)


def test_cli_json_and_exit_codes(wd, tmp_path):
    h = tmp_path / 'p.html'
    h.write_text(page('<p>지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸다.</p>'), encoding='utf-8')
    p = _cli('--market', 'us', '--date', D, '--html', str(h), '--datadir', str(wd), '--repo', REPO, '--json',
             '--effective', '2026-01-01')
    assert p.returncode == 0, p.stderr
    obj = json.loads(p.stdout.strip().splitlines()[-1])
    assert obj['violations'] == [] and S.check_sums(obj['sources']['counts'])
    assert obj['sources']['history'] == 'unverifiable'
    p = _cli('--market', 'us', '--date', D, '--html', str(h), '--datadir', str(wd), '--repo', REPO, '--json')
    assert p.returncode == 0 and json.loads(p.stdout)['skipped'] is True        # 적용일 전(자리표시 상수)
    (wd / 'market_data.json').write_text(json.dumps(dict(MD, report_date='2026-11-17')), encoding='utf-8')
    p = _cli('--market', 'us', '--date', D, '--html', str(h), '--datadir', str(wd), '--repo', REPO, '--json',
             '--effective', '2026-01-01')
    assert p.returncode == 2


# ── 자체 점검(구현 뒤) ──

def test_sign_after_hangul_is_a_sign_like_old_tokenizer(wd):
    q = [x for x in S.quantities('나스닥-0.42%') if not x.code][0]
    assert q.sign == '-' and q.value == pytest.approx(-0.42)
    # +0.42 칸에 화면상 음수를 달면 자료와 다름
    assert one(wd, '<p>나스닥<span data-ref="md:indices.Nasdaq.pct">-0.42%</span></p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>나스닥<span data-ref="md:indices.Nasdaq.pct">+0.42%</span></p>')[0] == 'data'
    # 음수 칸에 화면상 양수 + |abs 는 부호가 인쇄됐으므로 다름
    assert one(wd, '<p>지수<span data-ref="md:indices.SP500.pct|abs">+0.23%</span></p>') == ('unknown', '자료와 다름')
    assert [x.sign for x in S.quantities('3-6개월')] == ['', '']
    assert [x.sign for x in S.quantities('A-1')] == ['']


def test_run_recount_catches_a_dropped_run(wd, monkeypatch):
    real = S.quantities

    def drop(text, terms=()):
        qs = real(text, terms)
        return qs[1:] if len(qs) > 1 else qs
    monkeypatch.setattr(S, 'quantities', drop)
    with pytest.raises(S.InvariantError):
        run(wd, '<p>0.3% 올랐고 0.4% 내렸다.</p>')


def test_history_keeps_names_literal(wd):
    h = hist(wd, '<p>S&amp;P 500은 5% 내렸다.</p>', '<p>러셀 2000은 <span data-ref="md:indices.SP500.pct|abs">5%</span> 내렸다.</p>')
    assert h['gone'] == 1 and h['fixed'] == 0


def test_inheritance_boundary_is_marker_error(wd):
    (wd / 'telegram.json').write_text(json.dumps({'items': [{'id': 'ch/1', 'summary_ko': '5%에 이른다.'}]}), encoding='utf-8')
    AN.write_day(AN.numbers_path(str(wd), 'telegram', D), D, [('ch/1', '5%에 이른다.', '', '5% 전망')])
    assert one(wd, '<p><span data-tg="ch/1">금리는 5</span>%에 이른다.</p>') == ('unknown', '표식 오류')


def _fixture_wd(tmp_path):
    import shutil
    d = tmp_path / 'fx'
    d.mkdir()
    for n in os.listdir(FIX):
        if n.endswith('.json'):
            shutil.copy(os.path.join(FIX, n), d / n)
    return d


@pytest.mark.parametrize('ref', [
    'fb:units[semis].ret_3m', 'fb:risk.vix.level', 'fb:liquidity.net.level_bn',
    'md:indices.SP500.pct', 'md:yields.2Y.level', 'md:sectors.Energy.pct', 'md:spread_2s10s_bp',
])
def test_each_schema_branch_resolves_real_files(tmp_path, ref):
    from us import facts as FA
    d = _fixture_wd(tmp_path)
    md = json.load(open(d / 'market_data.json'))
    b = FA.Book(str(d), md['report_date'], [])
    f = b.resolve(ref)
    assert f.status in ('current', 'stale') and f.units, (ref, f)


def test_macro_metrics_branch(wd):
    # 11/05 고정 자료는 book_state·units 이전 꼴이라 무효·칸 없음이 맞다 — 지금 꼴(MM)로 본다
    assert one(wd, '<p>청구는 <span data-ref="mm:indicators[Initial Jobless Claims].actual">20만 건</span>이다.</p>')[0] == 'data'
    assert one(wd, '<p>점수 <span data-ref="mm:growth_score">0.225</span></p>')[0] == 'data'


def test_old_macro_metrics_shape_is_not_a_cell(tmp_path):
    from us import facts as FA
    d = _fixture_wd(tmp_path)
    b = FA.Book(str(d), '2026-11-05', [])
    assert b.resolve('mm:growth_score').status == 'invalid'          # book_state 가 없다
    with pytest.raises(FA.Miss):
        b.resolve('mm:indicators[Initial Jobless Claims].actual')     # units 가 없다


def test_auction_branch(tmp_path):
    from us import facts as FA
    au = {'ok': True, 'complete': True, 'report_date': D,
          'today': [{'date': D, 'key': 'nominal-20y', 'bid_to_cover': 2.63, 'indirect_pct': 60.2, 'offering_amt': 1.6e10,
                     'avg6': {'bid_to_cover': 2.63}}]}
    (tmp_path / 'auctions.json').write_text(json.dumps(au), encoding='utf-8')
    b = FA.Book(str(tmp_path), D, [])
    assert b.resolve('au:today[nominal-20y].bid_to_cover').status == 'current'
    assert b.resolve('au:today[nominal-20y].avg6.bid_to_cover').units == FA.RATIO
    f = b.resolve('au:today[nominal-20y].offering_amt')
    q = [x for x in S.quantities('160억 달러') if not x.code][0]
    assert U._shown_ok(q, f, set())
    (tmp_path / 'auctions.json').write_text(json.dumps(dict(au, complete=False)), encoding='utf-8')
    assert FA.Book(str(tmp_path), D, []).resolve('au:today[nominal-20y].bid_to_cover').status == 'invalid'


def test_markers_survive_publish_transforms(tmp_path):
    """발행 경로(apply_readability → apply_colors)를 지나도 표식이 남고 같은 칸으로 분류된다(설계 §8.5)."""
    html, _ = _fix()
    d = _fixture_wd(tmp_path)
    md = json.load(open(d / 'market_data.json'))
    rd = md['report_date']
    want = md['indices']['S&P 500']['pct']
    shown = f'{want:+.2f}%'
    p = tmp_path / f'{rd}.html'
    body = f'<p>지수는 <span data-ref="md:indices.SP500.pct">{shown}</span> 움직였다.</p>'
    p.write_text(html.replace('</main>', body + '</main>', 1) if '</main>' in html else html.replace('</body>', body + '</body>'),
                 encoding='utf-8')
    for tool in ('apply_readability.py', 'apply_colors.py'):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, tool), str(p)], capture_output=True, text=True)
        assert r.returncode in (0, 1), r.stderr
    out = p.read_text(encoding='utf-8')
    assert f'data-ref="md:indices.SP500.pct">{shown}</span>' in out
    inp = U.Inputs('us', rd, str(d), REPO, ledger=[])
    items_ = U.classify(inp, out)[1]
    got = [i for i in items_ if i.why == 'md:indices.SP500.pct']
    assert len(got) == 1 and got[0].cls == 'data'


# ── codex 구현 검토 1회 ──

def _t_cell_items(html_sub, level=None, raw='4.477'):
    html, data = _fix()
    bad = html.replace('>4.477%<', html_sub, 1)
    assert bad != html
    d = {k: v for k, v in data.items()}
    if level is not None:
        d['market_data']['yields']['2Y']['level'] = level
    inp = U.Inputs.__new__(U.Inputs)
    inp.market, inp.date, inp.datadir, inp.repo = 'us', data['market_data']['report_date'], FIX, REPO
    inp.terms, inp.news, inp.news_summary, inp.article, inp.telegram = U.fixed_terms(), None, {}, {}, {}
    inp.ledger, inp.cycle_arg, inp.data = [], None, d
    items_ = U.classify(inp, bad)[1]
    return [i for i in items_ if (raw in i.q.raw if raw == '4.477' else i.q.raw.strip() == raw)
            and i.sentence == '#']     # 표 칸(문장 속 같은 값은 뺀다)


def test_bad_marker_on_table_cell_is_not_table():
    # 표 대조가 맞은 칸이라도 없는 칸을 가리키는 표식은 U(#2·#3)
    got = _t_cell_items('><span data-ref="bad">4.477%</span><')
    assert [(i.cls, i.why) for i in got] == [('unknown', '칸 없음')]
    # 경계를 쪼갠 표식(#6)
    got = _t_cell_items('><span data-ref="md:yields.2Y.level">4.477</span>%<')
    assert [(i.cls, i.why) for i in got] == [('unknown', '표식 오류')]
    # 겹친 표식(#6)
    got = _t_cell_items('><span data-ref="md:yields.2Y.level"><span data-ref="md:yields.2Y.level">4.477%</span></span><')
    assert [(i.cls, i.why) for i in got] == [('unknown', '표식 오류')]


def test_valid_marker_on_table_cell_stays_table():
    got = _t_cell_items('><span data-ref="md:yields.2Y.level">4.477%</span><')
    assert [i.cls for i in got] == ['table']


def test_level_marker_on_table_cell_stays_level():
    # codex 구현 2회 #16 — 표 대조가 맞은 칸이라도 `|lvl` 표식이 맞으면 배타 칸 level 이다(「자료로 확인」에 섞지 않는다)
    sub = '><span data-ref="md:yields.2Y.level|lvl">4.5%</span><'
    got = _t_cell_items(sub, level=4.5, raw='4.5%')
    assert [(i.cls, i.why) for i in got] == [('level', 'md:yields.2Y.level')]
    # 표식이 틀리면 여전히 U, |lvl 없는 맞는 표식은 여전히 table
    got = _t_cell_items('><span data-ref="md:indices.SP500.last|lvl">4.5%</span><', level=4.5, raw='4.5%')
    assert [i.cls for i in got] == ['unknown']
    got = _t_cell_items('><span data-ref="md:yields.2Y.level">4.5%</span><', level=4.5, raw='4.5%')
    assert [i.cls for i in got] == ['table']


def test_rl_fields_are_schema_checked():
    from us import facts as FA
    ledger = [{'id': 'cycle', 'market': 'us', 'report_date': D, 'candidate_ids': ['r'], 'reviewed_ids': []},
              {'id': 'r', 'arbitrary': 5, 'event': {
                  'actual': {'value': 0.3, 'unit': '%', 'observed_at': f'{D}T13:30:00+00:00'},
                  'expectations': [{'value': 0.2, 'unit': 'furlongs', 'observed_at': f'{D}T10:00:00+00:00'},
                                   {'value': 0.25, 'unit': '%'}]}}]
    b = FA.Book('/none', D, ledger, 'cycle')
    with pytest.raises(FA.Miss) as e:
        b.resolve('rl:r.arbitrary')
    assert e.value.kind == '칸 없음'
    f = b.resolve('rl:r.event.actual.value')
    assert f.status == 'current' and f.units == frozenset({'%'})
    with pytest.raises(FA.Miss) as e:
        b.resolve('rl:r.event.expectations[0].value')              # 단위가 닫힌 표 밖
    assert e.value.kind == '칸 무효'
    with pytest.raises(FA.Miss) as e:
        b.resolve('rl:r.event.expectations[1].value')              # 관측 시각 없음
    assert e.value.kind == '칸 무효'


def test_gap_needs_an_explicit_threshold_field(wd):
    from us import facts as FA
    ledger = [{'id': 'cycle', 'market': 'us', 'report_date': D, 'candidate_ids': ['r'], 'reviewed_ids': []},
              {'id': 'r', 'event': {'actual': {'value': 0.1, 'unit': '%', 'observed_at': f'{D}T13:30:00+00:00'}}}]
    b = FA.Book(str(wd), D, ledger, 'cycle')
    with pytest.raises(FA.Miss) as e:
        b.resolve('dv:gap(md:indices.SP500.pct,rl:r.event.actual.value)')
    assert e.value.kind == '칸 없음'


def test_enum_rejects_scale_words(wd):
    for text in ('0천개', '3만개', '2K개'):
        q = [x for x in S.quantities(text) if not x.code][0]
        c = U.Classifier.__new__(U.Classifier)
        c.detail, c.declared = {'excluded_enum': 0}, []
        assert c._enum('enum', q) == ('unknown', '선언 무효'), text


def test_level_compares_sign(wd):
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last|lvl">-7,300선</span>이다.</p>') == ('unknown', '자료와 다름')
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last|lvl">7,300선</span>이다.</p>')[0] == 'level'
    # 음수 칸: 부호까지 같아야 한다
    assert one(wd, '<p>낙폭 <span data-ref="md:indices.SP500.chg|lvl">-17포인트</span></p>')[0] == 'level'
    assert one(wd, '<p>낙폭 <span data-ref="md:indices.SP500.chg|lvl">17포인트</span></p>') == ('unknown', '자료와 다름')


def test_cli_text_output_sums_with_level(wd, tmp_path):
    h = tmp_path / 'p.html'
    h.write_text(page('<p>지수는 <span data-ref="md:indices.SP500.last|lvl">7,300선</span>이고 0.3% 올랐다.</p>'),
                 encoding='utf-8')
    p = _cli('--market', 'us', '--date', D, '--html', str(h), '--datadir', str(wd), '--repo', REPO, '--effective', '2026-01-01')
    head = p.stdout.splitlines()[0]
    import re as _re
    total = int(_re.search(r'숫자 (\d+)개', head).group(1))
    parts = head.split('= ', 1)[1]
    parts = _re.sub(r'\(표 \d+·칸 \d+\)', '', parts)
    assert sum(int(x) for x in _re.findall(r' (\d+)(?= ·|$)', ' ' + parts)) == total and '어림선 1' in head


# ── 대조 못 한 숫자 전부(unknown_all, 2026-11-27 설계 v3 §H) — 출력만, 판정·건수·기존 unknown 은 그대로 ──

_UA_BODY = ('<p>그냥 0.3% 올랐고 1.5%는 모른다. 지수는 <span data-ref="md:indices.SP500.pct">-0.23%</span> 내렸고 2.5% 는 모른다.</p>'
            '<table><tr><td>3.1%</td><td>4.2%</td></tr></table><div data-release="cpi"><p>근원 0.4% 올랐다.</p></div>')


def test_unknown_all_every_unknown_with_full_sentence(wd):
    inp = U.Inputs('us', D, str(wd), REPO, ledger=[])
    r = U.result(inp, page(_UA_BODY, title='지수 9.9% 급락'), None)
    assert r['counts']['unknown'] == r['unknown_total'] == len(r['unknown_all']) == 7
    assert r['unknown_all'] == [
        {'n': '0.3%', 's': '그냥 0.3% 올랐고 1.5%는 모른다.', 'why': '표식 없음', 'w': 'body', 't': 0},
        {'n': '1.5%', 's': '그냥 0.3% 올랐고 1.5%는 모른다.', 'why': '표식 없음', 'w': 'body', 't': 0},
        {'n': '2.5%', 's': '지수는 -0.23% 내렸고 2.5% 는 모른다.', 'why': '표식 없음', 'w': 'body', 't': 0},
        {'n': '3.1%', 's': '3.1%', 'why': '코드 블록(표식 없음)', 'w': 'body', 't': 1},
        {'n': '4.2%', 's': '4.2%', 'why': '코드 블록(표식 없음)', 'w': 'body', 't': 1},
        {'n': '0.4%', 's': '근원 0.4% 올랐다.', 'why': '코드 블록(표식 없음)', 'w': 'body', 't': 1},
        {'n': '9.9%', 's': '지수 9.9% 급락', 'why': '표식 없음', 'w': 'title', 't': 0}]
    # 기존 칸은 이 변경 전과 같은 꼴 — 가린 조각·60개 상한(읽는 곳이 바뀌지 않는다)
    assert r['unknown'] == [
        {'text': '0.3% — 그냥 · 올랐고 ·는 모른다.', 'why': '표식 없음'},
        {'text': '1.5% — 그냥 · 올랐고 ·는 모른다.', 'why': '표식 없음'},
        {'text': '2.5% — 지수는 · 내렸고 · 는 모른다.', 'why': '표식 없음'},
        {'text': '3.1% — ·', 'why': '코드 블록(표식 없음)'}, {'text': '4.2% — ·', 'why': '코드 블록(표식 없음)'},
        {'text': '0.4% — 근원 · 올랐다.', 'why': '코드 블록(표식 없음)'}, {'text': '9.9%', 'why': '표식 없음'}]


def test_unknown_all_has_no_count_cap_and_clips_only_long_sentences(wd):
    body = ''.join(f'<p>값 {i}.5% 였다.</p>' for i in range(S.UNKNOWN_LIST + 15))
    body += '<p>긴 문장 ' + '가' * 400 + ' 7.7% 였다.</p>'
    r = run(wd, body)
    ua = r['unknown_all']
    assert len(r['unknown']) == S.UNKNOWN_LIST and len(ua) == r['counts']['unknown'] == S.UNKNOWN_LIST + 16
    assert [u['n'] for u in ua[:3]] == ['0.5%', '1.5%', '2.5%']             # 글 순서 — 배열 자리가 순번
    long = ua[-1]
    assert long['n'] == '7.7%' and len(long['s']) == S.UNKNOWN_ALL_LEN and long['s'].endswith('…')


_FIX_UNKNOWN_SHA = 'ef1de68c31500428'     # 이 변경 전(3fd9068b) 판이 11/05 고정 글에 낸 `unknown` 60개의 sha256 앞 16자
_FIX_REST_SHA = '150cfd33fde295e3'        # 같은 판의 결과 전체(unknown_all 칸 없음)


def test_fixture_unknown_unchanged_and_unknown_all_complete(tmp_path):
    import hashlib
    d = _fixture_wd(tmp_path)
    html, _ = _fix()
    r = U.result(U.Inputs('us', '2026-11-05', str(d), REPO, ledger=[]), html)
    ua = r.pop('unknown_all')
    assert hashlib.sha256(json.dumps(r['unknown'], ensure_ascii=False).encode()).hexdigest()[:16] == _FIX_UNKNOWN_SHA
    assert hashlib.sha256(json.dumps(r, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16] == _FIX_REST_SHA
    assert len(ua) == r['counts']['unknown'] == r['unknown_total'] == 372
    assert all(u['n'] in u['s'] for u in ua)                                # 숫자를 가리지 않은 문장
    assert all((u['t'] == 1) == (u['why'] == '코드 블록(표식 없음)') for u in ua)
    assert {u['w'] for u in ua} == {'body', 'meta', 'title'}


def test_cli_json_carries_unknown_all_exit_unchanged(wd, tmp_path):
    h = tmp_path / 'p.html'
    h.write_text(page(_UA_BODY), encoding='utf-8')
    p = _cli('--market', 'us', '--date', D, '--html', str(h), '--datadir', str(wd), '--repo', REPO, '--json',
             '--effective', '2026-01-01')
    assert p.returncode == 0, p.stderr
    o = json.loads(p.stdout)
    assert o['violations'] == [] and o['warnings'] == []
    assert len(o['sources']['unknown_all']) == o['sources']['counts']['unknown'] == 6
