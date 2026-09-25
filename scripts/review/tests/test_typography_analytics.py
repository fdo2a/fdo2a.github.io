"""`typography()` 가 방문 통계 로더 삽입을 「조판」으로 받는지 — 삽입만, 정확히 그 자리만.

받지 않으면 소급 한 번에 검토를 마친 발행본 전부가 「수정됨」으로 큐에 다시 오른다.
"""
from common import analytics
from review import prose
from us.readability import CSS as _READ_CSS

BODY = "<div class='card'><p>코스피는 20일선을 웃돌아 마감했다.</p></div>"


def _doc(css=_READ_CSS, body=BODY):
    return ("<!DOCTYPE html><html><head><title>t</title><style>" + css + "</style>\n"
            "</head><body>" + body + "</body></html>")


def test_backfill_alone_counts_as_typography():
    old = _doc()
    assert prose.typography("posts/2026-09-01.html", old, analytics.inject(old)) is True


def test_headless_early_post_backfill_counts_as_typography():
    old = ('<!-- adsense-loader -->\n<script async src="https://pagead2.googlesyndication.com'
           '/pagead/js/adsbygoogle.js"></script>\n<p>7월 10일 글.</p>')
    assert prose.typography("posts/2026-07-10.html", old, analytics.inject(old)) is True


def test_backfill_plus_prose_edit_is_a_revision():
    old = _doc()
    sneaky = analytics.inject(_doc(body=BODY.replace("웃돌아", "밑돌아")))
    assert prose.typography("posts/2026-09-01.html", old, sneaky) is False


def test_loader_somewhere_else_is_not_typography():
    old = _doc()
    moved = old.replace("<body>", "<body>" + analytics.SNIPPET)
    assert prose.typography("posts/2026-09-01.html", old, moved) is not True


def test_altered_loader_is_not_typography():
    old = _doc()
    other = analytics.inject(old).replace(analytics.CODE + ".goatcounter", "someone.goatcounter")
    assert prose.typography("posts/2026-09-01.html", old, other) is not True


def test_backfill_on_top_of_a_readability_upgrade_still_counts():
    """두 변환이 한 판에 겹친 경우 — 옛 판은 직전 조판 블록, 새 판은 현재 블록 + 로더."""
    from review.tests.blocks import CUR, PREV
    old = _doc(css=PREV)
    new = analytics.inject(_doc(css=CUR))
    assert prose.typography("posts/2026-09-01.html", old, _doc(css=CUR)) is True
    assert prose.typography("posts/2026-09-01.html", old, new) is True


def test_loader_already_there_changes_nothing():
    """옛 판에 이미 있으면 재연할 것이 없다 — 원래 판정이 그대로 나간다."""
    old = analytics.inject(_doc())
    edited = old.replace("웃돌아", "밑돌아")
    assert prose.typography("posts/2026-09-01.html", old, edited) is False
