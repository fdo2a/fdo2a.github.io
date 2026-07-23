#!/usr/bin/env python3
"""기존 페이지의 <title> 태그를 검색 친화적 형식으로 소급 개선.

형식: "<키워드> — <그날 핵심구> | <날짜>"  (본문·수치는 건드리지 않음)
posts.json 헤드라인에서 사람이 뽑은 핵심구를 사용. 멱등(같은 값이면 무변경).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 파일 -> 새 <title>
TITLES = {
    "index.html": "미국 증시 마감 시황·모닝브리프 아카이브 | US Market Brief",
    "kr/index.html": "코스피·코스닥 마감 시황·마감브리프 아카이브 | KR Market Brief",
    "posts/2026-07-22.html": "미국 증시 마감 시황 — 유가 급등·금리 상승에 뉴욕증시 혼조 | 2026-07-22",
    "posts/2026-07-21.html": "미국 증시 마감 시황 — 메모리주 폭등에 나스닥 반등 | 2026-07-21",
    "posts/2026-07-20.html": "미국 증시 마감 시황 — 지정학 리스크에 하락, 한·미 메모리 디커플링 | 2026-07-20",
    "posts/2026-07-16.html": "미국 증시 마감 시황 — TSMC發 반도체 급락에 나스닥 하락 | 2026-07-16",
    "posts/2026-07-15.html": "미국 증시 마감 시황 — CPI 둔화에 나스닥·S&P500 상승 | 2026-07-15",
    "posts/2026-07-13.html": "미국 증시 마감 시황 — 유가 쇼크에 나스닥 급락 | 2026-07-13",
    "posts/2026-07-10.html": "미국 증시 마감 시황 — SK하이닉스 IPO·AI 랠리에 3대 지수 상승 | 2026-07-10",
    "kr/posts/2026-07-23.html": "코스피 마감 시황 — 외국인 순매수에 코스피·코스닥 동반 급등 | 2026-07-23",
    "kr/posts/2026-07-22.html": "코스피 마감 시황 — 장중 7,100 터치 후 반납, +0.74% 마감 | 2026-07-22",
}

TITLE_RE = re.compile(r"<title>.*?</title>", re.IGNORECASE | re.DOTALL)


def main() -> int:
    for rel, new_title in TITLES.items():
        path = ROOT / rel
        html = path.read_text(encoding="utf-8")
        new_tag = f"<title>{new_title}</title>"
        if new_tag in html:
            print(f"  {rel}: 이미 최신")
            continue
        if not TITLE_RE.search(html):
            print(f"  {rel}: [경고] <title> 없음 — 건너뜀")
            continue
        old = TITLE_RE.search(html).group(0)
        path.write_text(TITLE_RE.sub(new_tag, html, count=1), encoding="utf-8")
        print(f"  {rel}:\n     old {old}\n     new {new_tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
