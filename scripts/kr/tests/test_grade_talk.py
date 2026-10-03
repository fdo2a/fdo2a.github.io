"""노출 등급 말투 — 본문에서 막고 원장에만 남긴다 (2026-10-04 사용자 결정).

양성은 KR 발행본에 실제로 실린 문장, 음성은 같은 낱말의 정당한 용례다. 변형은 선언형의
경계를 고정한다 — 좁게 잡은 대가로 남는 미탐도 테스트로 적어 둔다.
"""
import pytest

from kr.grade_talk import find, violations


def page(*paras, news=None):
    body = "".join(f"<p>{p}</p>" for p in paras)
    if news is not None:
        body += ('<h2>오늘의 뉴스</h2><div class="news-item" data-news="001-1">'
                 f'<p class="news-head">제목</p><p>{news}</p></div>')
    return f'<html><body data-register="da"><h1>제목</h1>{body}</body></html>'


@pytest.mark.parametrize("sentence", [
    "코스피 노출은 다음 세션까지 유지하고, 정유주는 추격하지 않고 관찰에 둔다.",   # 10/02
    "위험 노출은 다음 세션까지 축소한다.",
    "전력기기·반도체 중심의 위험 노출은 다음 세션까지 확대한다.",
    "노출 등급은 유지하되 두 가지를 고친다.",
    "매도가 대형 반도체 밖으로 번졌다고 보고, 노출 유지의 전제를 거둔다.",
    "이번 주 노출 유지는 근거를 세 번 바꾸며 유지됐다.",
    "주체가 회사에서 시장으로 넘어갔다는 뜻이라, 노출을 늘릴 근거가 된다.",
    "흔들리고 있다는 뜻이라 지금은 노출을 늘릴 때가 아니다.",
    "자사주 공시에 기댄 하루짜리 되돌림으로 보고 노출을 줄인다.",
    "코스피가 60일 이동평균을 지키는 동안 노출을 유지한다고 썼다.",
    "위험 노출도 유지한다.",
    "위험 노출을 줄였다.",
    "위험 노출은 다음 세션까지 0.5배로 유지한다.",
    "위험 노출은 반도체 재고 감소가 확인될 때까지 유지한다.",
])
def test_grade_declarations_are_caught(sentence):
    assert find(page(sentence)), sentence


@pytest.mark.parametrize("sentence", [
    "반도체·자동차 등 대미 노출이 큰 업종의 이익 전망 가시성이 높아진다.",
    "시장은 10월 금통위까지 국채 금리·환율 변동성에 그대로 노출된다.",
    "지수 하락을 증폭시키는 구조가 노출됐다는 평가다.",
    "중국군사기업으로 지정돼 규제 위험에 노출돼 있었다.",
    "대미 노출을 줄인 기업은 국내 생산을 유지했다.",
    "규제 위험 노출을 줄인 기업이 많다.",
    "행사 노출은 반등의 맥락을 제공하지만 실적 전망은 유지됐다.",
    "코스피는 20일 이동평균 위를 지켰다.",
    "위험 노출은 제한적이고 국내 생산은 유지했다.",     # 다른 절의 동사
    "위험 노출은 줄었고 국내 생산은 유지했다.",
    "재고 노출을 줄인 기업은 국내 생산을 유지했다.",   # 어미처럼 끝나는 명사
])
def test_ordinary_uses_pass(sentence):
    assert find(page(sentence)) == [], sentence


def test_known_misses_are_left_to_the_writer_contract():
    # 수식어 뒤 맨 「노출」과 주어 없는 먼 동사는 정당한 용례와 갈리지 않는다 — 지시문이 맡는다.
    assert find(page("노출은 다음 세션까지 0.5배로 유지한다.")) == []
    assert find(page("시계는 다음 세션이다.")) == []


def test_headline_card_and_title_are_read():
    html = ('<html><body data-register="da"><h1>위험 노출은 다음 세션까지 유지한다</h1>'
            '<p class="muted">코스피 노출은 유지하고 정유주는 관찰한다.</p></body></html>')
    assert len(find(html)) == 2


def test_news_items_are_exempt_only_in_the_news_section_when_asked():
    html = page("오늘은 반도체가 쉬었다.", news="코스피 노출을 확대한다는 보고서가 나왔다.")
    assert find(html, exempt_news=True) == []
    assert find(html) != []
    fake = page('<span>x</span>') .replace(
        '<p><span>x</span></p>',
        '<div data-news="fake"><p>위험 노출은 유지한다.</p></div>')
    assert find(fake, exempt_news=True) != []   # 뉴스 구간 밖의 data-news 는 면제가 아니다


def test_provenance_block_is_skipped():
    html = page("오늘은 반도체가 쉬었다.").replace(
        "</body>", "<details data-provenance><summary>계산 근거</summary>"
                   "<p>위험 노출은 유지한다.</p></details></body>")
    assert find(html) == []


def test_message_quotes_only_the_matched_span():
    v = violations(page("어제와 같이, 위험 노출은 다음 세션까지 축소한다. 이유는 셋이다."))
    assert len(v) == 1 and "「위험 노출은 다음 세션까지 축소」" in v[0]


@pytest.mark.parametrize("fragment", [
    "위험 노출은<br>다음 세션까지 유지한다.",
    "위험 노출은\n다음 세션까지 유지한다.",
    "노출<br>등급은 유지한다.",
    "보고 노출은<strong>유지</strong>한다.",
])
def test_markup_and_source_newlines_do_not_hide_a_declaration(fragment):
    assert find(page(fragment)), fragment


def _news_page(item, after=""):
    return ('<html><body data-register="da"><section><h2>오늘의 뉴스</h2>'
            f'{item}</section>{after}</body></html>')


def test_nested_news_item_is_exempt_whole():
    item = ('<div class="news-item" data-news = "001-1"><div class="inner">'
            '<p>요약 첫 문장.</p></div><p>위험 노출은 유지한다는 보고서가 나왔다.</p></div>')
    assert find(_news_page(item), exempt_news=True) == []


def test_exemption_stops_at_the_news_section():
    item = '<div class="news-item" data-news="001-1"><p>평범한 요약.</p></div>'
    after = '<section><p>본문</p><div data-news="x"><p>위험 노출은 유지한다.</p></div></section>'
    assert find(_news_page(item, after), exempt_news=True) != []
