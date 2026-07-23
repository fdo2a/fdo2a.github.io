#!/usr/bin/env python3
"""H1 없는 신규 US 글의 헤드라인 카드 첫 <p>를 <h1>으로 변환(시각 불변).

전역 h1(22px)에 안 먹도록 인라인 스타일로 기존 .headline-card p 외형(17px bold,
margin 0)을 복제. 파일별 CSS 변수명 차이에 의존하지 않는다. 멱등.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [
    "posts/2026-07-16.html",
    "posts/2026-07-20.html",
    "posts/2026-07-21.html",
    "posts/2026-07-22.html",
]
H1_OPEN = ('<h1 style="font-size:17px;font-weight:700;margin:0;'
           'line-height:1.55;color:inherit;">')


def convert(rel: str) -> str:
    path = ROOT / rel
    html = path.read_text(encoding="utf-8")
    if "<h1" in html:
        return "skip (이미 h1 있음)"
    m = re.search(r'headline-card"?\s*>', html)
    if not m:
        return "[경고] headline-card 없음"
    start = m.end()
    # 카드 안 첫 <p>...</p> 를 h1으로
    pm = re.search(r"<p>(.*?)</p>", html[start:], re.DOTALL)
    if not pm:
        return "[경고] 헤드라인 <p> 없음"
    seg = pm.group(0)
    new_seg = H1_OPEN + pm.group(1) + "</h1>"
    new = html[:start] + html[start:].replace(seg, new_seg, 1)
    path.write_text(new, encoding="utf-8")
    return "변환 <p>→<h1>"


def main() -> int:
    for rel in TARGETS:
        print(f"  {rel}: {convert(rel)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
