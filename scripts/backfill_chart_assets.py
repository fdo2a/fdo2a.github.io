#!/usr/bin/env python3
"""발행본에 박힌 base64 차트를 파일 참조로 되돌린다.

    python3 scripts/backfill_chart_assets.py us          # dry-run
    python3 scripts/backfill_chart_assets.py us --apply
    python3 scripts/backfill_chart_assets.py kr --apply

2026-09-06 실측: 발행 HTML 76편 18.8MB 중 15.8MB(84%)가 base64 PNG 였다.
US 38편은 임베드 바이트가 `assets/yield_curve_{date}.png` 와 SHA-256 동일이라(38/38)
**해시가 맞을 때만** 참조로 바꾼다. KR 32편은 대응 파일이 없다 — 무날짜 이름이라 매일
덮어써졌다 — 그래서 임베드분을 **추출**해 `kr/assets/` 에 날짜별로 만든다.

차트 종류는 `alt` 가 아니라 **PNG IHDR 높이**로 가린다. 53장 중 11장은 alt 가 없고
표기도 8종이라 alt 로는 전수 분류가 안 된다. 높이는 figure 크기에서 오므로 일봉 2×2
(11×6.4in)는 860 언저리, 장중 1×2(11×3.6in)는 469 로 갈린다 — alt 가 있는 42장과
충돌 0 으로 확인했다. alt 는 교차검증에만 쓴다.

한 편이라도 판정이 서지 않으면 **그 편은 건드리지 않는다.** 자산을 먼저 다 쓰고
HTML 을 나중에 바꾼다 — 중간에 죽어도 깨진 참조가 남지 않는다.
"""
import base64
import hashlib
import os
import re
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_INLINE = re.compile(r'src="data:(image/[a-z0-9.+-]+);base64,([A-Za-z0-9+/=]+)"', re.I)
_ALT = re.compile(r'alt="([^"]*)"')

# 일봉은 2×2 패널(figsize 11×6.4), 장중 수급은 1×2(11×3.6). 실측 분포는 (1505,861)·
# (1505,860) 32장과 (1505,469) 21장 둘뿐이다. 높이만으로 가르면 800×600 같은 남의
# 그림까지 일봉으로 읽으므로, **아는 모양의 창** 밖은 판정하지 않는다. bbox_inches
# ="tight" 가 여백을 깎아 861↔860 처럼 몇 픽셀이 흔들리므로 창에 여유를 둔다.
_WIDTH = (1400, 1600)
_SHAPES = (("kr_charts", 750, 950), ("kr_flows_intraday", 380, 560))


@dataclass
class Post:
    path: str                     # 레포 기준 상대경로
    ok: bool = True
    why: str = ""
    swaps: list = field(default_factory=list)   # [(post 상대경로, 새 src), …]
    writes: list = field(default_factory=list)  # [(자산 상대경로, 바이트), …]


def png_size(raw: bytes):
    """PNG IHDR 의 (너비, 높이). PNG 가 아니면 None."""
    # 길이를 먼저 본다. 잘린 헤더에 `struct.unpack` 을 걸던 판은 `struct.error` 로
    # 계획 수립 자체를 멈춰, 「그 편만 건너뛴다」는 계약이 지켜지지 않았다.
    if len(raw) < 24 or not raw.startswith(b"\x89PNG\r\n\x1a\n") or raw[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", raw[16:24])


def chart_kind(raw: bytes):
    """KR 차트 종류. 아는 모양이 아니면 None — 모르면 건드리지 않는다."""
    size = png_size(raw)
    if size is None:
        return None
    w, h = size
    if not _WIDTH[0] <= w <= _WIDTH[1]:
        return None
    for kind, lo, hi in _SHAPES:
        if lo <= h <= hi:
            return kind
    return None


def _embeds(html):
    """[(mime, 원본 바이트, alt 또는 None), …]"""
    out = []
    for m in _INLINE.finditer(html):
        open_at = html.rfind("<", 0, m.start())
        alt = _ALT.search(html[open_at:m.start()]) if open_at >= 0 else None
        try:
            raw = base64.b64decode(m.group(2))
        except Exception:  # noqa: BLE001
            raw = None
        out.append((m.group(1).lower(), raw, alt.group(1) if alt else None))
    return out


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _existing(root, rel, raw):
    """같은 해시면 재사용(쓰지 않음), 다르면 충돌. (쓸 것인가, 사유)"""
    p = Path(root) / rel
    if not p.exists():
        return True, ""
    if _sha(p.read_bytes()) == _sha(raw):
        return False, ""
    return False, "충돌 — %s 가 이미 다른 바이트로 있다" % rel


def plan_us(root):
    """US: 임베드가 `assets/yield_curve_{date}.png` 와 해시 일치할 때만 참조로."""
    root = Path(root)
    plans = []
    for post in sorted((root / "posts").glob("*.html")):
        date = post.stem
        rel_post = "posts/%s" % post.name
        p = Post(rel_post)
        html = post.read_text(encoding="utf-8")
        embeds = _embeds(html)
        if not embeds:
            continue
        if len(embeds) != 1:
            p.ok, p.why = False, "임베드 %d장 — US 는 커브 차트 한 장만 안다" % len(embeds)
            plans.append(p)
            continue
        _, raw, _ = embeds[0]
        asset = "assets/yield_curve_%s.png" % date
        target = root / asset
        if raw is None:
            p.ok, p.why = False, "base64 디코딩 실패"
        elif not target.exists():
            p.ok, p.why = False, "대응 자산 없음 — %s" % asset
        elif _sha(target.read_bytes()) != _sha(raw):
            p.ok, p.why = False, "해시 불일치 — %s 는 임베드와 다른 그림이다" % asset
        else:
            p.swaps = [(rel_post, "../%s" % asset)]
        plans.append(p)
    return plans


def plan_kr(root):
    """KR: 임베드분을 추출해 `kr/assets/{종류}_{date}.png` 로 만들고 참조로."""
    root = Path(root)
    plans = []
    for post in sorted((root / "kr" / "posts").glob("*.html")):
        date = post.stem
        p = Post("kr/posts/%s" % post.name)
        html = post.read_text(encoding="utf-8")
        embeds = _embeds(html)
        if not embeds:
            continue
        seen = {}
        for mime, raw, alt in embeds:
            if raw is None:
                p.ok, p.why = False, "base64 디코딩 실패"
                break
            kind = chart_kind(raw)
            if kind is None:
                p.ok, p.why = False, "모르는 그림 모양 %s — 손대지 않는다" % (png_size(raw),)
                break
            # alt 가 있으면 교차검증한다. 높이와 어긋나면 사람이 볼 일이다.
            if alt and (("일봉" in alt) != (kind == "kr_charts")):
                p.ok, p.why = False, "높이(%s)와 alt(%s)가 어긋난다" % (kind, alt)
                break
            if kind in seen:
                p.ok, p.why = False, "같은 종류 중복 %s — 어느 쪽이 어느 것인지 모른다" % kind
                break
            seen[kind] = raw
            rel = "kr/assets/%s_%s.png" % (kind, date)
            write, why = _existing(root, rel, raw)
            if why:
                p.ok, p.why = False, why
                break
            if write:
                p.writes.append((rel, raw))
            p.swaps.append((p.path, "../assets/%s_%s.png" % (kind, date)))
        if not p.ok:
            p.writes, p.swaps = [], []
        plans.append(p)
    return plans


def apply(plans, root):
    """자산을 먼저 전부 쓰고, 그다음 HTML 을 바꾼다. 판정이 선 편만."""
    root = Path(root)
    good = [p for p in plans if p.ok and p.swaps]
    for p in good:
        for rel, raw in p.writes:
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
    for p in good:
        post = root / p.path
        html = post.read_text(encoding="utf-8")
        srcs = iter([s for _, s in p.swaps])
        html = _INLINE.sub(lambda m: 'src="%s"' % next(srcs), html)
        post.write_text(html, encoding="utf-8")
    return good


def main(argv):
    if not argv or argv[0] not in ("us", "kr"):
        print("사용법: backfill_chart_assets.py {us|kr} [--apply]")
        return 2
    root = Path(__file__).resolve().parent.parent
    plans = (plan_us if argv[0] == "us" else plan_kr)(root)
    ok = [p for p in plans if p.ok and p.swaps]
    bad = [p for p in plans if not p.ok]
    saved = sum(len(base64.b64encode(raw)) for p in ok for _, raw in p.writes) or None
    for p in bad:
        print("  SKIP %s — %s" % (p.path, p.why))
    for p in ok:
        print("  %s → %s" % (p.path, ", ".join(s for _, s in p.swaps)))
    print("치환 대상 %d편 / 손대지 않음 %d편" % (len(ok), len(bad)))
    if "--apply" not in argv:
        print("  (dry-run — 실제로 쓰려면 --apply)")
        return 1 if bad else 0
    apply(plans, root)
    print("적용 완료 %d편%s" % (len(ok), " (자산 %d개 생성)" % sum(len(p.writes) for p in ok)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
