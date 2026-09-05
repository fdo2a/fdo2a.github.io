"""발행본에 남은 base64 인라인 이미지를 잡는 검사.

2026-09-06 실측: 발행본 76편 18.8MB 중 15.8MB(84%)가 base64 PNG 였다.
`brief-report-writer.md` 는 이미 「base64 임베드 금지」를 적어놨지만 강제하는
게이트가 없어 38편 전부가 규칙을 어긴 채 나갔다. 규칙은 게이트가 아니다.
"""
from scripts.us import readability as R


BODY = "<html><body><div class='card'>%s</div></body></html>"
# 실제 차트는 10만 자대다. 임계(1,024자)를 확실히 넘는 길이로 세운다.
B64 = "iVBORw0KGgoAAAANSUhEUg" + "A" * 2000


def test_finds_inline_png():
    html = BODY % ('<img class="chart" alt="일봉" src="data:image/png;base64,%s">' % B64)
    found = R.inline_data_uris(html)
    assert len(found) == 1
    mime, size, alt = found[0]
    assert mime == "image/png"
    assert size == len(B64)
    assert alt == "일봉"


def test_external_reference_is_clean():
    html = BODY % '<img src="../assets/yield_curve_2026-09-04.png" alt="커브">'
    assert R.inline_data_uris(html) == []


def test_small_inline_svg_icon_is_not_flagged():
    """아이콘 크기의 data URI 까지 막으면 규칙이 과해진다 — 임계 위만 잡는다."""
    html = BODY % '<img src="data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=" alt="아이콘">'
    assert R.inline_data_uris(html) == []


def test_missing_alt_still_found():
    html = BODY % ('<img src="data:image/png;base64,%s">' % B64)
    found = R.inline_data_uris(html)
    assert len(found) == 1
    assert found[0][2] is None


def test_several_are_all_reported():
    img = '<img src="data:image/png;base64,%s">' % B64
    assert len(R.inline_data_uris(BODY % (img + img))) == 2


def test_single_quoted_src_is_found():
    """작은따옴표로 쓴 판이 검사를 비껴가면 게이트가 한 겹 얕은 것이다."""
    html = BODY % ("<img src='data:image/png;base64,%s'>" % B64)
    assert len(R.inline_data_uris(html)) == 1


def test_css_background_data_uri_is_found():
    """`<img>` 만 보면 배경 이미지로 같은 무게가 그대로 들어온다."""
    html = "<html><body><div style=\"background-image:url(data:image/png;base64,%s)\"></div></body></html>" % B64
    found = R.inline_data_uris(html)
    assert len(found) == 1
    assert found[0][0] == "image/png"


# --- codex 구현 검토 2026-09-06: 게이트를 비껴간 세 가지 ---

def test_newline_inside_the_payload_does_not_hide_it():
    """HTML 속성값 안의 줄바꿈은 브라우저가 무시한다. 정규식만 앞토막을 읽고
    임계 아래로 버렸다 — 검사가 읽는 문자열과 브라우저가 읽는 URI 가 갈린 자리다."""
    split = B64[:100] + "\n" + B64[100:]
    assert len(R.inline_data_uris(BODY % ('<img src="data:image/png;base64,%s">' % split))) == 1


def test_mime_parameters_do_not_hide_it():
    html = BODY % ('<img src="data:image/png;charset=utf-8;base64,%s">' % B64)
    assert len(R.inline_data_uris(html)) == 1


def test_non_image_mime_does_not_hide_it():
    """`image/` 로 한정하면 같은 무게가 다른 MIME 을 달고 그대로 들어온다."""
    html = BODY % ('<img src="data:application/octet-stream;base64,%s">' % B64)
    assert len(R.inline_data_uris(html)) == 1
