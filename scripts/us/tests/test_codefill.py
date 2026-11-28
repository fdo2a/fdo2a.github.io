"""숫자는 코드가 채운다 — US 일간 1차(2026-11-27): 한글 개수·센 값, 채우기, 막는 검사, 지운 숫자, 기록 fills.

실제 사고를 그대로 재현한 시험(발행 커밋 자료를 fixtures/codefill 에 옮겼다):
- 5832b595 — 11/04 「11개 업종 가운데 여덟이 1% 넘게 올랐지만」 → 발행 커밋 75ac3b25 자료로 count = 7.
- 4709cd46 — 11/17 발행본(34cabfc6)의 닛케이·항셍·상해·DAX·유로스톡스50 행은 11/16 관측(한 세션 묵은 종가).
"""
import json
import os

import pytest

from common import numsrc as S
from us import facts as F
from us import number_sources as U

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.dirname(os.path.dirname(HERE))
REPO = os.path.dirname(SCRIPTS)
FIX = os.path.join(HERE, 'fixtures', 'codefill')
ON = '2026-11-01'          # 막는 판을 켠 날(시험용 — 운영 값은 numsrc.FILL_EFFECTIVE)


def page(body, date, title='제목'):
    return (f'<html><head><link rel="canonical" href="https://fdo2a.github.io/posts/{date}.html">'
            f'<title>{title}</title></head><body data-register="da"><main>{body}</main></body></html>')


def wd_from(tmp_path, fixture):
    d = tmp_path / 'w'
    d.mkdir()
    with open(os.path.join(FIX, fixture), encoding='utf-8') as fh:
        md = json.load(fh)
    (d / 'market_data.json').write_text(json.dumps(md), encoding='utf-8')
    return d, md['report_date']


def classify(wd, date, body, on=True):
    inp = U.Inputs('us', date, str(wd), REPO, ledger=[], fill_effective=ON if on else '2099-12-31')
    return [it for it in U.classify(inp, page(body, date))[1] if it.where == 'body' and not it.q.code]


# ── 한글 개수 ──

@pytest.mark.parametrize('text,got', [
    ('11개 업종 가운데 여덟이 1% 넘게 올랐다', [('여덟', 8, '')]),
    ('넷플릭스와 둘러싼 논란', []),
    ('세 업종이 올랐고 두 종목을 샀다', [('세 업종', 3, '업종'), ('두 종목', 2, '종목')]),
    ('셋째 날이다', []),
    ('다섯 곳에서', [('다섯 곳', 5, '곳')]),
    ('열한 개', []),                 # 「한」 앞이 한글 — 1 로 읽지 않는다
    ('세계 경제', []),
    ('네 거래일째', []),             # 세는 말 뒤가 한글(째) — 차례다
    ('두 개월', []),
    ('세 가지 이유', [('세 가지', 3, '가지')]),
])
def test_korean_counts(text, got):
    assert [(q.raw, q.value, q.unit) for q in S.korean_quantities(text)] == got
    assert all(q.runs == [] and q.korean for q in S.korean_quantities(text))


def test_korean_counts_only_in_blocking_mode(tmp_path):
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    body = '<p>업종 가운데 여덟이 올랐다.</p>'
    assert [i.q.raw for i in classify(wd, d, body, on=False)] == []
    assert [(i.q.raw, i.cls, i.why) for i in classify(wd, d, body)] == [('여덟', 'unknown', '표식 없음')]


# ── 센 값 ──

def test_count_with_condition_matches_publish_day_data(tmp_path):
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    book = F.Book(str(wd), d)
    assert book.resolve('dv:count(md:sectors,pct,>1)').value == 7
    assert book.resolve('dv:count(md:sectors)').value == 11
    assert book.resolve('dv:count(md:sectors,pct,<0)').value == 3
    with pytest.raises(F.Miss):
        book.resolve('dv:count(md:sectors,pct,~1)')


def test_5832b595_eight_of_eleven_sectors_is_reported(tmp_path):
    """11/04 발행본 문장 그대로 — 칸을 달면 「자료와 다름」(7 ≠ 8), 달지 않으면 「표식 없음」."""
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    marked = ('<p><span data-ref="dv:count(md:sectors)">11개</span> 업종 가운데 '
              '<span data-ref="dv:count(md:sectors,pct,>1)">여덟</span>이 1% 넘게 올랐지만, 에너지와 산업재는 내렸다.</p>')
    got = {i.q.raw: (i.cls, i.why) for i in classify(wd, d, marked)}
    assert got['11개'][0] == 'data'
    assert got['여덟'] == ('unknown', '자료와 다름')
    fixed = marked.replace('>여덟<', '>일곱<')
    assert {i.q.raw: i.cls for i in classify(wd, d, fixed)}['일곱'] == 'data'
    bare = '<p>11개 업종 가운데 여덟이 1% 넘게 올랐지만, 에너지와 산업재는 내렸다.</p>'
    assert {i.q.raw: i.why for i in classify(wd, d, bare)}['여덟'] == '표식 없음'


def test_enum_accepts_korean_count(tmp_path):
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    got = classify(wd, d, '<p>이유는 <span data-nx="enum">세 가지</span>다.</p>')
    assert [(i.q.raw, i.cls) for i in got] == [('세 가지', 'excluded')]


# ── 채우기 ──

from us import fill as FL  # noqa: E402
from us import zones as Z  # noqa: E402

# 시험은 운영 구역 설정(config/number_fill.json — 켠 구역이 바뀐다)에 기대지 않는다: 가격 구역 일곱을 block 으로 고정한다.
_TEST_BLOCK = ('오늘의 장', '주식', '섹터 기간별 수익률', '채권', 'FX', '원자재', '트렌드 유닛 점검')
_LIVE_LOAD = Z.load


def _test_zones(path=Z.CONFIG):
    d = _LIVE_LOAD(path)
    if path == Z.CONFIG:
        d = dict(d, zones=[dict(z, mode='block' if z['title'] in _TEST_BLOCK else z['mode']) for z in d['zones']])
    return d


@pytest.fixture(autouse=True)
def _pin_zones(monkeypatch):
    monkeypatch.setattr(Z, 'load', _test_zones)


def test_live_block_zones_are_the_three_switched_on():
    """2026-11-28 사용자 「그 셋을 켜」 — 막는 구역을 바꾸면 이 시험도 함께 고친다(사용자에게 먼저 알린다)."""
    d = _LIVE_LOAD()
    assert [z['title'] for z in d['zones'] if z['mode'] == 'block'] == ['섹터 기간별 수익률', 'FX', '원자재']
    from common import numsrc
    assert numsrc.FILL_EFFECTIVE == '2026-11-30'


D18 = '2026-11-18'
MD18 = {'report_date': D18, 'complete': True, 'missing': [],
        'indices': {'S&P 500': {'last': 7323.6298828125, 'chg': -16.9, 'pct': -0.2302, 'date': D18},
                    'Nasdaq': {'last': 24429.88, 'chg': 101.5, 'pct': 0.245, 'date': D18},
                    'Dow': {'last': 50000.0, 'chg': 2.0, 'pct': 0.004, 'date': D18}},
        'sectors': {'Energy': {'last': 61.29, 'chg': -2.07, 'pct': -3.267, 'date': D18},
                    'Technology': {'last': 163.81, 'chg': 0.55, 'pct': 1.337, 'date': D18},
                    'Utilities': {'last': 80.0, 'chg': 0.55, 'pct': 1.2, 'date': D18}}}


@pytest.fixture()
def w18(tmp_path):
    d = tmp_path / 'w18'
    d.mkdir()
    (d / 'market_data.json').write_text(json.dumps(MD18), encoding='utf-8')
    return d


def section(title, body):
    return f'<section><h2>{title}</h2>{body}</section>'


def do_fill(wd, date, body, meta=None, title='미국 증시 마감 시황 — 제목 | D'):
    html = page(body, date, title)
    return FL.fill(html, str(wd), date, REPO, meta=meta, ledger=[])


def span(ref, text):
    return f'<span data-ref="{ref}">{text}</span>'


def test_fill_keeps_matching_text_and_is_idempotent(w18):
    body = section('주식', f'<p>S&amp;P 500은 {span("md:indices.SP500.pct|abs", "0.23%")} 내린 '
                           f'{span("md:indices.SP500.last", "7,323.63")}이다.</p>')
    new, rep = do_fill(w18, D18, body)
    assert rep['problems'] == [] and rep['counts']['filled'] == 2
    assert '>0.23%</span>' in new and '>7,323.63</span>' in new
    again, rep2 = FL.fill(new, str(w18), D18, REPO, ledger=[])
    assert again == new and rep2['counts'] == rep['counts']


@pytest.mark.parametrize('ref,text,kind,filled', [
    ('md:indices.SP500.pct', '-0.24%', '자료와 다름', '-0.23%'),
    ('md:indices.Nasdaq.pct', '+0.24%', '자료와 다름', '+0.25%'),       # half-up 한 번(0.245 → 0.25) — 반 자리 허용 없음
    ('md:indices.SP500.pct', '+0.23%', '자료와 다름', '-0.23%'),
    ('md:indices.Nasdaq.pct|abs', '0.25%', '모양', None),                # 양수 칸에 |abs
    ('md:indices.SP500.pct', '0.23%', '모양', None),                     # 부호 없는 음수 칸
    ('md:indices.Dow.pct', '0.00%', '모양', None),                       # 0 이 아닌데 0 으로
    ('md:indices.SP500.pct', '-0.23%p', '모양', None),                   # 단위
    ('md:indices.SP500.last|lvl', '7,200선', '자료와 다름', '7,300선'),
    ('md:indices.SP500.foo', '7', '칸 없음', None),
])
def test_fill_reports_instead_of_overwriting(w18, ref, text, kind, filled):
    body = section('주식', f'<p>값은 {span(ref, text)}였다.</p>')
    new, rep = do_fill(w18, D18, body)
    assert [p['problem'] for p in rep['problems']] == [kind]
    assert rep['problems'][0]['blocking']                  # 주식 = block 구역
    if filled:
        assert rep['problems'][0]['filled'] == filled
    assert f'>{text}</span>' in new                         # 덮지 않는다


def test_fill_level_floors_to_written_digits(w18):
    for text in ('7,300선', '7,000선'):
        _, rep = do_fill(w18, D18, section('주식', f'<p>{span("md:indices.SP500.last|lvl", text)}에 있다.</p>'))
        assert rep['problems'] == [], text


def test_fill_missing_cell_only_blocks_in_block_zone(w18):
    _, rep = do_fill(w18, D18, section('매크로', f'<p>값은 {span("md:indices.SP500.foo", "7")}였다.</p>'))
    assert rep['problems'][0]['problem'] == '칸 없음' and not rep['problems'][0]['blocking']


def test_fill_korean_count(w18):
    body = section('주식', f'<p>업종 가운데 {span("dv:count(md:sectors,pct,>1)", "셋")}이 1% 넘게 올랐다.</p>')
    _, rep = do_fill(w18, D18, body)
    assert rep['problems'][0]['problem'] == '자료와 다름'
    _, rep = do_fill(w18, D18, body.replace('>셋<', '>둘<'))
    assert rep['problems'] == []


def test_4709cd46_stale_asia_close_gets_code_printed_date(tmp_path):
    """11/17 발행 커밋 자료 — 닛케이 행은 11/16 관측. 숫자 옆에 기준일을 코드가 찍는다(표 칸 안은 찍지 않는다)."""
    wd, d = wd_from(tmp_path, '2026-11-17_market_data.json')
    ref = 'md:session.global_close.asia.rows[닛케이].pct'
    body = section('오늘의 장', f'<table><tr><td>{span(ref, "-2.42%")}</td></tr></table>'
                              f'<p data-session="global">닛케이225가 {span(ref + "|abs", "2.42%")} 내리는 동안 항셍은 '
                              f'{span("md:session.global_close.asia.rows[항셍].pct", "+0.49%")} 올랐다. FTSE100은 '
                              f'{span("md:session.global_close.europe.rows[FTSE100].pct|abs", "1.76%")} 내렸다.</p>')
    new, rep = do_fill(wd, d, body)
    assert rep['problems'] == []
    assert new.count('<span data-asof="2026-11-16">(11월 16일 기준)</span>') == 2      # 닛케이(문단)·항셍 — 표 칸은 아님
    assert '2.42%</span><span data-asof="2026-11-16">' in new and '-2.42%</span></td>' in new
    assert '1.76%</span> 내렸다' in new                                               # FTSE100 은 11/17 값
    again, _ = FL.fill(new, str(wd), d, REPO, ledger=[])
    assert again == new


def test_fill_title_and_summary_refs(w18):
    meta = {'title_refs': ['md:indices.SP500.pct|abs'], 'summary_refs': ['md:indices.SP500.pct|abs']}
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct|abs", "0.23%")} 내렸다.</p>'), D18,
                '미국 증시 마감 시황 — S&amp;P 500 0.24% 하락 | 2026-11-18')
    html = html.replace('</title>', '</title><meta property="og:title" content="미국 증시 모닝브리프 — 11월 18일">'
                                    '<meta property="og:description" content="지수가 0.23% 내렸다.">')
    new, rep = FL.fill(html, str(w18), D18, REPO, meta=meta, ledger=[])
    heads = [s for s in rep['slots'] if s['where'] in ('title', 'meta')]
    assert [(h['where'], h.get('problem')) for h in heads] == [('title', '자료와 다름'), ('meta', None)]
    assert 'data-refs="[&quot;md:indices.SP500.pct|abs&quot;]"' in new and '<title>' in new     # <title> 은 맨 꼴
    # 다시 돌릴 때는 글에 적힌 이름표를 쓴다
    again, rep2 = FL.fill(new, str(w18), D18, REPO, ledger=[])
    assert [h.get('problem') for h in rep2['slots'] if h['where'] != 'body'] == ['자료와 다름', None]


def test_zone_of_uses_section_title_prefix():
    cfg = Z.load()
    assert Z.zone_of(cfg, '연준 이벤트 — 파월') == ('연준 이벤트', 'warn')
    assert Z.zone_of(cfg, 'FX')[1] == 'block' and Z.zone_of(cfg, '주목 섹터·종목')[1] == 'warn'
    assert Z.zone_of(cfg, '')[1] == 'warn'


def test_fill_cli_is_off_before_the_switch(w18, tmp_path):
    import subprocess
    import sys
    h = tmp_path / 'p.html'
    body = section('주식', f'<p>{span("md:indices.SP500.pct", "-0.24%")}</p>')
    h.write_text(page(body, D18), encoding='utf-8')
    base = [sys.executable, os.path.join(SCRIPTS, 'fill_numbers.py'), '--market', 'us', '--date', D18,
            '--html', str(h), '--datadir', str(w18), '--repo', REPO, '--report', str(tmp_path / 'r.json')]
    off = subprocess.run(base, capture_output=True, text=True)
    assert off.returncode == 0 and '적용일' in off.stdout
    on = subprocess.run(base + ['--effective', ON], capture_output=True, text=True)
    assert on.returncode == 1 and '되돌림(자료와 다름)' in on.stdout, on.stdout + on.stderr
    assert json.load(open(tmp_path / 'r.json'))['counts']['blocking'] == 1


# ── 막는 검사 ──

_SAME = object()


def check(wd, date, html, first=_SAME, removed=(), on=True, correction=False):
    """first 를 주지 않으면 글 자신을 첫 판으로 넘긴다(발행 경로는 늘 첫 판을 준다 — 2026-11-28 첫 판 없음 = 위반)."""
    inp = U.Inputs('us', date, str(wd), REPO, ledger=[], fill_effective=ON if on else '2099-12-31')
    return U.result(inp, html, html if first is _SAME else first, list(removed), correction=correction)


def kinds(res):
    return [v.split(' [')[0] for v in res['violations']]


def test_check_mismatch_blocks_in_any_zone(w18):
    for title in ('매크로', '주식'):
        res = check(w18, D18, page(section(title, f'<p>{span("md:indices.SP500.pct", "-0.24%")}</p>'), D18))
        assert kinds(res) == ['자료와 다름'], title


def test_check_half_digit_tolerance_is_gone_in_blocking_mode(w18):
    html = page(section('매크로', f'<p>{span("md:indices.Nasdaq.pct", "+0.24%")}</p>'), D18)
    assert kinds(check(w18, D18, html)) == ['자료와 다름']        # 0.245 → half-up 0.25
    assert 'violations' not in check(w18, D18, html, on=False)    # 끈 판은 지금 판정 그대로(반 자리 허용)


def test_check_unmarked_numbers_block_only_in_block_zone(w18):
    body = '<p>S&amp;P 500은 0.23% 내렸다.</p>'
    assert kinds(check(w18, D18, page(section('주식', body), D18))) == ['표식 없음']
    assert kinds(check(w18, D18, page(section('전략 코멘트', body), D18))) == []
    assert kinds(check(w18, D18, page(section('주식', f'<table><tr><td>{body}</td></tr></table>'), D18))) \
        == ['코드 블록(표식 없음)']


def test_check_positive_slot_with_abs_blocks(w18):
    res = check(w18, D18, page(section('매크로', f'<p>{span("md:indices.Nasdaq.pct|abs", "0.25%")} 올랐다</p>'), D18))
    assert kinds(res) == ['자료와 다름']


def test_check_5832b595_sentence_in_block_zone(tmp_path):
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    bare = section('주식', '<p>11개 업종 가운데 여덟이 1% 넘게 올랐지만, 에너지와 산업재는 내렸다.</p>')
    res = check(wd, d, page(bare, d))
    assert [v.split(' — ')[0] for v in res['violations']] == ['표식 없음 [세계 지수·업종] 11개', '표식 없음 [세계 지수·업종] 여덟',
                                                             '표식 없음 [세계 지수·업종] 1%']
    marked = section('주식', f'<p>{span("dv:count(md:sectors)", "11개")} 업종 가운데 '
                           f'{span("dv:count(md:sectors,pct,>1)", "여덟")}이 <span data-nx="set">1%</span> 넘게 올랐다.</p>')
    res = check(wd, d, page(marked, d))
    # 문턱 선언은 조건 문단 밖이라 무효, 여덟은 7 과 다르다
    assert sorted(v.split(' — ')[0] for v in res['violations']) == ['선언 무효 [세계 지수·업종] 1%',
                                                                    '자료와 다름 [세계 지수·업종] 여덟']


def test_check_set_threshold_only_in_condition_paragraph(w18):
    html = page(section('매크로', '<p data-falsifier="1">30년물이 <span data-nx="set">5.05%</span>를 밑돌면 틀린다.</p>'), D18)
    res = check(w18, D18, html)
    assert res['violations'] == [] and res['declared_set'] == ['5.05%']


def test_check_stale_ref_needs_the_code_printed_date(tmp_path):
    wd, d = wd_from(tmp_path, '2026-11-17_market_data.json')
    body = section('오늘의 장', f'<p>닛케이225가 {span("md:session.global_close.asia.rows[닛케이].pct|abs", "2.42%")} 내렸다.</p>')
    html = page(body, d)
    assert kinds(check(wd, d, html)) == ['기준일 없음']
    filled, _ = FL.fill(html, str(wd), d, REPO, ledger=[])
    res = check(wd, d, filled)
    assert res['violations'] == []
    assert res['fills'] == [{'ref': 'md:session.global_close.asia.rows[닛케이].pct|abs', 'asset': '닛케이', 'group': 'global',
                             'field': 'pct', 'date': '2026-11-16', 'value': -2.42, 'text': '2.42%'}]
    # 기준일 글자를 손으로 바꾸면 다시 막힌다
    assert kinds(check(wd, d, filled.replace('(11월 16일 기준)', '(11월 17일 기준)'))) == ['기준일 없음']


def test_check_removed_numbers_must_be_listed(w18):
    first = page(section('주식', f'<p>나스닥은 {span("md:indices.Nasdaq.pct", "+0.25%")} 올랐다.</p>'
                                 '<p>기술주는 2.5% 올랐다는 보도가 있었다.</p>'), D18)
    final = page(section('주식', f'<p>나스닥은 {span("md:indices.Nasdaq.pct", "+0.25%")} 올랐다.</p>'), D18)
    res = check(w18, D18, final, first=first)
    assert kinds(res) == ['적지 않은 삭제'] and res['removal']['unlisted'] == ['2.5%']
    rm = [{'number': '2.5%', 'sentence': '기술주는 2.5% 올랐다는 보도가 있었다.', 'reason': '출처 없음'}]
    res = check(w18, D18, final, first=first, removed=rm)
    assert res['violations'] == [] and res['removal']['matched'] == 1 and res['removal']['reasons'] == {'출처 없음': 1}
    # 칸을 단 숫자도 따라간다 — 문장째 지우면 removed 가 있어야 한다
    gone = page(section('주식', '<p>장은 조용했다.</p>'), D18)
    res = check(w18, D18, gone, first=final)
    assert kinds(res) == ['적지 않은 삭제']


def test_check_ambiguous_sentence_needs_removed_only_when_number_is_gone(w18):
    twice = '<p>기술주는 2.5% 올랐다.</p><p>기술주는 2.5% 올랐다.</p>'
    first = page(section('전략 코멘트', twice), D18)
    kept = page(section('전략 코멘트', '<p>기술주는 2.5% 올랐다.</p>'), D18)
    assert check(w18, D18, kept, first=first)['violations'] == []
    gone = page(section('전략 코멘트', '<p>장은 조용했다.</p>'), D18)
    assert kinds(check(w18, D18, gone, first=first)) == ['적지 않은 삭제', '적지 않은 삭제']


def test_check_title_refs(w18):
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct|abs", "0.23%")} 내렸다.</p>'), D18,
                '미국 증시 마감 시황 — S&amp;P 500 0.23% 하락 | 2026-11-18')
    html = html.replace('</title>', '</title><meta property="og:title" content="미국 증시 모닝브리프 — 11월 18일">')
    filled, _ = FL.fill(html, str(w18), D18, REPO, meta={'title_refs': ['md:indices.SP500.pct|abs']}, ledger=[])
    assert check(w18, D18, filled)['violations'] == []
    bad = filled.replace('0.23% 하락', '0.24% 하락')
    assert kinds(check(w18, D18, bad)) == ['자료와 다름']
    other, _ = FL.fill(html.replace('S&amp;P 500 0.23%', '나스닥 0.25%'), str(w18), D18, REPO,
                       meta={'title_refs': ['md:indices.Nasdaq.pct']}, ledger=[])
    assert kinds(check(w18, D18, other)) == ['본문에 없는 이름표']


def test_check_off_mode_is_unchanged(w18):
    html = page(section('주식', '<p>11개 업종 가운데 여덟이 1% 넘게 올랐다.</p>'), D18)
    res = check(w18, D18, html, on=False)
    assert 'violations' not in res and 'fills' not in res
    assert [u['n'] for u in res['unknown_all']] == ['11개', '1%']              # 한글 개수는 끈 판에서 세지 않는다


def test_check_cli_exit_1_with_violations(w18, tmp_path):
    import subprocess
    import sys
    h = tmp_path / 'p.html'
    h.write_text(page(section('주식', '<p>S&amp;P 500은 0.23% 내렸다.</p>'), D18), encoding='utf-8')
    base = [sys.executable, os.path.join(SCRIPTS, 'check_number_sources.py'), '--market', 'us', '--date', D18,
            '--html', str(h), '--datadir', str(w18), '--repo', REPO, '--json', '--effective', ON]
    off = subprocess.run(base, capture_output=True, text=True)
    assert off.returncode == 0 and json.loads(off.stdout)['violations'] == []
    on = subprocess.run(base + ['--fill-effective', ON], capture_output=True, text=True)
    assert on.returncode == 1, on.stderr
    out = json.loads(on.stdout)
    assert out['violations'] and out['sources']['blocking'] is True
    (w18 / 'removed.json').write_text('[{"number": "1"}]', encoding='utf-8')
    bad = subprocess.run(base + ['--fill-effective', ON], capture_output=True, text=True)
    assert bad.returncode == 2 and 'removed' in bad.stderr


# ── 기록 ──

@pytest.mark.parametrize('modname,stuck', [('record', 'indeterminate'), ('record2', 'incomplete')])
def test_record_fails_on_violations_and_keeps_fills(w18, modname, stuck):
    import importlib
    R = importlib.import_module(f'verification.{modname}')
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct|abs", "0.23%")} 내렸고 나스닥은 0.25% 올랐다.</p>'), D18)
    src = check(w18, D18, html)
    spec = {'name': 'check_number_sources', 'json': True, 'result': 'sources'}
    out = json.dumps({'skipped': False, 'warnings': [], 'violations': src['violations'], 'sources': src})
    res = {}
    assert R._classify(spec, 1, out, '', {'html': '/x/p.html', 'datadir': '/w', 'repo': '/r'}, res) == 'fail'
    assert res['sources']['blocking'] is True and res['sources']['violations'] == 1
    assert res['sources']['fills'] == [{'ref': 'md:indices.SP500.pct|abs', 'asset': 'S&P 500', 'group': 'indices',
                                        'field': 'pct', 'date': D18, 'value': -0.2302, 'text': '0.23%'}]
    assert res['items'][0].startswith('표식 없음 [세계 지수·업종] 0.25%')
    # 끈 판(blocking 없음)에서 exit 1 이면 지금처럼 판정 불가
    off = check(w18, D18, html, on=False)
    out = json.dumps({'skipped': False, 'warnings': [], 'violations': ['x'], 'sources': off})
    assert R._classify(spec, 1, out, '', {'html': '/x/p.html', 'datadir': '/w', 'repo': '/r'}, {}) == stuck
    out = json.dumps({'skipped': False, 'warnings': [], 'violations': [], 'sources': src})
    assert R._classify(spec, 1, out, '', {'html': '/x/p.html', 'datadir': '/w', 'repo': '/r'}, {}) == stuck


def test_period_names_are_not_counted_in_blocking_mode(w18):
    """11/25 시운전에서 나온 꼴 — 「1주 전」「1개월 수익률」「최근 2년」은 기간 이름(세지 않는 숫자 ④). 「(504거래일)」은 11/25 에는
    센 값으로 셌지만 11/28 부터 기간 이름이다 — 「최근 2년」의 창 길이를 괄호로 풀어 쓴 것(11/27 글 3건). 「9거래일째」는 센 값."""
    body = section('채권', '<p>1주 전보다 낮고, 레벨은 최근 2년(504거래일) 가운데 높은 쪽이다. 3개월 상대수익률과 20거래일 전. '
                         '국면은 9거래일째다.</p>')
    res = check(w18, D18, page(body, D18))
    assert [v.split(' — ')[0] for v in res['violations']] == ['표식 없음 [금리] 9거래일']


# 11/27 글(ee21bcd)의 실제 문장 — 기간·방법 설명 숫자는 세지 않고, 같은 문장의 값 수량은 그대로 센다
@pytest.mark.parametrize('text,period,values', [
    ('VIX는 최근 2년(504거래일) 가운데 높은 쪽 13% 안에 남았다.', ['2년', '504거래일'], ['13%']),
    ('30년물의 하루 움직임은 최근 60거래일 평균 하루 변동 대비 1.59배, 10년물은 1.3배다.', ['60거래일'], ['1.59배', '1.3배']),
    ('최근 60거래일 두 자산은 같은 방향으로 움직여, 반대로 움직이던 직전 60거래일과 부호가 바뀌었다.', ['60거래일', '60거래일'], []),
    ('상관계수는 최근 60거래일 0.227, 직전 60거래일 -0.30이다.', ['60거래일', '60거래일'], ['0.227', '-0.30']),
    ('최근 252거래일 지수·업종 수익률로 추정한 비중이다.', ['252거래일'], []),
    ('5거래일로는 22bp 하락 가운데 15bp가 실질금리, 7bp가 기대인플레였다.', ['5거래일'], ['22bp', '15bp', '7bp']),
    ('장중에는 개장 갭 뒤 첫 30분에 한 번 되밀렸다.', ['30분'], []),
    ('아래에서 4분의 1 지점과 위에서 4분의 1 지점을 경계로 삼았다.', ['4분의 1', '4분의 1'], []),
    ('하이일드는 5거래일 동안 25bp 넓어졌다.', ['5거래일'], ['25bp']),
])
def test_period_and_method_descriptors_1127(text, period, values):
    qs = S.quantities(text, ('30년물', '10년물'), periods=True)
    assert [q.raw for q in qs if q.code == 'period'] == period
    assert [q.raw for q in qs if not q.code] == values


@pytest.mark.parametrize('text', ['9거래일째 단기 약세다.', '3거래일 연속 올랐다.', '지수 3개의 관측값이다.'])
def test_counted_values_stay_quantities(text):
    assert all(q.code != 'period' for q in S.quantities(text, (), periods=True))


def test_period_descriptors_only_in_blocking_mode():
    """끈 판 집계는 그대로 — 「(504거래일)」「첫 30분」「4분의 1」은 지금처럼 값 수량."""
    qs = S.quantities('최근 2년(504거래일)·첫 30분·4분의 1', ())
    assert [q.code for q in qs] == ['', '', '', '', '']


# ── 구현 검토 전 자체 점검(advisor) 에서 나온 것 ──

def test_filled_stale_stamp_does_not_count_as_deletion(tmp_path):
    """첫 판 = 채우기 전 초안. 코드가 찍은 기준일이 문장 열쇠를 바꿔 「사라짐」이 되면 안 된다."""
    wd, d = wd_from(tmp_path, '2026-11-17_market_data.json')
    body = section('오늘의 장', f'<p>닛케이225가 {span("md:session.global_close.asia.rows[닛케이].pct|abs", "2.42%")} 내렸고 '
                              f'FTSE100은 {span("md:session.global_close.europe.rows[FTSE100].pct|abs", "1.76%")} 내렸다.</p>')
    first = page(body, d)
    final, _ = FL.fill(first, str(wd), d, REPO, ledger=[])
    assert '(11월 16일 기준)' in final
    res = check(wd, d, final, first=first)
    assert res['violations'] == [] and res['removal']['gone'] == 0


def test_removed_pairs_are_printed_for_the_writer_but_not_recorded(w18):
    from verification import record as R
    first = page(section('주식', '<p>기술주는 2.5% 올랐다는 보도가 있었다.</p>'), D18)
    final = page(section('주식', '<p>장은 조용했다.</p>'), D18)
    res = check(w18, D18, final, first=first)
    assert res['removal']['wanted'] == [{'number': '2.5%', 'sentence': '기술주는 2.5% 올랐다는 보도가 있었다.'}]
    rec = R._blocking_fields(res, {'html': '/x', 'datadir': '/w', 'repo': '/r'}, res['violations'])
    assert 'wanted' not in rec['removal'] and '보도' not in json.dumps(rec, ensure_ascii=False)
    # 그 짝을 그대로 옮기면 풀린다
    rm = [dict(w, reason='출처 없음') for w in res['removal']['wanted']]
    assert check(w18, D18, final, first=first, removed=rm)['violations'] == []


def test_dv_with_post_date_is_not_stamped(w18):
    """계산값은 첫 칸의 날짜를 지닌다 — 그 날짜가 글 날짜면 기준일을 찍지도 요구하지도 않는다."""
    md = json.loads((w18 / 'market_data.json').read_text())
    md['yields'] = {'10Y': {'level': 4.9, 'bp': -1.0, 'date': D18, 'week_ago': 5.0, 'week_ago_date': '2026-11-11'}}
    (w18 / 'market_data.json').write_text(json.dumps(md), encoding='utf-8')
    body = section('채권', f'<p>1주 전보다 {span("dv:diff(md:yields.10Y.level,md:yields.10Y.week_ago)", "-10.0bp")} 낮다.</p>')
    new, rep = do_fill(w18, D18, body)
    assert rep['problems'] == [] and 'data-asof' not in new
    assert check(w18, D18, new)['violations'] == []


@pytest.mark.parametrize('text,code', [('3주째', ''), ('3주 연속', ''), ('5개월 만에', ''), ('3개월 수익률', 'period')])
def test_period_names_exclude_counted_runs(text, code):
    assert [q.code for q in S.quantities(text, (), periods=True)][0] == code


def test_enum_accepts_korean_without_count_word(w18):
    got = check(w18, D18, page(section('주식', '<p>이유는 <span data-nx="enum">둘</span>이고 <span data-nx="enum">세 업종</span>이다.</p>'), D18))
    assert got['violations'] == []


def test_efe2d787_sector_period_row_from_another_session_is_stamped(w18):
    """efe2d787(10/12 섹터 기간 표의 10/9 값) 꼴 — 그날 자료에는 행 날짜가 없어(수집기가 그 뒤로 남긴다) **만든 자료**다."""
    md = json.loads((w18 / 'market_data.json').read_text())
    md['sector_performance'] = {'Communication Services': {'date': '2026-11-17', '1D': -1.51, '1W': 1.0, '1M': 2.0,
                                                           '6M': 3.0, '1Y': 4.0}}
    (w18 / 'market_data.json').write_text(json.dumps(md), encoding='utf-8')
    body = section('섹터 기간별 수익률', f'<p>커뮤니케이션은 하루 {span("md:sector_performance.CommunicationServices.1D", "-1.51%")}였다.</p>')
    html = page(body, D18)
    assert kinds(check(w18, D18, html)) == ['기준일 없음']
    new, _ = do_fill(w18, D18, body)
    assert '(11월 17일 기준)' in new and check(w18, D18, new)['violations'] == []


def test_filled_markers_survive_publish_transforms(tmp_path):
    """채운 글이 조판(apply_readability → apply_colors)을 지나도 기준일 표지·제목 이름표가 남고 검사가 같은 판정을 낸다.
    실제 발행본 꼴(11/05 고정 글)에 묵은 칸 하나를 넣는다 — 그날 자료의 S&P 500 행 날짜를 하루 앞으로 바꾼 **만든 자료**다."""
    import subprocess
    import sys
    from us.tests import test_number_sources as T
    html, _ = T._fix()
    d = T._fixture_wd(tmp_path)
    md = json.load(open(d / 'market_data.json'))
    rd = md['report_date']
    md['indices']['S&P 500']['date'] = '2026-11-04'
    (d / 'market_data.json').write_text(json.dumps(md), encoding='utf-8')
    pct = md['indices']['S&P 500']['pct']
    body = f'<p>지수는 <span data-ref="md:indices.SP500.pct">{pct:+.2f}%</span> 움직였다.</p>'
    p = tmp_path / f'{rd}.html'
    src = html.replace('</main>', body + '</main>', 1) if '</main>' in html else html.replace('</body>', body + '</body>')
    filled, rep = FL.fill(src, str(d), rd, REPO, ledger=[], meta={'summary_refs': []})
    assert rep['counts']['stale_stamped'] == 1
    p.write_text(filled, encoding='utf-8')
    for tool in ('apply_readability.py', 'apply_colors.py'):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, tool), str(p)], capture_output=True, text=True)
        assert r.returncode in (0, 1), r.stderr
    out = p.read_text(encoding='utf-8')
    assert '<span data-asof="2026-11-04">(11월 4일 기준)</span>' in out
    assert ('data-refs="[]"' in out) == ('data-refs="[]"' in filled)
    inp = U.Inputs('us', rd, str(d), REPO, ledger=[], fill_effective=ON)
    items_ = U.classify(inp, out)[1]
    got = [i for i in items_ if i.detail.get('fill', {}).get('ref') == 'md:indices.SP500.pct']
    assert len(got) == 1 and got[0].cls == 'data' and not got[0].detail.get('no_asof')


# ── 펀드 점검판 SPY 대비 상대수익률의 단위(11/27 발행본 ee21bcd) ──

def test_fund_board_relative_return_accepts_pp_as_written_on_1127(tmp_path):
    """11/27 글은 rel_3m 을 「-15.34%p」「+5.58%p」로 썼다(자료 값 그대로). % 만 받는 칸이라 「자료와 다름」이 났다."""
    wd, d = wd_from(tmp_path, '2026-11-04_market_data.json')
    units = [{'id': 'semis', 'status': 'ok', 'rel_3m': -15.34, 'rel_3m_5d': -13.87, 'rel_3m_chg_pp': -1.47, 'as_of': d},
             {'id': 'homebuilders', 'status': 'ok', 'rel_3m': 5.58, 'rel_3m_chg_pp': 6.87, 'as_of': d}]
    (wd / 'fund_board.json').write_text(json.dumps({'report_date': d, 'status': 'ok', 'missing': [], 'units': units}), encoding='utf-8')
    body = ('<p>반도체는 <span data-ref="fb:units[semis].rel_3m">-15.34%p</span>로 5거래일 전'
            '(<span data-ref="fb:units[semis].rel_3m_5d">-13.87%p</span>)보다 나빠졌고, 주택건설은 '
            '<span data-ref="fb:units[homebuilders].rel_3m">+5.58%p</span>다. 3개월 수익률 '
            '<span data-ref="fb:units[semis].rel_3m">-15.34%</span> 꼴도 받는다.</p>')
    got = [(i.q.raw, i.cls) for i in classify(wd, d, body) if i.q.raw.startswith(('-', '+'))]
    assert got == [('-15.34%p', 'data'), ('-13.87%p', 'data'), ('+5.58%p', 'data'), ('-15.34%', 'data')], got


# ── 11/28 칸 넓히기·칸 밖 단위 — 11/27 글(ee21bcd)의 실제 문장과 그 발행 커밋 자료 ──

D27 = '2026-11-27'


@pytest.fixture()
def w27(tmp_path):
    d = tmp_path / 'w27'
    d.mkdir()
    for f in ('market_data', 'intraday', 'fund_board'):
        with open(os.path.join(FIX, f'2026-11-27_{f}.json'), encoding='utf-8') as fh:
            (d / f'{f}.json').write_text(fh.read(), encoding='utf-8')
    return d


SENT_1127 = [
    ('주식', '추정 기여도로 기술이 {} 보태 지수 상승 가운데 가장 컸고, 경기소비재 {}다.',
     [('md:price_context.sector_contribution.rows[Technology].contribution', '+0.95%p'),
      ('md:price_context.sector_contribution.rows[Consumer Discretionary].contribution', '+0.28%p')]),
    ('주식', '유틸리티·헬스케어(각 {})와 필수소비재({})가 가장 덜 올랐다.',
     [('md:price_context.sector_contribution.rows[Utilities].change', '0.28%'),
      ('md:price_context.sector_contribution.rows[Consumer Staples].change', '0.41%')]),
    ('트렌드 유닛 점검', '52주 고점 대비 단기 약세 기준({})을 넘어 있다.', [('fb:market_regime.rules.drawdown_pct', '-5%')]),
    ('주식', 'S&P 500은 시가 {}에서 10시 무렵 {}까지 밀렸다.',
     [('id:S&P 500.open', '7,263'), ('id:S&P 500.low', '7,211')]),
    ('주식', '엔비디아는 시가 {}에서 {}까지 {} 밀렸다.',
     [('id:Nvidia.open', '151.94달러'), ('id:Nvidia.low', '145.39달러'), ('id:Nvidia.open_to_low_pct|abs', '4.31%')]),
    ('원자재', '금은 {} 저점에서 반등했고 WTI는 개장 무렵의 {}대가 고점이었다.',
     [('id:Gold.low', '3,643달러'), ('id:WTI.open|lvl', '84달러')]),
    ('오늘의 장', 'S&P 500 선물은 {}에서 {} 사이, 나스닥100 선물은 {}에서 {} 사이에서 움직였다.',
     [('md:session.futures.contracts.ES.low', '7,183'), ('md:session.futures.contracts.ES.high', '7,254'),
      ('md:session.futures.contracts.NQ.low', '25,983'), ('md:session.futures.contracts.NQ.high', '26,436')]),
    ('오늘의 장', 'VIX는 최근 2년(504거래일) 가운데 높은 쪽 {} 안에 남았다.', [('md:price_context.levels.VIX.plain.share_pct', '13%')]),
    ('채권', '10년물은 최근 2년 가운데 이보다 높았던 날이 {}뿐이고, 30년물은 {}뿐이다.',
     [('md:price_context.levels.10Y.plain.days', '45일'), ('md:price_context.levels.30Y.plain.days', '37일')]),
    ('채권', '상관계수는 최근 60거래일 {}, 직전 60거래일 {}이다.',
     [('md:price_context.correlations[equity_rates].value', '0.227'),
      ('md:price_context.correlations[equity_rates].prior', '-0.30')]),
]


@pytest.mark.parametrize('title,tmpl,refs', SENT_1127)
def test_new_slots_fill_and_pass_on_1127_sentences(w27, title, tmpl, refs):
    body = section(title, '<p>' + tmpl.format(*[span(r, t) for r, t in refs]) + '</p>')
    new, rep = do_fill(w27, D27, body)
    assert rep['problems'] == [], rep['problems']
    assert [s['filled'] for s in rep['slots']] == [t for _, t in refs]
    assert check(w27, D27, new)['violations'] == []


def test_5y5y_is_stale_and_stamped(w27):
    body = section('채권', f'<p>5년 뒤 5년 명목금리는 {span("md:price_context.forward_5y5y.nominal", "5.05%")}, '
                         f'실질 {span("md:price_context.forward_5y5y.real", "2.94%")}다.</p>')
    new, rep = do_fill(w27, D27, body)
    assert rep['problems'] == [] and new.count('(11월 25일 기준)') == 2
    assert check(w27, D27, new)['violations'] == []


@pytest.mark.parametrize('mutate', [
    lambda d: d.pop('collect'),
    lambda d: d['collect'].update(status='partial'),
    lambda d: d['collect'].update(required_ok=False),
    lambda d: d['collect'].update(missing=['Nvidia']),
])
def test_intraday_slot_invalid_without_ok_collect(w27, mutate):
    p = w27 / 'intraday.json'
    d = json.loads(p.read_text())
    mutate(d)
    p.write_text(json.dumps(d), encoding='utf-8')
    body = section('주식', f'<p>엔비디아는 시가 {span("id:Nvidia.open", "151.94달러")}였다.</p>')
    new, rep = do_fill(w27, D27, body)
    assert [x['problem'] for x in rep['problems']] == ['칸 무효']
    assert kinds(check(w27, D27, new)) == ['칸 무효']


def test_intraday_unknown_asset_or_time_field_is_not_a_slot(w27):
    from us import facts as F
    b = F.Book(str(w27), D27, [])
    for ref in ('id:Nvidia.low_t', 'id:collect.as_of', 'id:Dow.open'):
        with pytest.raises(F.Miss) as e:
            b.resolve(ref)
        assert e.value.kind == '칸 없음', ref


# 칸 밖 단위(11/27 실제 4건 — 금·WTI·브렌트·엔비디아 종가): 채우기가 단위를 칸 안으로 옮긴다
def test_fill_moves_trailing_unit_into_span(w27):
    body = section('원자재', f'<p>금은 {span("md:commodities.Gold.pct", "2.00%")} 오른 '
                           f'{span("md:commodities.Gold.last", "3,674.60")}달러다.</p>')
    new, rep = do_fill(w27, D27, body)
    assert rep['problems'] == []
    assert '<span data-ref="md:commodities.Gold.last">3,674.60달러</span>다' in new
    assert check(w27, D27, new)['violations'] == []
    again, rep2 = FL.fill(new, str(w27), D27, REPO, ledger=[])
    assert again == new and rep2['problems'] == []


def test_fill_does_not_move_unit_after_a_space_or_when_inside_has_unit(w27):
    body = section('원자재', f'<p>금은 {span("md:commodities.Gold.last", "3,674.60")} 달러, '
                           f'다시 {span("md:commodities.Gold.last", "3,674.60달러")}다.</p>')
    new, rep = do_fill(w27, D27, body)
    assert '3,674.60</span> 달러' in new and '3,674.60달러</span>다' in new
    assert rep['problems'] == []
    assert kinds(check(w27, D27, new)) == ['표식 오류']       # 빈칸 뒤 단위는 옮기지 않는다 — 검사는 지금처럼 표식 오류


def test_moved_unit_keeps_stale_stamp_after_the_unit(w27):
    body = section('채권', f'<p>5년 뒤 5년 명목금리는 {span("md:price_context.forward_5y5y.nominal", "5.05")}%다.</p>')
    new, rep = do_fill(w27, D27, body)
    assert rep['problems'] == []
    assert '5.05%</span><span data-asof="2026-11-25">(11월 25일 기준)</span>다' in new
    again, _ = FL.fill(new, str(w27), D27, REPO, ledger=[])
    assert again == new
    assert check(w27, D27, new)['violations'] == []


# ── 설계 검토 2회차 #3 — 「날이 12일뿐」(11/27 글 505행): 「12일」이 날짜로 읽혀 칸을 달 수 없었다 ──

SENT_12 = '원/달러는 같은 기간 가운데 이보다 낮았던 날이 {}뿐인 수준까지 내려왔다.'
REF_12 = 'md:price_context.levels.USD/KRW.plain.days'


def test_day_count_after_nari_is_a_value_in_blocking_mode_1127(w27):
    body = section('환율', '<p>' + SENT_12.format(span(REF_12, '12일')) + '</p>')
    new, rep = do_fill(w27, D27, body)
    assert rep['problems'] == [], rep['problems']
    assert [s['filled'] for s in rep['slots']] == ['12일']
    assert check(w27, D27, new)['violations'] == []
    again, rep2 = FL.fill(new, str(w27), D27, REPO, ledger=[])
    assert again == new and rep2['problems'] == []


def test_day_count_wrong_value_is_reported_1127(w27):
    body = section('환율', '<p>' + SENT_12.format(span(REF_12, '13일')) + '</p>')
    _, rep = do_fill(w27, D27, body)
    assert [p['problem'] for p in rep['problems']] == ['자료와 다름']


@pytest.mark.parametrize('text,periods,codes', [
    (SENT_12.format('12일'), True, ['']),               # 막는 판 — 날수(값, 단위 일)
    (SENT_12.format('12일'), False, ['date']),          # 끈 판 — 지금처럼 날짜
    ('높았던 날이 45일뿐이고, 다른 쪽은 37일뿐이다.', True, ['', '']),
    ('11월 12일 발표였고 12일 기준 값이다.', True, ['date', 'date']),   # 진짜 날짜는 막는 판에서도 날짜
    ('발표한 날이 11월 12일이다.', True, ['date']),
    ('이보다 높았던 날은 20일뿐이다.', True, ['']),      # 작성자 지시문 예시 꼴
    ('이보다 높았던 날은 20일뿐이다.', False, ['date']),
])
def test_day_count_rule_scope(text, periods, codes):
    qs = S.quantities(text, (), periods=periods)
    assert [q.code for q in qs] == codes
    if text.startswith('원/달러') and periods:
        assert (qs[0].raw, qs[0].unit, qs[0].value) == ('12일', '일', 12.0)




# ── 11/28 막는 판에서 첫 판이 없으면 위반 / 무인 정정 재검사는 첫 판을 보지 않는다 ──

def test_blocking_without_first_draft_is_a_violation(w18):
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct", "-0.23%")}</p>'), D18)
    assert check(w18, D18, html, first=None)['violations'] == ['첫 판 확인 불가 — 첫 판이 없다']
    other = page(section('주식', '<p>x</p>'), '2026-11-17')
    assert check(w18, D18, html, first=other)['violations'] == ['첫 판 확인 불가 — 첫 판이 이 글의 날짜·시장이 아니다']
    assert 'violations' not in check(w18, D18, html, first=None, on=False)      # 끈 판은 지금 그대로


def test_correction_mode_skips_first_draft_and_removal(w18):
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct", "-0.23%")}</p>'), D18)
    first = page(section('주식', f'<p>{span("md:indices.SP500.pct", "-0.23%")} 그리고 2.5% 보도.</p>'), D18)
    assert set(kinds(check(w18, D18, html, first=first))) == {'적지 않은 삭제'}
    assert check(w18, D18, html, first=None, correction=True)['violations'] == []
    bad = page(section('주식', f'<p>{span("md:indices.SP500.pct", "-0.24%")}</p>'), D18)
    assert kinds(check(w18, D18, bad, first=None, correction=True)) == ['자료와 다름']   # 값 위반은 그대로


def test_cli_correction_flag(w18, tmp_path):
    import subprocess, sys
    html = page(section('주식', f'<p>{span("md:indices.SP500.pct", "-0.23%")}</p>'), D18)
    p = tmp_path / 'p.html'
    p.write_text(html, encoding='utf-8')
    cli = os.path.join(REPO, 'scripts', 'check_number_sources.py')
    base = [sys.executable, cli, '--market', 'us', '--date', D18, '--html', str(p), '--datadir', str(w18), '--repo', REPO,
            '--fill-effective', ON, '--effective', ON]
    r = subprocess.run(base, capture_output=True, text=True)
    assert r.returncode == 1 and '위반: 첫 판 확인 불가' in r.stdout
    r = subprocess.run(base + ['--correction'], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
