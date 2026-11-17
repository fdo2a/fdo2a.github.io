"""일본어 목록 json — 한글 목록에서 일본어판이 나간 글만 남기고 제목·헤드라인·라벨을 일본어로 바꾼다.

    python3 -m scripts.ja.lists          # ja/ 아래 세 파일을 다시 쓴다

일본어 글의 이전·다음 이동과 목록 페이지(`ja/index.html`, `ja/japan/index.html`)가 이 파일을 읽는다.

규칙:
- 한글 목록의 항목 가운데 원장(`ja/state.json`)의 `status` 가 `published`·`notice` 인 글만 남긴다.
  순서는 한글 목록 그대로.
- `title`·`headline`·`label` 은 그 글 사이드카(`ja/_tm/<path>.json`)의 `list: {field: ja}` 로 바꾼다.
  사이드카의 `list_src[field]` 가 **지금 한글 목록의 값과 같을 때만** 쓴다. 다르거나 없으면 그 글을
  목록에서 뺀다(낡은 제목을 내지 않는다). 빈 문자열과 한글이 없는 값은 그대로 둔다.
- 그 밖의 필드(`date`·`key`·`start_date`·`end_date`)는 그대로.
- 결과에 한글이 한 자라도 남으면 `ValueError`.
- 직렬화는 한글판 파일을 쓰는 코드와 같다: `json.dump(..., ensure_ascii=False, indent=2)`.
  `posts.json`·`news.json` 은 `update_archives.py` 가 써서 끝 줄바꿈이 없고,
  `japan/daily.json`(`publish_japan_daily._write_json`)은 끝에 `\\n` 이 있다.
- 주간 목록(`weekly.json`·`japan/posts.json`)은 만들지 않는다 — 일본어판은 일간만이다(2026-11-17).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from . import state as S

HANGUL = re.compile(r"[가-힣]")

# (한글 목록, 글 폴더, 끝 줄바꿈) — 일본어판은 같은 이름을 `ja/` 아래에 둔다.
LISTS = (
    ("posts.json", "posts", ""),
    ("news.json", "news", ""),
    ("japan/daily.json", "japan/daily", "\n"),
)
TEXT_FIELDS = ("title", "headline", "label")
LISTED = ("published", "notice")


def page_of(folder: str, item: dict):
    """목록 페이지가 여는 글 — `index.html` 의 `p.slug || p.key || p.date` 와 같은 순서."""
    slug = item.get("slug") or item.get("key") or item.get("date")
    return f"{folder}/{slug}.html" if slug else None


def dumps(rows, tail: str) -> str:
    return json.dumps(rows, ensure_ascii=False, indent=2) + tail


def _ja_item(root, folder, item, pages):
    path = page_of(folder, item)
    if not path or (pages.get(path) or {}).get("status") not in LISTED:
        return None
    side, why = S.load_sidecar(root, path)
    if why:
        return None
    src = side.get("list_src") if isinstance(side.get("list_src"), dict) else {}
    ja = side.get("list") if isinstance(side.get("list"), dict) else {}
    out = dict(item)
    for f in TEXT_FIELDS:
        if f not in item:
            continue
        ko = item[f]
        tr = ja.get(f)
        if isinstance(ko, str) and src.get(f) == ko and isinstance(tr, str) and tr.strip():
            out[f] = tr
        elif isinstance(ko, str) and (not ko or not HANGUL.search(ko)):
            out[f] = ko
        else:
            return None
    return out


def _read_list(path: Path):
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    if not isinstance(rows, list):
        raise ValueError(f"{path} 가 목록이 아니다")
    return rows


def build(root) -> dict:
    """{relpath: text} — `ja/posts.json` 등 세 파일의 내용."""
    root = Path(root)
    ledger, _why = S.load_ledger(root)
    pages = ledger.get("pages") or {}
    out = {}
    for rel, folder, tail in LISTS:
        rows = []
        for item in _read_list(root / rel):
            if isinstance(item, dict):
                got = _ja_item(root, folder, item, pages)
                if got is not None:
                    rows.append(got)
        text = dumps(rows, tail)
        left = HANGUL.findall(text)
        if left:
            raise ValueError(f"ja/{rel} 에 한글 {len(left)}자가 남았다: {''.join(left[:10])}")
        out[f"ja/{rel}"] = text
    return out


def write(root) -> list:
    """세 파일을 쓰고, 바뀐 경로를 돌려준다."""
    root = Path(root)
    changed = []
    for rel, text in build(root).items():
        p = root / rel
        if p.exists() and p.read_text(encoding="utf-8") == text:
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        changed.append(rel)
    return changed


def main():
    root = Path(__file__).resolve().parents[2]
    for rel in write(root):
        print(f"{rel} 갱신")


if __name__ == "__main__":
    main()
