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


def test_paragraphs_skip_tables_and_style():
    ps = R.paragraphs(DOC)
    assert len(ps) == 1
    assert "6,460.71" not in ps[0]
    assert "line-height" not in ps[0]


def test_sentences_split_on_korean_ending():
    assert len(R.sentences(DOC)) == 2


def test_figures_ignore_years():
    assert R.figures("2026년 8월 21일 종가는 6,912.95였다") == ["6,912.95"]


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
    assert m["sentences"] == 2 and "p90_len" in m


def test_inject_ignores_inline_body_style():
    doc = (
        "<html><head><style>p{margin:0}</style></head><body>"
        "<div class='card'><style>.spf{color:red}</style><p>본문</p></div></body></html>"
    )
    out = R.inject_css(doc)
    assert out.index(R.MARKER) < out.index("</head>")
    assert ".spf{color:red}</style>" in out
