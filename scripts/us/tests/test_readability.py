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


def test_desktop_block_widens_prose_and_keeps_mobile_measure():
    out = R.inject_css(DOC)
    assert "@media (min-width: 1024px)" in out
    desktop = out.split("@media (min-width: 1024px)", 1)[1]
    # v5: 데스크톱에서는 폭 제한을 걷어 카드를 다 쓴다. 기본 조판은 42em 그대로.
    assert "max-width: none" in desktop
    assert "font-size: %s" % R.DESKTOP_FONT in desktop
    base = out.split("@media (min-width: 1024px)", 1)[0]
    assert "max-width: 42em" in base


def test_desktop_font_bump_skips_classed_paragraphs():
    """`.caption`·`.note`는 제 크기를 지킨다.

    `.card p`(0,1,1)가 `.caption`(0,1,0)을 이기므로 font-size를 무조건 얹으면
    12.5px 캡션이 본문 크기로 튀어오른다. `:not([class])`로 막는다.
    """
    out = R.inject_css(DOC)
    desktop = out.split("@media (min-width: 1024px)", 1)[1]
    for line in desktop.splitlines():
        if "font-size" in line and " p" in line:
            assert ":not([class])" in line, line


def test_migrate_v3_css_to_v4():
    old = DOC.replace("</style>", R._V3_CSS + "</style>")
    out = R.inject_css(old)
    assert R.MARKER in out
    assert out.count(R.MARKER) == 1
    assert R.V3_MARKER not in out
    assert "@media (min-width: 1024px)" in out


def test_migrate_v2_straight_to_v4():
    old = DOC.replace("</style>", R._V2_CSS + "</style>")
    out = R.inject_css(old)
    assert R.MARKER in out and R.OLD_MARKER not in out and R.V3_MARKER not in out


BAD_SPECIFICITY = """<html><head><style>
.card p, p { font-size:16px; line-height:1.62; color:#191F28; margin:0 0 9px; }
.caption { color:#8B95A1; font-size:12.5px; }
</style></head><body>
<div class="card"><p>본문이다.</p><p class="caption">출처: Naver.</p></div>
</body></html>"""


def test_demote_card_p_font_keeps_bare_p_rule():
    """`.card p`(0,1,1)가 `.caption`(0,1,0)을 이겨 12.5px 캡션이 16px로 뜬다.

    실측 2026-08-26: KR 발행본 5편과 US 5편이 이 선택자를 썼고, 그 글들만
    캡션·각주가 본문 크기로 인쇄됐다. 한정 선택자를 떨어내면 맨 `p`가 그대로
    본문을 맡고 클래스 붙은 문단은 제 크기를 되찾는다.
    """
    out = R.demote_card_p_font(BAD_SPECIFICITY)
    assert ".card p, p { font-size" not in out
    assert "p { font-size:16px; line-height:1.62; color:#191F28; margin:0 0 9px; }" in out
    assert ".caption { color:#8B95A1; font-size:12.5px; }" in out


def test_demote_card_p_font_is_idempotent():
    once = R.demote_card_p_font(BAD_SPECIFICITY)
    assert R.demote_card_p_font(once) == once


def test_demote_card_p_font_leaves_rules_without_font_size():
    """폭·줄간격만 정하는 v4 조판 규칙은 캡션 크기를 건드리지 않으므로 남긴다."""
    doc = "<html><head><style>.card p, .doc p, p { line-height: 1.78; max-width: 42em; }" \
          "</style></head><body><p>a</p></body></html>"
    assert R.demote_card_p_font(doc) == doc


def test_demote_card_p_font_keeps_rule_without_bare_p():
    """맨 `p`가 없으면 규칙 전체가 사라지므로 손대지 않는다."""
    doc = "<html><head><style>.card p { font-size:16px; }</style></head>" \
          "<body><p>a</p></body></html>"
    assert R.demote_card_p_font(doc) == doc


def test_enhance_runs_demote_and_preserves_numbers():
    out = R.enhance_html(BAD_SPECIFICITY)
    assert ".card p, p { font-size" not in out
    assert R.visible_numeric_tokens(out) == R.visible_numeric_tokens(BAD_SPECIFICITY)


def test_demote_preserves_complex_selector_commas_and_rule_spacing():
    doc = """<html><head><style>
.previous { color:red; }
.card p, p, [data-x="a,b"], :not(.a,.b) { font-size:16px; }
</style></head><body><p>a</p></body></html>"""
    expected = """<html><head><style>
.previous { color:red; }
p, [data-x="a,b"], :not(.a,.b) { font-size:16px; }
</style></head><body><p>a</p></body></html>"""
    assert R.demote_card_p_font(doc) == expected


def test_demote_preserves_media_wrapper_and_indentation():
    doc = """<html><head><style>
@media screen and (min-width:1024px) {
  .card p, p { font-size:16px; }
}
</style></head><body><p>a</p></body></html>"""
    expected = """<html><head><style>
@media screen and (min-width:1024px) {
  p { font-size:16px; }
}
</style></head><body><p>a</p></body></html>"""
    assert R.demote_card_p_font(doc) == expected


def test_demote_ignores_inline_body_style():
    doc = """<html><head><style>
.card p, p { font-size:16px; }
</style></head><body><style>
.card p, p { font-size:12px; }
</style><p>a</p></body></html>"""
    out = R.demote_card_p_font(doc)
    assert "\np { font-size:16px; }" in out
    assert "\n.card p, p { font-size:12px; }" in out


def test_demote_handles_literal_brace_in_declaration():
    doc = """<html><head><style>
.card p, p { font-size:16px; content:"{"; }
</style></head><body><p>a</p></body></html>"""
    out = R.demote_card_p_font(doc)
    assert "\np { font-size:16px; content:\"{\"; }" in out


def test_migrate_v3_css_with_marker_whitespace():
    variant = R._V3_CSS.replace(R.V3_MARKER, "/*  readability-v3*/", 1)
    old = DOC.replace("</style>", variant + "</style>")
    out = R.inject_css(old)
    assert out.count("readability-v3") == 0
    assert out.count(R.MARKER) == 1
    assert R.inject_css(out) == out


# head 안의 <script>가 마커 문자열을 품고 있어도 CSS로 오인하지 않아야 한다.
# 지금 발행본 29+23편에는 없지만, JSON-LD·광고 로더가 head에 있으므로
# 언젠가 문자열이 섞이면 마크업이 깨진다. 검출은 실제 <style> 안에서만 한다.
SCRIPT_DECOY = """<html><head>
<script type="application/ld+json">
{"description":"조판 이력: /* readability-v3 */ 를 </style> 앞에 넣었다"}
</script>
<style>
p { font-size: 16px; }
</style></head><body><div class="card"><p>본문이다. 6,460.71로 마감했다.</p></div></body></html>"""


def test_marker_search_ignores_script_text():
    out = R.inject_css(SCRIPT_DECOY)
    # 스크립트 안 문자열은 CSS가 아니다 — 마이그레이션 경로로 새면 JSON-LD가 잘린다.
    # 마커 뒤쪽까지 온전해야 실제로 안 건드린 것이다.
    assert '{"description":"조판 이력: /* readability-v3 */ 를 </style> 앞에 넣었다"}' in out
    assert out.count(R.MARKER) == 1
    assert R.CSS.strip() in out
    # 진짜 CSS(<style> 안)에 붙어야 한다 — 스크립트 자리가 아니라.
    assert out.index("<style>") < out.index(R.MARKER)


def test_has_override_ignores_script_text():
    decoy = SCRIPT_DECOY.replace("readability-v3", "readability-v4")
    assert not R.has_override(decoy)


def test_script_decoy_is_idempotent_and_keeps_numbers():
    once = R.enhance_html(SCRIPT_DECOY)
    twice = R.enhance_html(once)
    assert once == twice
    assert R.visible_numeric_tokens(once) == R.visible_numeric_tokens(SCRIPT_DECOY)


# script 안에 여는 <style>이나 </head>가 통째로 들어 있는 경우.
# 위 SCRIPT_DECOY는 닫는 </style>만 있어서 이 갈래를 못 덮었다.
FULL_TAG_DECOY = """<html><head>
<script>var t = "<style>/* readability-v4 */</style>"; var u = "</head>";</script>
<style>
p { font-size: 16px; }
</style></head><body><div class="card"><p>본문이다. 6,460.71로 마감했다.</p></div></body></html>"""


def test_style_spans_ignore_tags_inside_script():
    assert not R.has_override(FULL_TAG_DECOY)
    out = R.inject_css(FULL_TAG_DECOY)
    # 스크립트 문자열은 한 글자도 안 바뀐다.
    assert 'var t = "<style>/* readability-v4 */</style>"; var u = "</head>";' in out
    # 스크립트 안 미끼 문자열이 그대로 남아 있으니 문서 전체 개수는 2다.
    # (`</head>`도 스크립트 안에 먼저 나오므로 index로 자르면 안 된다.)
    # 세어야 하는 것은 스크립트 뒤 — 진짜 CSS — 에 정확히 하나 있느냐다.
    after_script = out.split("</script>", 1)[1]
    assert after_script.count(R.MARKER) == 1
    assert R.CSS.strip() in after_script


def test_head_scope_ignores_head_close_inside_script():
    """`</head>` 문자열이 스크립트 안에 있으면 그것을 head 끝으로 삼지 않는다."""
    assert R._head_scope_end(FULL_TAG_DECOY) > FULL_TAG_DECOY.index("</script>")


def test_full_tag_decoy_idempotent_and_numbers_intact():
    once = R.enhance_html(FULL_TAG_DECOY)
    assert R.enhance_html(once) == once
    assert R.visible_numeric_tokens(once) == R.visible_numeric_tokens(FULL_TAG_DECOY)


# 진짜 <style>이 하나도 없는 문서 + 스크립트 안 </head> 미끼.
# FULL_TAG_DECOY는 진짜 style이 있어서 「style 없을 때」 갈래를 못 덮었다.
NO_STYLE_DECOY = """<html><head>
<script>var u = "</head>"; var t = "<style>.card p, p { font-size:16px; }</style>";</script>
</head><body><div class="card"><p>본문이다. 6,460.71로 마감했다.</p></div></body></html>"""


def test_inject_without_style_does_not_write_into_script():
    out = R.inject_css(NO_STYLE_DECOY)
    assert 'var u = "</head>";' in out
    assert R.MARKER in out.split("</script>", 1)[1]


def test_demote_does_not_edit_style_string_inside_script():
    out = R.demote_card_p_font(NO_STYLE_DECOY)
    assert '"<style>.card p, p { font-size:16px; }</style>"' in out


def test_enhance_leaves_script_decoy_intact():
    out = R.enhance_html(NO_STYLE_DECOY)
    assert 'var u = "</head>";' in out
    assert '.card p, p { font-size:16px; }</style>";' in out
    assert R.enhance_html(out) == out


def test_desktop_prose_fills_the_card_instead_of_stopping_short():
    """2026-08-28 사용자 지시 — PC에서 문장이 카드 폭을 다 쓰게. 50em에서 멈추면
    1120px 카드의 오른쪽이 늘 빈다."""
    block = R.CSS.split("@media (min-width: 1024px)")[1]
    assert "max-width: none" in block
    assert "50em" not in block
    # 모바일·태블릿 기본 조판은 그대로 42em이다.
    assert "max-width: 42em" in R.CSS


def test_labels_sit_on_their_own_line_above_the_body():
    assert ".box-label { display: block" in R.CSS
    assert "width: fit-content" in R.CSS
    assert ".p-label { display: block" in R.CSS


def test_strong_label_is_promoted_to_a_block():
    html = "<p><strong>오늘의 행동.</strong> 축소합니다 — 메모리를 중립으로.</p>"
    out = R.block_labels(html)
    assert '<strong class="p-label">오늘의 행동.</strong> 축소합니다' in out


def test_strong_first_sentence_stays_inline():
    """마침표가 <strong> 바깥이면 라벨이 아니라 강조된 첫 문장이다."""
    html = "<p><strong>엔비디아가 하루를 지배했습니다</strong>. +8.74%로 마감했습니다.</p>"
    assert R.block_labels(html) == html
    html2 = "<p><strong>고용은 개선 쪽이다.</strong> 일곱 중 다섯이 좋아졌다.</p>"
    assert R.block_labels(html2) == html2


def test_block_labels_is_idempotent():
    html = "<p><strong>무효화 조건.</strong> 20일 초과수익이 +5.0%포인트를 넘으면.</p>"
    once = R.block_labels(html)
    assert R.block_labels(once) == once


def test_migrate_v4_css_to_v5():
    html = "<html><head><style>body{}\n%s\n.card p { max-width: 42em; }</style></head><body><p>a</p></body></html>" % R.V4_MARKER
    out = R.inject_css(html)
    assert R.MARKER in out
    assert out.count(R.MARKER) == 1
    assert R.has_override(out)


def test_colon_labels_are_promoted_too():
    """2026-08-28 codex 검토 — 마침표만 보다가 「동인:」류 34건을 놓쳤다."""
    html = "<p><strong>동인:</strong> 오늘 장의 단일 최대 동인은 미-이란 양해각서였다.</p>"
    assert 'class="p-label">동인:' in R.block_labels(html)


def test_bare_subject_with_a_particle_stays_inline():
    """`<strong>코스피</strong>는 종가…`는 라벨이 아니라 문장의 주어다."""
    html = "<p><strong>코스피</strong>는 종가 7,096.89포인트로 MA20을 밑돈다.</p>"
    assert R.block_labels(html) == html


def test_label_keeps_the_space_before_the_body_text():
    """블록이라 화면에서는 안 보이지만, 복사·평문 추출에서는 붙어 나온다."""
    out = R.block_labels("<p><strong>동인.</strong> 오늘 장의 최대 동인은.</p>")
    assert "</strong> 오늘" in out


def test_inline_styled_box_labels_are_unpinned():
    """인라인 style="display:inline"은 시트를 이긴다 — 소급 판 34건이 그랬다."""
    html = '<p><span class="box-label" style="display:inline;">동인.</span> 본문.</p>'
    out = R.unpin_inline_labels(html)
    assert "display:inline" not in out
    keep = '<span class="box-label" style="margin-top:10px;">동인.</span>'
    assert R.unpin_inline_labels(keep) == keep


def test_labels_avoid_a_page_break_right_after_them():
    assert "break-after: avoid-page" in R.CSS


def test_already_converted_labels_get_their_lost_space_back():
    """1차 소급 적용이 공백을 먹었다. 재적용으로는 안 잡히므로 따로 되살린다."""
    html = '<p><strong class="p-label">동인.</strong>오늘 장의 최대 동인은.</p>'
    assert '</strong> 오늘' in R.block_labels(html)
