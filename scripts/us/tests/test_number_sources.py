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
    assert one(wd, '<p>지수는 <span data-ref="md:indices.SP500.last|lvl">7,300선</span>에 있다.</p>')[0] == 'data'
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
