from scripts.us import readability as R


DOC = """<html><head><style>
body { line-height: 1.58; }
p { font-size: 16px; margin: 0 0 9px; }
</style></head><body>
<div class="card"><p>코스피는 20일선을 웃돌아 마감했다. 상승 폭은 제한적이었다.</p></div>
<table><tr><td>6,460.71</td></tr></table>
</body></html>"""


def test_inject_is_idempotent():
    once = R.inject_css(DOC)
    twice = R.inject_css(once)
    assert once.count(R.MARKER) == 1
    assert once == twice
    assert R.has_override(once)


def test_inject_goes_inside_last_style_block():
    out = R.inject_css(DOC)
    assert out.index(R.MARKER) < out.index("</style>")
    assert "max-width: 42em" in out


def test_inject_without_style_block():
    out = R.inject_css("<html><head></head><body><p>a</p></body></html>")
    assert "<style>" in out and R.has_override(out)


def test_inject_preserves_body():
    out = R.inject_css(DOC)
    assert "코스피는 20일선을 웃돌아 마감했다." in out
    assert "6,460.71" in out


def test_migrate_v2_css():
    old = DOC.replace("</style>", R._V2_CSS + "</style>")
    out = R.inject_css(old)
    assert R.MARKER in out and R.OLD_MARKER not in out


def test_split_dense_paragraphs_preserves_text_and_numbers():
    para = "첫 문장은 10을 설명한다. 둘째 문장은 20을 설명한다. 셋째 문장은 30을 설명한다. 넷째 문장은 40을 설명한다. " * 3
    doc = "<html><body><p>%s</p></body></html>" % para
    out = R.split_dense_paragraphs(doc, limit=100)
    assert out.count("<p>") > 1
    assert "<p></p>" not in out and out.count("<p>") == out.count("</p>")
    assert R.visible_numeric_tokens(out) == R.visible_numeric_tokens(doc)


def test_reading_map_is_idempotent_and_adds_section_ids():
    doc = "<html><body><div class='doc'><section><h1>제목</h1></section>" + "".join(
        "<section><h2>%s</h2><p>본문이다.</p></section>" % x
        for x in ("전략 코멘트", "주식", "채권", "매크로 논리", "주목 섹터·종목")
    ) + "</div></body></html>"
    once = R.inject_reading_map(doc)
    twice = R.inject_reading_map(once)
    assert once == twice
    assert R.READING_MAP_MARKER in once
    assert 'href="#read-' in once


def test_strategy_moves_after_reading_map_without_number_changes():
    doc = (
        "<html><body><div class='doc'><section><h1>제목</h1><p>지수는 10이다.</p></section>"
        "<section><h2>주식</h2><p>주식은 20이다.</p></section>"
        "<section><h2>전략 코멘트</h2><p>비중은 30이다.</p></section>"
        "<section><h2>채권</h2><p>채권은 40이다.</p></section></div></body></html>"
    )
    mapped = R.inject_reading_map(doc)
    out = R.move_strategy_first(mapped)
    assert out.index(R.STRATEGY_FIRST_MARKER) < out.index("<h2>주식</h2>")
    assert out.index("</nav>") < out.index(R.STRATEGY_FIRST_MARKER)
    assert R.move_strategy_first(out) == out
    assert sorted(R.visible_numeric_tokens(out)) == sorted(R.visible_numeric_tokens(doc))


def test_paragraphs_skip_tables_and_style():
    ps = R.paragraphs(DOC)
    assert len(ps) == 1
    assert "6,460.71" not in ps[0]
    assert "line-height" not in ps[0]


def test_sentences_split_on_korean_ending():
    assert len(R.sentences(DOC)) == 2


def test_figures_ignore_years():
    assert R.figures("2026년 8월 21일 종가는 6,912.95였다") == ["6,912.95"]


def test_figures_ignore_clock_times_and_short_dates():
    assert R.figures("7/29 회의 뒤 10:30 ET에 지수는 6,912.95였다") == ["6,912.95"]


def test_figures_ignore_chart_and_tenor_labels():
    assert R.figures("30분봉과 20일선, 10년물을 비교하면 종가는 6,912.95였다") == ["6,912.95"]


def test_first_heading_strips_markup():
    assert R.first_heading("<h1>시장 <strong>반등</strong></h1>") == "시장 반등"


def test_long_sentences():
    doc = "<p>%s다.</p>" % ("가" * 130)
    assert R.long_sentences(doc, limit=120)
    assert not R.long_sentences(doc, limit=200)


def test_dense_sentences_counts_figures():
    doc = "<p>지수는 6,912.95로 +0.88% 올랐고 20일선 6,460.71을 7.0% 웃돌며 60일선 7,477.31에는 7.55% 못 미쳤고 볼린저 상단 7,215.16에 근접했다.</p>"
    hits = R.dense_sentences(doc, limit=6)
    assert hits and hits[0][1] >= 7


def test_overprecise_flags_won_moving_averages():
    doc = "<p>60일 이동평균선은 2,043,966.67원이라고 본문에 적혀 있었다.</p>"
    assert R.overprecise(doc) == ["2,043,966.67원"]


def test_overprecise_spares_real_quotes():
    doc = "<p>금은 오늘 큰 폭으로 올라 온스당 4,661.60에 마감하며 최고치를 새로 썼다.</p>"
    assert R.overprecise(doc) == []
    assert R.loosely_precise(doc) == ["4,661.60"]


def test_overprecise_ignores_tables():
    doc = "<table><tr><td>2,043,966.67</td></tr></table>"
    assert R.overprecise(doc) == []


def test_echoed_figures():
    doc = "".join(f"<p>금 가격은 오늘 {w}하며 +3.22% 올라 최고치를 새로 썼다.</p>" for w in ("급등", "상승", "반등", "강세"))
    assert ("+3.22%", 4) in R.echoed_figures(doc, limit=3)


def test_measure_reports_shape():
    m = R.measure(DOC)
    assert m["sentences"] == 2 and "p90_len" in m and "p90_para_len" in m


def test_inject_ignores_inline_body_style():
    doc = (
        "<html><head><style>p{margin:0}</style></head><body>"
        "<div class='card'><style>.spf{color:red}</style><p>본문</p></div></body></html>"
    )
    out = R.inject_css(doc)
    assert out.index(R.MARKER) < out.index("</head>")
    assert ".spf{color:red}</style>" in out
