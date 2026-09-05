"""`typography()` 가 자산 외부화도 「조판」과 같은 자리로 받아들이는지.

받아들이지 않으면 백필 한 번에 발행본 70편이 「수정됨」으로 큐에 쌓인다. 그 70편은
`REVIEW_GATE.md` §2 가 「레이아웃·HTML·CSS는 보지 마」라고 지시하는 대상이라
**정의상 지적을 만들 수 없다** — `equivalent()` 가 CSS 때문에 생긴 것과 같은 문제다.
"""
import base64

from review import prose

PNG = b"\x89PNG\r\n\x1a\n" + b"chart" * 300
DOC = ("<html><body><div class='card'><p>코스피는 20일선을 웃돌아 마감했다.</p>"
       "<img src=\"%s\"></div></body></html>")
OLD = DOC % ("data:image/png;base64," + base64.b64encode(PNG).decode())
NEW = DOC % "../assets/yield_curve_2026-09-04.png"


def _root(tmp_path):
    (tmp_path / "posts").mkdir()
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "yield_curve_2026-09-04.png").write_bytes(PNG)
    return tmp_path


def test_asset_externalization_counts_as_typography(tmp_path):
    root = _root(tmp_path)
    assert prose.typography("posts/2026-09-04.html", OLD, NEW, root=str(root)) is True


def test_without_a_root_it_stays_undecidable(tmp_path):
    """파일을 못 읽으면 「조판」이라고 우기지 않는다 — 미검토로 남는 편이 안전하다."""
    assert prose.typography("posts/2026-09-04.html", OLD, NEW) is None


def test_a_different_image_is_still_a_revision(tmp_path):
    root = _root(tmp_path)
    (root / "assets" / "yield_curve_2026-09-04.png").write_bytes(b"\x89PNG\r\n\x1a\nother")
    assert prose.typography("posts/2026-09-04.html", OLD, NEW, root=str(root)) is False


def test_prose_change_alongside_is_still_a_revision(tmp_path):
    root = _root(tmp_path)
    sneaky = NEW.replace("웃돌아", "밑돌아")
    assert prose.typography("posts/2026-09-04.html", OLD, sneaky, root=str(root)) is False


def test_css_verdict_still_wins(tmp_path, monkeypatch):
    """조판(CSS) 판정이 자산 경로 때문에 가려지면 안 된다."""
    monkeypatch.setattr(prose, "equivalent", lambda old, new: True)
    assert prose.typography("posts/x.html", OLD, NEW, root=str(tmp_path)) is True


def test_a_plain_revision_stays_a_revision(tmp_path, monkeypatch):
    """자산 변환의 사례가 아닐 때는 `equivalent()` 의 답이 그대로 나가야 한다."""
    monkeypatch.setattr(prose, "equivalent", lambda old, new: False)
    plain = "<html><body><p>가</p></body></html>"
    assert prose.typography("posts/x.html", plain, plain, root=str(tmp_path)) is False
