#!/usr/bin/env python3
"""구글 애드센스 로더 스크립트를 모든 콘텐츠 HTML에 삽입 + ads.txt 생성.

사용법:
    python3 scripts/inject_adsense.py ca-pub-1234567890123456          # 실제 적용
    python3 scripts/inject_adsense.py ca-pub-1234567890123456 --dry    # 미리보기(파일 미변경)

- 멱등: 이미 삽입된 파일은 건너뜀(마커 <!-- adsense-loader --> 로 판별)
- 대상: 방문자가 보는 페이지만. data/*·kr/data/* 조각(본문에 삽입됨)과
  scripts/.../fixtures/* 테스트 픽스처는 제외.
- ads.txt: 애드센스 수익 보호를 위한 판매자 선언. 루트에 있어야 함.
"""
import re
import sys
from pathlib import Path

# 이 스크립트는 site/scripts/ 에 있으므로 부모의 부모가 사이트 루트
ROOT = Path(__file__).resolve().parent.parent

# 광고를 넣을 방문자용 페이지 (조각·픽스처 제외)
CONTENT_GLOBS = [
    "index.html",
    "about.html",
    "privacy.html",
    "posts/*.html",
    "kr/index.html",
    "kr/posts/*.html",
]

MARKER = "<!-- adsense-loader -->"


def loader_snippet(pub_id: str) -> str:
    return (
        f'{MARKER}\n'
        f'<script async src="https://pagead2.googlesyndication.com/pagead/js/'
        f'adsbygoogle.js?client={pub_id}" crossorigin="anonymous"></script>'
    )


def target_files() -> list[Path]:
    files: list[Path] = []
    for pattern in CONTENT_GLOBS:
        files.extend(sorted(ROOT.glob(pattern)))
    return files


def inject(path: Path, snippet: str, dry: bool) -> str:
    html = path.read_text(encoding="utf-8")
    if MARKER in html:
        return "skip (이미 있음)"
    if "</head>" in html:
        new = html.replace("</head>", snippet + "\n</head>", 1)
        where = "head"
    else:
        # <head> 래퍼 없는 초기 글: 문서 최상단에 삽입(브라우저 암묵 head로 들어감)
        new = snippet + "\n" + html
        where = "top(head 래퍼 없음)"
    if not dry:
        path.write_text(new, encoding="utf-8")
    return f"삽입 @{where}" + (" (dry)" if dry else "")


# 앞으로 발행되는 글도 실제 ID를 쓰도록 writer 템플릿의 placeholder를 치환
TEMPLATE_FILES = [
    ".claude/agents/brief-report-writer.md",
]
PLACEHOLDER = "ca-pub-XXXXXXXXXXXXXXXX"


def patch_templates(pub_id: str, dry: bool) -> list[str]:
    out = []
    for rel in TEMPLATE_FILES:
        path = ROOT / rel
        if not path.exists():
            out.append(f"  {rel}: 없음(건너뜀)")
            continue
        text = path.read_text(encoding="utf-8")
        n = text.count(PLACEHOLDER)
        if n == 0:
            out.append(f"  {rel}: placeholder 없음(이미 치환됨?)")
            continue
        if not dry:
            path.write_text(text.replace(PLACEHOLDER, pub_id), encoding="utf-8")
        out.append(f"  {rel}: placeholder {n}곳 -> {pub_id}" + (" (dry)" if dry else ""))
    return out


def write_ads_txt(pub_id: str, dry: bool) -> str:
    # ads.txt 는 'ca-' 접두사 없이 pub- 만 사용
    seller = pub_id.replace("ca-", "")
    line = f"google.com, {seller}, DIRECT, f08c47fec0942fa0\n"
    path = ROOT / "ads.txt"
    if not dry:
        path.write_text(line, encoding="utf-8")
    return f"ads.txt -> {line.strip()}" + (" (dry)" if dry else "")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv[1:]
    if not args:
        print(__doc__)
        return 1
    pub_id = args[0].strip()
    if not re.fullmatch(r"ca-pub-\d{16}", pub_id):
        print(f"[오류] 게시자 ID 형식이 이상합니다: {pub_id!r}\n"
              f"       예: ca-pub-1234567890123456 (ca-pub- + 숫자 16자리)")
        return 1

    snippet = loader_snippet(pub_id)
    print(f"게시자 ID: {pub_id}  {'[DRY-RUN]' if dry else ''}\n")
    for f in target_files():
        rel = f.relative_to(ROOT)
        print(f"  {rel}: {inject(f, snippet, dry)}")
    print("\n" + write_ads_txt(pub_id, dry))
    print("\n[writer 템플릿 patch — 향후 발행 글용]")
    for line in patch_templates(pub_id, dry):
        print(line)
    print("\n완료. git add -A && git commit && git push 로 반영하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
