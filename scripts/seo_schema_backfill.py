#!/usr/bin/env python3
"""기존 글에 NewsArticle JSON-LD 구조화 데이터를 소급 주입.

각 글의 og:title(headline)·meta description·canonical(url)·파일명(date)을 읽어
NewsArticle 스키마를 <head> 직전(head 래퍼 없는 초기 글은 최상단)에 삽입.
멱등(마커로 판별). 본문·수치는 건드리지 않음.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKER = "<!-- article-schema -->"

# 경로 접두어 -> (브랜드, 홈 URL)
BRAND = {
    "posts/": ("US Market Brief", "https://fdo2a.github.io/"),
    "kr/posts/": ("KR Market Brief", "https://fdo2a.github.io/kr/"),
}

DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def field(html: str, pattern: str) -> str:
    m = re.search(pattern, html, re.IGNORECASE)
    return (m.group(1).strip() if m else "")


def brand_for(rel: str):
    for prefix, val in BRAND.items():
        if rel.startswith(prefix):
            return val
    return None


def build_schema(html: str, rel: str) -> str:
    brand, home = brand_for(rel)
    date = DATE_RE.search(rel).group(1)
    headline = field(html, r'property=["\']og:title["\']\s+content=["\']([^"\']+)')
    desc = field(html, r'name=["\']description["\']\s+content=["\']([^"\']+)')
    canonical = field(html, r'rel=["\']canonical["\']\s+href=["\']([^"\']+)')
    if not canonical:
        canonical = home + rel.split("/")[-1]
    org = {"@type": "Organization", "name": brand, "url": home}
    data = {
        "@context": "https://schema.org",
        "@type": "NewsArticle",
        "headline": headline[:110],
        "description": desc,
        "datePublished": date,
        "dateModified": date,
        "author": org,
        "publisher": org,
        "mainEntityOfPage": {"@type": "WebPage", "@id": canonical},
        "inLanguage": "ko",
    }
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return f'{MARKER}\n<script type="application/ld+json">\n{body}\n</script>'


def inject(rel: str, dry: bool) -> str:
    path = ROOT / rel
    html = path.read_text(encoding="utf-8")
    if MARKER in html:
        return "skip (이미 있음)"
    block = build_schema(html, rel)
    if "</head>" in html:
        new = html.replace("</head>", block + "\n</head>", 1)
        where = "head"
    else:
        new = block + "\n" + html
        where = "top"
    if not dry:
        path.write_text(new, encoding="utf-8")
    return f"주입 @{where}" + (" (dry)" if dry else "")


def main() -> int:
    import sys
    dry = "--dry" in sys.argv[1:]
    targets = sorted(ROOT.glob("posts/*.html")) + sorted(ROOT.glob("kr/posts/*.html"))
    for p in targets:
        rel = str(p.relative_to(ROOT))
        print(f"  {rel}: {inject(rel, dry)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
