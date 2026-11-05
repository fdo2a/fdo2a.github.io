"""`typography()` 가 AdSense 로더 제거를 「조판」으로 받는지 — 그 줄만, 정확히 그것만(2026-11-05).

받지 않으면 제거 한 번에 검토를 마친 발행본 전부가 「수정됨」으로 큐에 다시 오르고, 매시
러너가 그 205편을 codex 에 다시 읽힌다.
"""
from common import adsense, analytics
from review import prose
from review.tests.blocks import CUR, PREV
from us.readability import CSS as _READ_CSS

BODY = "<div class='card'><p>코스피는 20일선을 웃돌아 마감했다.</p></div>"
SRC = ('https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
       '?client=ca-pub-9240461016907498')
# 발행본에 실제로 있는 네 가지 표기(2026-11-05 전수 조사)
ONE_LINE = f'<!-- adsense-loader --><script async src="{SRC}" crossorigin="anonymous"></script>'
SPLIT = f'<!-- adsense-loader -->\n<script async src="{SRC}" crossorigin="anonymous"></script>'
REORDERED = f'<!-- adsense-loader --><script async="" crossorigin="anonymous" src="{SRC}"></script>'
BARE = f'<script async src="{SRC}" crossorigin="anonymous"></script>'


def _doc(loader=ONE_LINE, css=_READ_CSS, body=BODY, counter=True):
    head = "<!DOCTYPE html><html><head><title>t</title><style>" + css + "</style>\n"
    if loader:
        head += loader + "\n"
    if counter:
        head += analytics.SNIPPET + "\n"
    return head + "</head><body>" + body + "</body></html>"


def test_every_spelling_strips_to_the_same_page():
    want = _doc(loader=None)
    for loader in (ONE_LINE, SPLIT, REORDERED, BARE):
        assert adsense.strip(_doc(loader=loader)) == want


def test_strip_leaves_other_scripts_alone():
    page = _doc(loader=None)
    assert adsense.strip(page) == page
    assert not adsense.present(page)


def test_removal_alone_counts_as_typography():
    for loader in (ONE_LINE, SPLIT, REORDERED, BARE):
        old = _doc(loader=loader)
        assert prose.typography("posts/2026-09-01.html", old, adsense.strip(old)) is True


def test_removal_plus_prose_edit_is_a_revision():
    old = _doc()
    sneaky = _doc(loader=None, body=BODY.replace("웃돌아", "밑돌아"))
    assert prose.typography("posts/2026-09-01.html", old, sneaky) is False


def test_removal_on_top_of_a_readability_upgrade_still_counts():
    old = _doc(css=PREV)
    assert prose.typography("posts/2026-09-01.html", old, _doc(loader=None, css=CUR)) is True


def test_reviewed_before_the_counter_then_counter_then_removal():
    """옛 판(검토된 판)에는 방문 통계가 없고 AdSense 만 있었다 — 그 뒤 두 변환이 다 들어왔다."""
    old = _doc(counter=False)
    assert prose.typography("posts/2026-09-01.html", old, _doc(loader=None)) is True


def test_headless_early_post_counter_then_removal():
    """`<head>` 가 없는 초기 글 — 방문 통계는 AdSense 로더 바로 뒤에 붙었다. 삽입을 먼저
    재연해야 자리가 맞는다."""
    old = SPLIT + "\n<p>7월 10일 글.</p>"
    new = adsense.strip(analytics.inject(old))
    assert analytics.MARKER in new and not adsense.present(new)
    assert prose.typography("posts/2026-07-10.html", old, new) is True


def test_adding_a_loader_is_not_typography():
    """방향은 제거뿐이다 — 새 판에 로더가 생기면 이 재연은 아무것도 설명하지 않는다."""
    old = _doc(loader=None)
    edited = _doc(loader=ONE_LINE, body=BODY.replace("웃돌아", "밑돌아"))
    assert prose.typography("posts/2026-09-01.html", old, edited) is False


def test_removing_body_text_that_mentions_adsense_is_a_revision():
    body = BODY + "<p>Google AdSense 광고를 게재합니다.</p>"
    old = _doc(body=body)
    assert prose.typography("privacy.html", old, _doc(loader=None)) is False
