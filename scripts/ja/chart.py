"""수익률 곡선 그림의 일본어판 — `ja/assets/yield_curve_<date>.png`.

    python3 -m scripts.ja.chart 2026-11-13 [더 많은 날짜…]

한글 그림(`assets/yield_curve_<date>.png`)을 그린 **입력을 같은 값으로 되살려** 라벨만 일본어로 다시 그린다.

입력을 되살리는 길(`restore`): 수집기(`collect_market_data.py`)는 한 번 돌 때 `market_data.json` 의
`yields` 로 `data/yield_curve.png` 를 그려 둘을 같은 커밋에 넣고(값이 같아 PNG 가 같은 바이트면 git 에는
json 변경만 남는다), 발행 루틴은 그 PNG 를 `assets/yield_curve_<date>.png` 로 복사한다. 그래서 ① 한글 그림의
git blob 을 구하고 ② `data/market_data.json` 을 바꾼 커밋 가운데 그 시점 트리의 `data/yield_curve.png` 가 같은
blob 이고 ③ `report_date` 가 그 날짜인 것의 `yields` 를 읽는다. 그런 커밋이 여럿이면 넷 만기의 값이 모두
같아야 한다. 수집기가 그림을 건너뛴 실행(1주 전 값 결측)은 `yields` 에 빈 값이 있어 걸러진다.
`data/history/market.jsonl` 은 1주 전 값·날짜·출처가 없어 같은 값을 줄 수 없다.
되살리지 못하면(2026-07-10·07-13 처럼 그림을 루틴이 직접 그린 날, 얕은 클론, git 없음) 그리지 않고
`None` + 사유 — 호출한 쪽이 그 글을 보류한다.

글꼴: macOS 의 Hiragino. 그리기 전에 그 글꼴 파일의 문자표에 그림에 쓸 모든 글자가 있는지 보고, 그리는 동안
matplotlib 의 「Glyph … missing」 경고를 받아 하나라도 있으면 파일을 남기지 않는다(깨진 글자 □ 방지).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1]

JA_LABELS = {
    "today": "当日 ({date})",
    "week_ago": "1週間前 ({date})",
    "note": "* {note} 時点（その他は Yahoo スポット {date}）",
}
JA_FONTS = ("Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK JP", "Noto Sans JP")
TENORS = ("2Y", "5Y", "10Y", "30Y")
FIELDS = ("level", "week_ago", "date", "week_ago_date", "source")
PNG = "data/yield_curve.png"
DATA = "data/market_data.json"


def asset_rel(date: str) -> str:
    return f"assets/yield_curve_{date}.png"


def out_rel(date: str) -> str:
    return f"ja/assets/yield_curve_{date}.png"


def blob_sha(raw: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(raw) + raw).hexdigest()


def _git(root, *args):
    try:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return subprocess.CompletedProcess(args, 1, "", str(e))


def collector_runs(root, blob: str) -> list | None:
    """`data/market_data.json` 을 바꾼 커밋(수집기 한 번의 실행) 가운데, 그 시점 트리의
    `data/yield_curve.png` 가 이 blob 인 것(최신 먼저). git 이 실패하면 None.

    트리 상태로 본다 — 채권 휴장일처럼 값이 그대로면 수집기가 다시 그린 PNG 가 같은 바이트라 git 이
    PNG 변경을 기록하지 않는다(2026-11-11 실측: 그날 그림은 11-10 커밋의 blob 이다)."""
    r = _git(root, "log", "--format=%H", "--", DATA)
    if r.returncode:
        return None
    commits = r.stdout.split()
    if not commits:
        return []
    try:
        q = subprocess.run(["git", "-C", str(root), "cat-file", "--batch-check"],
                           input="".join(f"{c}:{PNG}\n" for c in commits),
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if q.returncode:
        return None
    lines = q.stdout.splitlines()
    if len(lines) != len(commits):
        return None
    return [c for c, line in zip(commits, lines) if line.split()[:1] == [blob]]


def _subset(yields):
    """그림이 읽는 값만 — 넷 만기 × FIELDS. 빠진 값이 있으면 None."""
    out = {}
    for t in TENORS:
        row = yields.get(t) if isinstance(yields, dict) else None
        if not isinstance(row, dict) or row.get("level") is None or row.get("week_ago") is None:
            return None
        out[t] = {k: row.get(k) for k in FIELDS}
    return out


def restore(root, date: str):
    """(yields, 사유). 같은 값으로 되살리지 못하면 (None, 사유)."""
    root = Path(root)
    asset = root / asset_rel(date)
    if not asset.is_file():
        return None, f"한글판 그림 {asset_rel(date)} 이 없다"
    blob = blob_sha(asset.read_bytes())
    commits = collector_runs(root, blob)
    if commits is None:
        return None, "git 이력을 읽지 못했다"
    if not commits:
        return None, (f"{asset_rel(date)} 와 같은 그림을 남긴 수집 커밋이 없다 — 루틴이 직접 그린 날이거나 "
                      "얕은 클론이다")
    seen, why = {}, []
    for c in commits:
        shown = _git(root, "show", f"{c}:{DATA}")
        try:
            data = json.loads(shown.stdout) if shown.returncode == 0 else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            why.append(f"{c[:8]}:{DATA} 를 읽지 못했다")
            continue
        if data.get("report_date") != date:
            why.append(f"{c[:8]} 의 report_date {data.get('report_date')} ≠ {date}")
            continue
        sub = _subset(data.get("yields"))
        if sub is None:
            why.append(f"{c[:8]} 의 yields 에 빠진 값이 있다")
            continue
        seen[json.dumps(sub, sort_keys=True)] = sub
    if not seen:
        return None, "; ".join(why) or "쓸 수 있는 수집 커밋이 없다"
    if len(seen) > 1:
        return None, f"같은 그림을 만든 커밋 {len(commits)}개의 값이 갈린다"
    return next(iter(seen.values())), None


def drawn_text(yields, labels=JA_LABELS) -> str:
    """그림에 들어가는 모든 글자 — 글꼴 검사용. `render_curve` 가 그리는 문자열과 같은 재료."""
    t_date, w_date = yields["10Y"]["date"], yields["10Y"]["week_ago_date"]
    parts = [labels["today"].format(date=t_date), labels["week_ago"].format(date=w_date),
             "".join(TENORS), "*", "0123456789.%+-bp"]
    odd = [t for t in TENORS if yields[t].get("date") != t_date]
    if odd:
        note = " · ".join(f"{t} {yields[t].get('source', '?')} {yields[t]['date']}" for t in odd)
        parts.append(labels["note"].format(note=note, date=t_date))
    return "".join(parts)


def pick_font(fonts=JA_FONTS):
    """`render_curve` 와 같은 규칙으로 고른 글꼴 (이름, 파일). 없으면 (None, None)."""
    from matplotlib import font_manager
    for f in fonts:
        if any(f.lower() in x.name.lower() for x in font_manager.fontManager.ttflist):
            path = font_manager.findfont(font_manager.FontProperties(family=f), fallback_to_default=False)
            return f, path
    return None, None


def missing_glyphs(text: str, font_path: str) -> list:
    from matplotlib import ft2font
    cmap = ft2font.FT2Font(font_path).get_charmap()
    return sorted({ch for ch in text if not ch.isspace() and ord(ch) not in cmap})


def _render_curve():
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    import collect_market_data
    return collect_market_data.render_curve


def render_why(root, date: str, dest_root=None):
    """(만든 파일, None) 또는 (None, 사유). 파일은 `dest_root`(기본 root) 의 `ja/assets/` 에."""
    root = Path(root)
    try:
        import matplotlib  # noqa: F401
    except ImportError:
        return None, "matplotlib 이 없다"
    yields, why = restore(root, date)
    if yields is None:
        return None, why
    family, path = pick_font()
    if family is None:
        return None, f"일본어 글꼴이 없다({', '.join(JA_FONTS)})"
    lost = missing_glyphs(drawn_text(yields, JA_LABELS), path)
    if lost:
        return None, f"글꼴 {family} 에 없는 글자: {''.join(lost)}"
    dest = Path(dest_root or root) / out_rel(date)
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=dest.stem + ".", suffix=".png", dir=dest.parent)
    os.close(fd)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _render_curve()(yields, tmp, labels=JA_LABELS, fonts=(family,))
        tofu = [str(w.message) for w in caught if "missing from" in str(w.message)]
        if tofu:
            return None, f"깨진 글자: {tofu[0]}"
        os.replace(tmp, dest)
        tmp = None
    finally:
        if tmp and os.path.exists(tmp):
            os.unlink(tmp)
    return dest, None


def render(root, date: str, dest_root=None):
    """`ja/assets/yield_curve_<date>.png` 의 경로, 만들지 못했으면 None(사유는 `render_why`)."""
    return render_why(root, date, dest_root)[0]


def main(argv):
    root = SCRIPTS.parent
    code = 0
    for date in argv:
        path, why = render_why(root, date)
        if path:
            print(f"{date}: {path.relative_to(root)}")
        else:
            print(f"{date}: 만들지 않음 — {why}")
            code = 1
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
