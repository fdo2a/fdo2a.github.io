"""prose_swap — 이름으로 되꽂기가 실제로 거부해야 할 것을 거부하는가."""

import json

import pytest

from us.prose_swap import ProseSwapError, extract, parse_payload, reinsert

HTML = """<html><body>
<h2>시황</h2>
<p>나스닥은 1.2% 올랐다. 엔비디아가 <strong>-0.98%</strong>로 눌렸다.</p>
<p>금은 3.22% 올라 3개월래 최고치를 썼다.</p>
<p class="caption">자료: FRED</p>
<table><tr><td><p>표 안 문단 5.0%</p></td></tr></table>
<section data-editor-note="1"><p>사람이 쓴 노트 9.9%</p></section>
<p data-reconcile="bonds">채권은 방향이 갈렸다. 2s10s는 42bp다.</p>
</body></html>"""


def payload_of(html):
    text, side = extract(html)
    return text, side


def test_표와_캡션과_에디터노트는_뽑지_않는다():
    text, side = payload_of(HTML)
    assert sorted(side['items']) == ['P001', 'P002', 'P003']
    assert '표 안 문단' not in text
    assert '사람이 쓴 노트' not in text
    assert '자료: FRED' not in text


def test_인라인_태그는_자리표로_나간다():
    text, side = payload_of(HTML)
    assert '<strong>' not in text
    assert '⟦0⟧-0.98%⟦1⟧' in text
    assert side['items']['P001']['tags'] == ['<strong>', '</strong>']


def test_그대로_돌려주면_원문과_같다():
    text, side = payload_of(HTML)
    assert reinsert(HTML, text, side) == HTML.replace(
        '나스닥은 1.2% 올랐다. 엔비디아가 <strong>-0.98%</strong>로 눌렸다.',
        '나스닥은 1.2% 올랐다. 엔비디아가 <strong>-0.98%</strong>로 눌렸다.')


def test_말투만_바꾸면_통과한다():
    text, side = payload_of(HTML)
    out = reinsert(HTML, text.replace('올랐다.', '올랐습니다.'), side)
    assert '올랐습니다' in out
    assert '<strong>-0.98%</strong>' in out
    assert 'data-reconcile="bonds"' in out


def test_문단이_자리를_바꾸면_수치가_어긋나_거부된다():
    """문단 수는 같다. 셈으로 맞추던 방식이 통과시키던 바로 그 사고."""
    text, side = payload_of(HTML)
    lines = text.split('\n\n')
    a = lines[0].split('\n', 1)
    b = lines[1].split('\n', 1)
    swapped = '\n\n'.join([a[0] + '\n' + b[1], b[0] + '\n' + a[1]] + lines[2:])
    with pytest.raises(ProseSwapError, match='수치가 달라졌다'):
        reinsert(HTML, swapped, side)


def test_문단이_빠지면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='돌아오지 않은'):
        reinsert(HTML, text.split('\n\n')[0], side)


def test_이름이_겹치면_거부된다():
    text, side = payload_of(HTML)
    dup = text + '\n[[P001]]\n또 왔다.\n'
    with pytest.raises(ProseSwapError, match='두 번'):
        reinsert(HTML, dup, side)


def test_모르는_이름은_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='모르는 이름'):
        reinsert(HTML, text + '\n[[P404]]\n없던 문단 1.0%.\n', side)


def test_인라인_표식이_사라지면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='인라인 표식'):
        reinsert(HTML, text.replace('⟦1⟧', ''), side)


def test_수치가_바뀌면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='수치가 달라졌다'):
        reinsert(HTML, text.replace('3.22%', '3.23%'), side)


def test_수치가_사라져도_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='수치가 달라졌다'):
        reinsert(HTML, text.replace('금은 3.22% 올라', '금은 올라'), side)


def test_HTML이_섞여_오면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='HTML이 섞였다'):
        reinsert(HTML, text.replace('금은', '<b>금은</b>'), side)


def test_마크다운_구조가_섞여_오면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='마크다운'):
        reinsert(HTML, text.replace('[[P002]]\n', '[[P002]]\n## 소제목\n'), side)


def test_빈_문단으로_돌아오면_거부된다():
    text, side = payload_of(HTML)
    broken = text.replace('금은 3.22% 올라 3개월래 최고치를 썼다.', '')
    with pytest.raises(ProseSwapError, match='비어서'):
        reinsert(HTML, broken, side)


def test_다른_HTML의_사이드카는_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='뽑힌 것이 아니다'):
        reinsert(HTML.replace('시황', '마감'), text, side)


def test_스킬_요약_블록은_무시한다():
    text, side = payload_of(HTML)
    out = reinsert(HTML, text + '\n<!-- HUMANIZE-SUMMARY -->\n변경률 12%\n', side)
    assert 'HUMANIZE-SUMMARY' not in out


def test_이름_없는_머리말이_붙으면_거부된다():
    text, side = payload_of(HTML)
    with pytest.raises(ProseSwapError, match='이름 없는 텍스트'):
        reinsert(HTML, '윤문 완료했습니다!\n\n' + text, side)


# ── 2026-08-25 codex 검토에서 실제로 재현된 우회들 ──────────────────────────

SWAPPY = """<html><body>
<p>연준은 신중한 태도를 유지하겠다는 뜻을 되풀이했다.</p>
<p>시장은 이번 국면을 관망하며 다음 발표를 기다리는 분위기다.</p>
<p>나스닥은 +1.2% 올랐다.</p>
<p>러셀은 -1.2% 밀렸다.</p>
</body></html>"""


def _swap_bodies(text, a, b):
    blocks = dict(x.split('\n', 1) for x in text.strip().split('\n\n'))
    ka, kb = '[[%s]]' % a, '[[%s]]' % b
    blocks[ka], blocks[kb] = blocks[kb], blocks[ka]
    return '\n\n'.join('%s\n%s' % (k, v) for k, v in blocks.items())


def test_숫자_없는_문단끼리_내용을_맞바꾸면_거부된다():
    """이름표는 자리만 정한다 — 몸통이 제 이름에 묶여 있는지는 따로 봐야 한다."""
    text, side = extract(SWAPPY)
    with pytest.raises(ProseSwapError, match='다른 문단'):
        reinsert(SWAPPY, _swap_bodies(text, 'P001', 'P002'), side)


def test_부호만_반대인_문단끼리_맞바꿔도_거부된다():
    """+1.2%와 -1.2%를 같게 보면 숫자 검사를 그대로 통과한다."""
    text, side = extract(SWAPPY)
    with pytest.raises(ProseSwapError):
        reinsert(SWAPPY, _swap_bodies(text, 'P003', 'P004'), side)


def test_부호는_수치의_일부다():
    text, side = extract(SWAPPY)
    with pytest.raises(ProseSwapError, match='수치가 달라졌다'):
        reinsert(SWAPPY, text.replace('+1.2%', '-1.2%'), side)


def test_문단이_통째로_다른_말로_바뀌면_거부된다():
    text, side = extract(SWAPPY)
    broken = text.replace('연준은 신중한 태도를 유지하겠다는 뜻을 되풀이했다.',
                          '오늘 점심은 김치찌개였다.')
    with pytest.raises(ProseSwapError):
        reinsert(SWAPPY, broken, side)


def test_말투만_바꾼_것은_여전히_통과한다():
    text, side = extract(SWAPPY)
    out = reinsert(SWAPPY, text.replace('되풀이했다.', '되풀이했습니다.')
                               .replace('분위기다.', '분위기입니다.'), side)
    assert '되풀이했습니다' in out and '분위기입니다' in out


def test_인라인_자리표_순서가_뒤집히면_거부된다():
    text, side = extract(HTML)
    broken = text.replace('⟦0⟧-0.98%⟦1⟧', '⟦1⟧-0.98%⟦0⟧')
    with pytest.raises(ProseSwapError, match='자리표 순서'):
        reinsert(HTML, broken, side)


def test_문단_길이가_급변하면_거부된다():
    text, side = extract(SWAPPY)
    long = text.replace('분위기다.', '분위기다. ' + '같은 말을 계속 덧붙인다. ' * 12)
    with pytest.raises(ProseSwapError, match='길이'):
        reinsert(SWAPPY, long, side)


@pytest.mark.parametrize('bad,why', [
    ('- 목록 항목이다', '마크다운'),
    ('1. 번호 목록이다', '마크다운'),
    ('**굵게** 쓴 말이다', '마크다운'),
    ('[링크](https://example.com)다', '마크다운'),
    ('`코드`다', '마크다운'),
])
def test_마크다운_문법은_전부_거부된다(bad, why):
    text, side = extract(SWAPPY)
    broken = text.replace('시장은 이번 국면을 관망하며 다음 발표를 기다리는 분위기다.',
                          '시장은 이번 국면을 관망한다.\n' + bad)
    with pytest.raises(ProseSwapError, match=why):
        reinsert(SWAPPY, broken, side)


# ── 유사도만으로는 못 잡는 «사실 원자» ─────────────────────────────────────

FACTS = """<html><body>
<p>애플(AAPL)은 실적 기대에 힘입어 강세를 이어갔다.</p>
<p>테슬라(TSLA)는 인도량 우려에 약세를 보였다.</p>
<p>고용은 완만한 개선 흐름이고 물가는 완만한 둔화 국면이다.</p>
<p>자세한 내용은 <a href="https://www.federalreserve.gov/x">연준 보고서</a>와 노동부 자료에 있다.</p>
</body></html>"""


def test_티커를_문단끼리_맞바꾸면_거부된다():
    """각자 제 원문과는 여전히 닮았으므로 유사도로는 안 잡힌다."""
    text, side = extract(FACTS)
    broken = text.replace('애플(AAPL)', '애플(TSLA)').replace('테슬라(TSLA)', '테슬라(AAPL)')
    with pytest.raises(ProseSwapError, match='영문 이름·티커'):
        reinsert(FACTS, broken, side)


def test_판단_어휘를_뒤집으면_거부된다():
    """「완만한 개선」→「뚜렷한 악화」는 3-gram 유사도가 0.8을 넘는다."""
    text, side = extract(FACTS)
    broken = text.replace('완만한 개선', '뚜렷한 악화')
    with pytest.raises(ProseSwapError, match='판단 어휘'):
        reinsert(FACTS, broken, side)


def test_둔화를_가속으로_바꿔도_거부된다():
    text, side = extract(FACTS)
    with pytest.raises(ProseSwapError, match='판단 어휘'):
        reinsert(FACTS, text.replace('완만한 둔화', '완만한 가속'), side)


def test_링크가_다른_말에_가서_붙으면_거부된다():
    text, side = extract(FACTS)
    broken = text.replace('⟦0⟧연준 보고서⟦1⟧와 노동부 자료',
                          '연준 보고서와 ⟦0⟧노동부 자료⟦1⟧')
    with pytest.raises(ProseSwapError, match='링크가 감싼 말'):
        reinsert(FACTS, broken, side)


def test_사실을_그대로_둔_말투_변경은_통과한다():
    text, side = extract(FACTS)
    out = reinsert(FACTS, text.replace('이어갔다.', '이어갔습니다.')
                              .replace('보였다.', '보였습니다.'), side)
    assert 'AAPL' in out and 'TSLA' in out and '완만한 개선' in out


def test_홑별표_표기는_마크다운이_아니다():
    """`2Y*`는 이 프로젝트의 커브 차트 각주 표기다 (2026-08-25 실측에서 오탐)."""
    html = '<html><body><p>차트의 2Y*는 기준일 불일치를 나타낸 표기다.</p></body></html>'
    text, side = extract(html)
    assert reinsert(html, text.replace('표기다.', '표기입니다.'), side)


# ── 허용 범위는 문법·말투까지 ────────────────────────────────────────────

def test_절을_갈아끼우면_거부된다():
    """사실 검사를 다 통과해도, 원문에 없던 말로 절을 바꾸는 것은 이 단계 밖이다."""
    text, side = extract(SWAPPY)
    broken = text.replace('시장은 이번 국면을 관망하며 다음 발표를 기다리는 분위기다.',
                          '시장은 이번 국면을 관망한다고 보기는 어렵다고 판단된다.')
    with pytest.raises(ProseSwapError, match='문법·말투 이상'):
        reinsert(SWAPPY, broken, side)


def test_종결어미_교체는_통과한다():
    text, side = extract(SWAPPY)
    out = reinsert(SWAPPY, text.replace('되풀이했다.', '되풀이했습니다.'), side)
    assert '되풀이했습니다' in out


def test_주어를_되살리고_문장을_나눠도_통과한다():
    html = ('<html><body><p>장 초반 하락했다가 오후 들어 반등해 결국 강보합으로 '
            '마감했고 거래대금도 늘었다.</p></body></html>')
    text, side = extract(html)
    talk = text.replace('장 초반 하락했다가 오후 들어 반등해 결국 강보합으로 마감했고 거래대금도 늘었다.',
                        '지수는 장 초반 하락했습니다. 오후 들어 반등해 결국 강보합으로 '
                        '마감했고, 거래대금도 늘었습니다.')
    assert '지수는' in reinsert(html, talk, side)


FED_PAGE = ('<div class="card"><p>이 문단은 윤문 대상입니다. 오늘 시장은 조용했습니다.</p>'
            '<div class="fed-quote" data-fed-quote="fomc-statement-20260729">'
            '<blockquote>The economy is showing impressive resilience.</blockquote>'
            '<p class="fed-trans">경제가 인상적인 회복력을 보이고 있다고 했습니다.</p>'
            '<p class="caption">출처: 기자회견 전문</p></div>'
            '<div data-fed-idea="1"><p>이 문단도 윤문 대상입니다. 커브는 눕는 쪽입니다.</p></div>'
            '</div>')


def test_fed_quote_block_is_never_handed_to_the_humanizer():
    # 원문 대조를 통과해야 하는 글이라 말투를 다듬는 순간 발행이 막힌다.
    payload, _ = extract(FED_PAGE)
    assert '회복력을 보이고 있다고' not in payload
    assert 'impressive resilience' not in payload
    assert '오늘 시장은 조용했습니다' in payload
    assert '커브는 눕는 쪽입니다' in payload


def test_fed_change_block_is_skipped_too():
    page = ('<p>바깥 문단입니다. 시장은 조용했습니다.</p>'
            '<div data-fed-change="1"><p>The Committee is continuing its policy. '
            '「reaffirmed」가 바뀌었습니다.</p></div>'
            '<p>그다음 문단입니다. 커브가 섰습니다.</p>')
    payload, _ = extract(page)
    assert 'reaffirmed' not in payload
    assert '바깥 문단입니다' in payload and '그다음 문단입니다' in payload


def test_nested_divs_do_not_swallow_the_rest_of_the_page():
    page = ('<div data-fed-quote="k"><div class="inner">'
            '<blockquote>Verbatim words here.</blockquote>'
            '<p class="fed-trans">번역입니다.</p></div></div>'
            '<p>뒤 문단은 윤문 대상입니다. 커브가 섰습니다.</p>')
    payload, _ = extract(page)
    assert 'Verbatim words' not in payload and '번역입니다' not in payload
    assert '뒤 문단은 윤문 대상입니다' in payload


def test_generated_research_summary_is_not_sent_for_humanization():
    html = '<p>시장 설명은 다듬는다.</p><section data-research-summary="hash"><p>검토 대상 17건입니다.</p></section>'
    text, side = extract(html)
    assert '시장 설명' in text
    assert '검토 대상' not in text
    assert reinsert(html, text, side) == html


# ── 문단 단위 되꽂기 (발행 뒤 codex 문체 수정, 2026-09-27 사용자 지시) ─────────────
# 한 문단이 닮은 정도 0.79 로 걸려 수십 문단의 수정이 통째로 버려졌다. 걸린 문단만
# 원문으로 두고 나머지는 반영한다. 문단마다의 검사는 그대로다.

from us.prose_swap import reinsert_partial  # noqa: E402


def test_부분_되꽂기는_걸린_문단만_원문으로_둔다():
    text, side = extract(SWAPPY)
    edited = (text.replace('되풀이했다.', '되풀이했습니다.')
                  .replace('시장은 이번 국면을 관망하며 다음 발표를 기다리는 분위기다.',
                           '오늘 점심은 김치찌개였다.'))
    out, rejected = reinsert_partial(SWAPPY, edited, side)
    assert '되풀이했습니다' in out
    assert '시장은 이번 국면을 관망하며 다음 발표를 기다리는 분위기다.' in out
    assert '김치찌개' not in out
    assert [pid for pid, _ in rejected] == ['P002']


def test_부분_되꽂기도_수치가_바뀐_문단은_반영하지_않는다():
    text, side = extract(SWAPPY)
    out, rejected = reinsert_partial(SWAPPY, text.replace('+1.2%', '+1.3%')
                                     .replace('밀렸다.', '밀렸습니다.'), side)
    assert '+1.2%' in out and '+1.3%' not in out and '밀렸습니다' in out
    assert [pid for pid, _ in rejected] == ['P003']


def test_부분_되꽂기는_맞바꾼_문단을_둘_다_원문으로_둔다():
    text, side = extract(SWAPPY)
    out, rejected = reinsert_partial(SWAPPY, _swap_bodies(text, 'P001', 'P002'), side)
    assert out == SWAPPY
    assert sorted(pid for pid, _ in rejected) == ['P001', 'P002']


def test_부분_되꽂기에서_빠진_문단과_모르는_이름은_원문이다():
    text, side = extract(SWAPPY)
    blocks = text.strip().split('\n\n')
    edited = '\n\n'.join(blocks[1:] + ['[[P999]]\n엉뚱한 문단.']).replace('분위기다.', '분위기입니다.')
    out, rejected = reinsert_partial(SWAPPY, edited, side)
    assert '분위기입니다' in out and '되풀이했다.' in out
    assert 'P999' in [pid for pid, _ in rejected]


def test_부분_되꽂기에서_마크다운이_섞인_문단만_원문이다():
    text, side = extract(SWAPPY)
    edited = text.replace('되풀이했다.', '**되풀이**했다.').replace('분위기다.', '분위기입니다.')
    out, rejected = reinsert_partial(SWAPPY, edited, side)
    assert '되풀이했다.' in out and '분위기입니다' in out
    assert [pid for pid, _ in rejected] == ['P001']


def test_부분_되꽂기도_다른_HTML의_사이드카는_통째로_거부한다():
    text, side = extract(SWAPPY)
    with pytest.raises(ProseSwapError):
        reinsert_partial(HTML, text, side)


# ── 부분 되꽂기의 추가 검사 (2026-09-30 codex 구현 검토) ──────────────────────────
# 사람이 보지 않는 자동 경로라 개수만 맞추는 검사로는 모자란다. 아래 넷은 전부
# 개수·유사도 검사를 통과하던 편집이다(재현 후 추가).

def _one(sentence):
    return ('<html><body><div class="card"><p>' + sentence + '</p>'
            '<p>S&amp;P 500 은 0.4% 올랐다.</p></div></body></html>')


def _partial(before, after, names=()):
    html = _one(before)
    text, side = extract(html)
    return reinsert_partial(html, text.replace(before, after), side, names=names)


def test_부분_되꽂기는_수치의_순서가_바뀐_문단을_원문으로_둔다():
    out, rejected = _partial('금리는 100에서 200으로 올랐고 시장은 이를 경계했다.',
                             '금리는 200에서 100으로 올랐고 시장은 이를 경계했다.')
    assert '100에서 200으로' in out and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_방향이_뒤집힌_문단을_원문으로_둔다():
    out, rejected = _partial('유가가 오르면서 지수가 상승할 가능성이 커졌다고 본다.',
                             '유가가 오르면서 지수가 하락할 가능성이 커졌다고 본다.')
    assert '상승할' in out and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_부정이_빠진_문단을_원문으로_둔다():
    out, rejected = _partial('수출 기업은 환율 상승의 덕을 크게 보지 않았다고 판단한다.',
                             '수출 기업은 환율 상승의 덕을 크게 보았다고 판단한다.')
    assert '않았다' in out and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_아는_이름이_바뀐_문단을_원문으로_둔다():
    out, rejected = _partial('삼성전자 실적이 시장 기대를 웃돌았다고 판단한다.',
                             '현대전자 실적이 시장 기대를 웃돌았다고 판단한다.',
                             names=('삼성전자',))
    assert '삼성전자' in out and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_같은_방향의_말바꿈은_받는다():
    out, rejected = _partial('유가가 올랐고 그래서 에너지 업종이 강세를 보인 것으로 나타났다.',
                             '유가가 올랐고 그래서 에너지 업종이 강세를 보였다.',
                             names=('에너지',))
    assert '강세를 보였다' in out and rejected == []


def test_부분_되꽂기는_넘겨받은_사이드카가_아니라_HTML_을_기준으로_본다():
    """codex 는 작업 폴더에 쓰기 권한이 있다 — 사이드카의 기대값을 고쳐 판단 어휘를 뒤집을 수 있었다."""
    html = _one('경기는 개선 흐름이라고 판단한다.')
    text, side = extract(html)
    forged = json.loads(json.dumps(side))
    for rec in forged['items'].values():
        if rec.get('controlled'):
            rec['controlled'] = {'악화': 1}
    out, rejected = reinsert_partial(html, text.replace('개선', '악화'), forged)
    assert '개선' in out and '악화' not in out
    assert [p for p, _ in rejected] == ['P001']


# ── 재검토(2026-09-30) ─────────────────────────────────────────────────────────

def test_부분_되꽂기는_독립된_안이_빠진_문단을_원문으로_둔다():
    out, rejected = _partial('지금은 주식 비중을 늘리면 안 된다고 판단한다.',
                             '지금은 주식 비중을 늘리면 된다고 판단한다.')
    assert '안 된다' in out and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_이름과_방향의_짝이_바뀐_문단을_원문으로_둔다():
    out, rejected = _partial('삼성전자는 상승했고 현대차는 하락했다. 반도체 업황 회복 기대와 환율 부담이 엇갈린 하루였고 외국인 수급도 종목별로 크게 갈렸다고 판단한다.',
                             '현대차는 상승했고 삼성전자는 하락했다. 반도체 업황 회복 기대와 환율 부담이 엇갈린 하루였고 외국인 수급도 종목별로 크게 갈렸다고 판단한다.',
                             names=('삼성전자', '현대차'))
    assert out.index('삼성전자') < out.index('현대차') and [p for p, _ in rejected] == ['P001']


def test_부분_되꽂기는_영문_이름과_방향의_짝도_본다():
    out, rejected = _partial('AAPL 은 상승했고 TSLA 는 하락했다. 반도체 업황 회복 기대와 환율 부담이 엇갈린 하루였고 외국인 수급도 종목별로 크게 갈렸다고 판단한다.',
                             'TSLA 는 상승했고 AAPL 은 하락했다. 반도체 업황 회복 기대와 환율 부담이 엇갈린 하루였고 외국인 수급도 종목별로 크게 갈렸다고 판단한다.')
    assert [p for p, _ in rejected] == ['P001']


# ── 기간 리포트 (2026-10-01 codex 설계 검토) ─────────────────────────────────────

def test_중첩된_연구_요약도_윤문에_넘기지_않는다():
    """KR W39: 요약 section 이 바깥 section 안에 있어 _BLOCK_RE 가 바깥만 잡고 요약 문단을 넘겼다."""
    html = ('<section class="card"><h2>복기</h2><p>이번 주 판단을 돌아본다.</p>'
            '<section data-research-summary="h"><p>검토 대상 2건이다.</p></section>'
            '<p>다음 주에 확인할 조건이 있다.</p></section>')
    text, side = extract(html)
    assert '검토 대상' not in text
    assert '돌아본다' in text and '확인할 조건' in text
    assert reinsert(html, text, side) == html


def test_실제_KR_W39_의_연구_요약은_추출되지_않는다():
    import os
    path = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'kr', 'weekly', '2026-W39.html')
    html = open(path, encoding='utf-8').read()
    text, _ = extract(html)
    assert '검토 대상' not in text
