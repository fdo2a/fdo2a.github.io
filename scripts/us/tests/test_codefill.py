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
    html = html.replace('</title>', '</title><meta property="og:description" content="지수가 0.23% 내렸다.">')
    new, rep = FL.fill(html, str(w18), D18, REPO, meta=meta, ledger=[])
    heads = [s for s in rep['slots'] if s['where'] in ('title', 'meta')]
    assert [(h['where'], h.get('problem')) for h in heads] == [('title', '자료와 다름'), ('meta', None)]
    assert 'data-refs="[&quot;md:indices.SP500.pct|abs&quot;]"' in new
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
