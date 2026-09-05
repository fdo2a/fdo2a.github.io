"""임베드를 파일 참조로 바꾼 판이 원장에서 「수정됨」으로 쌓이지 않게 하는 등가 판정.

`equivalent()` 는 CSS 블록만 이식하므로 `src` 치환은 통과하지 못한다(2026-09-06 codex
검토 2.1·2.2). 그래서 형제 변환을 둔다. 방향은 이 모듈의 원칙 그대로 — **새 판을 되감아
옛 판이 바이트 그대로 나오는지만 본다.** 통과하는 새 판은 단 하나다.
"""
import base64

from review import prose

PNG = b"\x89PNG\r\n\x1a\n" + b"chart-bytes" * 200
B64 = base64.b64encode(PNG).decode()
DOC = ("<html><body><div class='card'><p>코스피는 20일선을 웃돌아 마감했다.</p>"
       "<img class=\"chart\" alt=\"일봉\" src=\"%s\"></div></body></html>")
OLD = DOC % ("data:image/png;base64," + B64)
NEW = DOC % "../assets/kr_charts_2026-09-03.png"


def _files(mapping):
    return lambda rel: mapping.get(rel)


def test_faithful_externalization_is_equivalent():
    assert prose.asset_externalized(OLD, NEW, _files({"../assets/kr_charts_2026-09-03.png": PNG})) is True


def test_different_image_is_not_equivalent():
    other = b"\x89PNG\r\n\x1a\n" + b"other" * 200
    assert prose.asset_externalized(OLD, NEW, _files({"../assets/kr_charts_2026-09-03.png": other})) is False


def test_missing_file_is_undecidable():
    assert prose.asset_externalized(OLD, NEW, _files({})) is None


def test_prose_edited_alongside_is_not_equivalent():
    """문장을 함께 고치면 등가가 아니다 — 이것이 수치·태그 비교로는 못 잡는 구멍이었다."""
    sneaky = NEW.replace("20일선을 웃돌아", "20일선을 밑돌아")
    assert prose.asset_externalized(OLD, NEW.replace(NEW, sneaky),
                                    _files({"../assets/kr_charts_2026-09-03.png": PNG})) is False


def test_attribute_change_on_the_img_is_not_equivalent():
    tweaked = NEW.replace('alt="일봉"', 'alt="일봉 차트"')
    assert prose.asset_externalized(OLD, tweaked,
                                    _files({"../assets/kr_charts_2026-09-03.png": PNG})) is False


def test_no_inline_image_in_the_old_version_is_undecidable():
    assert prose.asset_externalized(NEW, NEW, _files({})) is None


def test_still_embedded_new_version_is_undecidable():
    assert prose.asset_externalized(OLD, OLD, _files({})) is None


def test_two_images_both_must_resolve():
    old2 = OLD.replace("</div>", "<img src=\"data:image/png;base64,%s\"></div>" % B64)
    new2 = NEW.replace("</div>", "<img src=\"../assets/b.png\"></div>")
    files = {"../assets/kr_charts_2026-09-03.png": PNG, "../assets/b.png": PNG}
    assert prose.asset_externalized(old2, new2, _files(files)) is True
    assert prose.asset_externalized(old2, new2, _files({"../assets/b.png": PNG})) is None


def test_mime_is_taken_from_the_old_version():
    """png 로 못박아 되감으면 webp 판이 「다른 이미지」로 오판된다."""
    old = DOC % ("data:image/webp;base64," + B64)
    new = DOC % "../assets/kr_charts_2026-09-03.webp"
    assert prose.asset_externalized(old, new, _files({"../assets/kr_charts_2026-09-03.webp": PNG})) is True


def test_mixed_mimes_are_undecidable():
    old = (DOC % ("data:image/png;base64," + B64)).replace(
        "</div>", "<img src=\"data:image/webp;base64,%s\"></div>" % B64)
    new = NEW.replace("</div>", "<img src=\"../assets/b.webp\"></div>")
    assert prose.asset_externalized(old, new, _files({})) is None


def test_other_src_attributes_do_not_break_the_verdict():
    """광고 로더 `<script src="https://…">` 를 파일로 찾으려 들면 발행본 전부가
    「판정 불가」가 된다 — 2026-09-06 실측 38편 전부가 그렇게 무너졌다."""
    ad = '<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js"></script>'
    old = OLD.replace("<body>", "<body>" + ad)
    new = NEW.replace("<body>", "<body>" + ad)
    assert prose.asset_externalized(old, new, _files({"../assets/kr_charts_2026-09-03.png": PNG})) is True


def test_a_changed_script_src_is_not_equivalent():
    """가려놓고 자리만 맞추면 스크립트를 바꿔치기해도 통과할 수 있다 — 자리별로 본다."""
    old = OLD.replace("<body>", '<body><script src="a.js"></script>')
    new = NEW.replace("<body>", '<body><script src="evil.js"></script>')
    assert prose.asset_externalized(old, new, _files({"../assets/kr_charts_2026-09-03.png": PNG})) is False


# --- codex 구현 검토 2026-09-06: 뚫렸던 경로 ---

def test_src_written_in_prose_is_not_an_asset_swap():
    """산문에 `src="data:…"` 라고 **쓰여 있으면** 그 글자를 바꿔도 통과했다.
    정규식이 태그 속성과 독자가 보는 글자를 구분하지 않은 탓이다."""
    old = "<html><body><div class=card><p>예시 src=\"data:image/png;base64,%s\"</p></div></body></html>" % B64
    new = "<html><body><div class=card><p>예시 src=\"../assets/a.png\"</p></div></body></html>"
    assert prose.asset_externalized(old, new, _files({"../assets/a.png": PNG})) is not True


def test_src_inside_a_comment_is_not_an_asset_swap():
    old = "<html><body><!-- src=\"data:image/png;base64,%s\" --><p>가</p></body></html>" % B64
    new = "<html><body><!-- src=\"../assets/a.png\" --><p>가</p></body></html>"
    assert prose.asset_externalized(old, new, _files({"../assets/a.png": PNG})) is not True


def test_a_real_tag_attribute_still_swaps():
    """태그 안만 본다고 해서 정상 경로가 막히면 안 된다."""
    assert prose.asset_externalized(OLD, NEW, _files({"../assets/kr_charts_2026-09-03.png": PNG})) is True
