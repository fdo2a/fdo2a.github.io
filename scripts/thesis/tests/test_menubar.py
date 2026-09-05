"""thesis 페이지의 상단 메뉴바는 손으로 고칠 수 없다 — 빌더가 매번 다시 쓴다.

2026-08-31 채권 파이프라인을 붙이면서 메뉴바를 넓혔는데 `thesis/index.html` 만
손으로 고쳤고 빌더의 `menubar()` 는 그대로였다. 그날 저녁 수집 워크플로가
페이지를 다시 렌더하면서 손편집을 지워 버렸다(실행 33413582191 이 그 사실을
빨간 실행으로 남겼다). 채권 파이프라인은 2026-09-04 에 폐기됐지만, 메뉴를
index.html 에서만 고치면 thesis 만 어긋난다는 사실은 그대로다.
"""
import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

spec = importlib.util.spec_from_file_location(
    "build_thesis_pages", ROOT / "scripts" / "build_thesis_pages.py")
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def labels(html):
    return re.findall(r'<a href="[^"]*"[^>]*>([^<]+)</a>', html)


def test_menubar_carries_every_section():
    assert labels(build.menubar("thesis", "../")) == [
        "미국 시장", "한국 시장", "메모리 thesis", "중국 경제"]


def test_menubar_matches_the_hand_written_indexes():
    """정본은 index.html 이다 — 문구도 순서도 거기에 맞춘다."""
    home = (ROOT / "index.html").read_text(encoding="utf-8")
    nav = re.search(r"<nav class=\"menubar\">.*?</nav>", home, re.S).group(0)
    assert labels(build.menubar("thesis", "../")) == labels(nav)


def test_current_section_is_marked_once():
    html = build.menubar("thesis", "../")
    assert html.count('aria-current="page"') == 1
    assert '<a href="../thesis/" aria-current="page">메모리 thesis</a>' in html


def test_no_link_survives_from_the_retired_bond_pipeline():
    """2026-09-04 폐기 — 되살아나면 죽은 링크가 된다."""
    for current, root in (("thesis", "../"), ("us", "")):
        assert "bond" not in build.menubar(current, root)
