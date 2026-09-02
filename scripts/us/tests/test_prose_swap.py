"""prose_swap — 이름으로 되꽂기가 실제로 거부해야 할 것을 거부하는가."""

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
