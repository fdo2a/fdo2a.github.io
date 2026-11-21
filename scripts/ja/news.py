"""원문이 일본어인 뉴스 항목 — 번역하지 않고 원제·원문 매체명으로 되돌린다.

사용자 규칙: 원문이 일본어인 뉴스는 원문 그대로 두고, 다른 언어인 것만 번역한다.
한글 요약은 싣지 않는다.

발행본의 뉴스 항목:
    <div class="news-item" data-news="ID"><p class="news-head">한글 제목<span class="sub">매체 · 11월 12일</span></p>
    <p data-summary="ID">한글 요약</p></div>
요약 문단은 `data-summary` 가 없는 `<p>` 하나·둘인 변형도 있다(실물 39건). 지우는 것은 머리 뒤의 속성 없는
`<p>` 와 `<p data-summary=…>` 뿐이다 — 그 밖의 문단·요소가 머리 뒤에 있거나, 머리를 못 찾거나, 여는 태그가
위 꼴이 아니거나(속성 순서가 다름), 원문 주소가 `http`/`https` 가 아니면 손대지 않고 `malformed` 로 올린다
(파이프라인이 `news_malformed` 로 보류). 2026-11-14 실물 151편에서 지워지는 것은 전부 요약이었다.

원제 언어(`origin`): 가나 → 일본어. 가나 없이 한자만인 제목은 `.jp` 호스트면 일본어, 아니면 「불확실」
(`unsure` — 중국어일 수 있다. 파이프라인이 `news_lang` 으로 보류). 실측: 뉴스 기록 1,428건에 0건.

순서는 **localize → extract.split → state.plan** 이다. localize 뒤의 머리 단위는
「원제 + 원문 매체명 + 한글 날짜」라 `glossary.fixed` 가 받고 모델에는 가지 않는다.
"""
from __future__ import annotations

import html as _html
import json
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

KANA = re.compile(r"[ぁ-ゖァ-ヺ]")
KANJI = re.compile(r"[㐀-䶿一-鿿]")
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")

BEFORE_DAYS = 14   # 뉴스가 며칠 이월되므로 앞으로 넉넉히
AFTER_DAYS = 0     # 2026-11-14 실측: 뒷날 파일 없이도 대상 글 151편의 뉴스 ID 가 전부 맞는다

_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})\.html$")
_WEEK = re.compile(r"(\d{4})-W(\d{2})\.html$")


def _span(post_path: str):
    """글이 덮는 (첫날, 끝날, 주차 목록)."""
    m = _DATE.search(post_path)
    if m:
        d = date.fromisoformat(m.group(1))
        y, w, _ = d.isocalendar()
        return d, d, [(y, w)]
    m = _WEEK.search(post_path)
    if m:
        y, w = int(m.group(1)), int(m.group(2))
        mon = date.fromisocalendar(y, w, 1)
        return mon, mon + timedelta(days=6), [(y, w)]
    raise ValueError(f"날짜·주차를 읽을 수 없는 경로: {post_path}")


def data_files(repo_root, post_path: str) -> list[Path]:
    """그 글이 쓰는 뉴스 데이터 후보(있는 것만)."""
    root = Path(repo_root)
    first, last, weeks = _span(post_path)
    out = []
    d = first - timedelta(days=BEFORE_DAYS)
    while d <= last + timedelta(days=AFTER_DAYS):
        s = d.isoformat()
        out += [root / "data/news" / f"{s}.json",
                root / "japan/data/news" / f"{s}.json",
                root / "japan/data/news/daily" / f"{s}.json"]
        d += timedelta(days=1)
    for y, w in weeks:
        mon = date.fromisocalendar(y, w, 1)
        for back in (0, 7, 14):
            yy, ww, _ = (mon - timedelta(days=back)).isocalendar()
            out.append(root / "japan/data" / f"{yy}-W{ww:02d}.news.json")
    return [p for p in out if p.is_file()]


def _items(obj):
    if isinstance(obj, list):
        return [x for x in obj if isinstance(x, dict)]
    if isinstance(obj, dict) and isinstance(obj.get("items"), list):
        return [x for x in obj["items"] if isinstance(x, dict)]
    return []


def lookup(repo_root, post_path: str) -> dict:
    """data-news ID(guid 또는 url) → 기록. 뒤에 읽은 파일이 앞의 것을 덮는다."""
    recs = {}
    for p in data_files(repo_root, post_path):
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for it in _items(obj):
            for key in ("guid", "url"):
                v = it.get(key)
                if v:
                    recs[str(v)] = it
    return recs


def origin(record: dict) -> str:
    """원제 언어 — "ja" · "other" · "unsure". 가나가 있으면 일본어. 가나가 없고 한자가 있으면 `.jp` 호스트에
    한글이 없고 라틴 문장이 아닐 때 일본어(한자만으로 된 짧은 제목), `.jp` 가 아니면 불확실."""
    title = _html.unescape(str(record.get("title") or ""))
    if not title.strip() or HANGUL.search(title):
        return "other"
    if KANA.search(title):
        return "ja"
    kanji = len(KANJI.findall(title))
    if not kanji:
        return "other"
    host = (urlparse(str(record.get("url") or "")).hostname or "").lower()
    if not host.endswith(".jp"):
        return "unsure"
    return "ja" if len(LATIN.findall(title)) <= 2 * kanji else "other"


def is_ja_origin(record: dict) -> bool:
    return origin(record) == "ja"


def count_items(html: str) -> int:
    """`data-news` 속성을 단 시작 태그 수(script 안 문자열은 세지 않는다)."""
    from .extract import attr_spans, tokens
    n = 0
    for t in tokens(html):
        if t.kind in ("start", "startend") and any(
                name == "data-news" for name, *_ in attr_spans(html[t.start:t.end])):
            n += 1
    return n


@dataclass
class Report:
    localized: list = field(default_factory=list)   # 원문으로 바꾼 ID
    kept: list = field(default_factory=list)        # 일본어 원문이 아니라 그대로 둔(번역 대상) ID
    missing: list = field(default_factory=list)     # 기록을 못 찾은 ID — 2차가 그 글을 보류한다
    no_source: list = field(default_factory=list)   # 기록에 source 가 없어 한글 매체명이 남은 ID
    malformed: list = field(default_factory=list)   # 꼴을 못 알아본 ID(머리 없음·요약 아닌 문단·주소·여는 태그)
    unsure: list = field(default_factory=list)      # 원제가 일본어인지 불확실한 ID


_OPEN = re.compile(r'<div class="news-item" data-news="([^"]*)">')
_DIV = re.compile(r"<div\b|</div\s*>", re.I)
_HEAD = re.compile(r'(<p class="news-head">)(.*?)(<span class="sub">)(.*?)(</span>\s*</p>)', re.S)
_SUMMARY = re.compile(r'\s*<p(?:\s+data-summary="[^"]*")?\s*>.*?</p>', re.S)
_ANY_OPEN = re.compile(r"<[a-zA-Z][^>]*\sdata-news\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)[^>]*>")


def _item_end(html, start):
    depth = 0
    for m in _DIV.finditer(html, start):
        depth += 1 if m.group(0).lower().startswith("<div") else -1
        if depth == 0:
            return m.start(), m.end()
    return None


def _summaries_end(rest):
    """머리 뒤가 요약 문단(+공백)뿐이면 지운 뒤 남는 꼬리(공백), 아니면 None."""
    pos = 0
    while True:
        m = _SUMMARY.match(rest, pos)
        if not m:
            break
        pos = m.end()
    tail = rest[pos:]
    return tail if not tail.strip() else None


def _localize_item(inner, rec):
    """항목 안쪽(여는·닫는 div 사이)을 바꾼다. 꼴을 못 알아보면 (None, False)."""
    head = _HEAD.search(inner)
    if not head:
        return None, False
    raw_url = _html.unescape(str(rec.get("url") or ""))
    u = urlparse(raw_url)
    if u.scheme.lower() not in ("http", "https") or not u.netloc:
        return None, False
    rest = _summaries_end(inner[head.end():])
    if rest is None:
        return None, False
    title = _html.escape(_html.unescape(str(rec.get("title") or "")), quote=False)
    url = _html.escape(raw_url, quote=True)
    source = rec.get("source")
    sub = head.group(4)
    if source:
        src = _html.escape(_html.unescape(str(source)), quote=False)
        sub = src + sub[sub.index(" · "):] if " · " in sub else src
    new_head = (f'{head.group(1)}<a href="{url}" rel="noopener">{title}</a>'
                f"{head.group(3)}{sub}{head.group(5)}")
    return inner[:head.start()] + new_head + rest, bool(source)


def localize(html: str, records: dict):
    """일본어 원문 항목의 제목·매체명을 원문으로, 요약 문단은 지운다. (html2, Report)."""
    rep = Report()
    out, pos = [], 0
    known = {m.start() for m in _OPEN.finditer(html)}
    for m in _ANY_OPEN.finditer(html):      # 여는 태그가 정해진 꼴이 아니면 보류(못 보고 지나치지 않게)
        if m.start() not in known:
            rep.malformed.append(_html.unescape(m.group(1).strip("\"'")))
    for m in _OPEN.finditer(html):
        if m.start() < pos:
            continue
        nid = _html.unescape(m.group(1))
        end = _item_end(html, m.start())
        rec = records.get(nid)
        if end is None:
            rep.malformed.append(nid)
            continue
        if rec is None:
            rep.missing.append(nid)
            continue
        lang = origin(rec)
        if lang == "unsure":
            rep.unsure.append(nid)
            continue
        if lang != "ja":
            rep.kept.append(nid)
            continue
        inner = html[m.end():end[0]]
        new, has_source = _localize_item(inner, rec)
        if new is None:
            rep.malformed.append(nid)
            continue
        out.append(html[pos:m.end()])
        out.append(new)
        pos = end[0]
        rep.localized.append(nid)
        if not has_source:
            rep.no_source.append(nid)
    out.append(html[pos:])
    return "".join(out), rep
