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
