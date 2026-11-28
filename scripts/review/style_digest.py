#!/usr/bin/env python3
"""문체 지적의 주간 묶음 — 사람이 보고 STYLE_EXEMPLARS·작성 지시문을 고칠지 정한다. **아무것도 고치지 않고, 아무 파일도 쓰지 않는다.**

  python3 scripts/review/style_digest.py [--since 7d] [--root .] [--private] [--patterns ../clarity-patterns.json]

읽는 것: `reviews/style_findings/*.json`(git 제외, 발행 뒤 러너가 쓴다)과 `reviews/prepublish/*/*.json`(발행 전 검토,
발행 커밋에 함께 들어간다)의 `style_findings`, 그리고 발행 전 검토의 명료성 지적(`clarity`, 2026-11-18).

명료성 지적은 **되풀이되는 원인**을 찾는 데 쓴다 — 문장을 하나씩 고쳐 쓰는 목록이 아니다. 자동으로 내는 것은
「지적 표현의 발행본 잔존 여부」(그 글자가 처음 발행된 글에 남았는가)까지다. 그것은 **실제로 나아졌는지의 증거가
아니다** — 다른 수정으로 지워졌을 수도, 인용(앞 40자) 뒤쪽만 바뀌었을 수도 있다. 나아졌는지는 사람이 본다.

`--private` 는 비공개 저장소의 검토 원문에서 지적의 이유를 읽어 **화면에만** 찍는다. 검토자가 쓴 글은 공개
저장소에 옮기지 않는다 — 이 출력을 저장소 안 파일로 돌리지(`>`) 않는다. `--patterns` 는 사람이 이름 붙인 꼴의
목록(공개 저장소 밖에 둔다)으로, 지시문을 고친 날 뒤 발행본에 그 낱말이 다시 나온 글을 센다.
"""

import argparse
import glob
import json
import os
import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

if __package__ in (None, ''):      # 스크립트로 돌 때 — `prepub.public`(같은 글자 읽기)을 찾을 수 있게
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from prepub.public import norm, visible  # noqa: E402

FOLDER = 'reviews/style_findings'
PREPUB = 'reviews/prepublish'
POSTS = {'us': 'posts/%s.html', 'kr': 'kr/posts/%s.html'}
RUNNER_REPO = 'fdo2a/review-runner'
_RID = re.compile(r'^(us|kr|jp|us-news)-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}$')
_DAY = re.compile(r'^\d{4}-\d{2}-\d{2}$')
KIND_ORDER = ('용어', '문장 구조', '지시 대상 불명확', '논리·사실관계 의심')
TELL = {'가': '무엇이 일어났는지', '나': '어떤 판단인지', '다': '무엇을 가리키는지'}
_MARK = re.compile(r'^\s*\(?\s*(가|나|다)\s*\)')   # `prepub.split._TELL` 과 같은 꼴


def _since(spec):
    spec = spec.strip().lower()
    if spec.endswith('d') and spec[:-1].isdigit():
        return datetime.now(timezone.utc) - timedelta(days=int(spec[:-1]))
    return datetime.fromisoformat(spec).replace(tzinfo=timezone.utc)


def _at(text):
    try:
        t = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def collect(root, since):
    rows = []
    for path in sorted(glob.glob(os.path.join(root, FOLDER, '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        at = _at(rec.get('at'))
        if at is None or at < since:
            continue
        for f in rec.get('findings') or ():
            if isinstance(f, dict):
                rows.append(dict(f, path=rec.get('path', ''), at=rec.get('at')))
    for path in sorted(glob.glob(os.path.join(root, PREPUB, '*', '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        at = _at(rec.get('recorded_at'))
        if at is None or at < since:
            continue
        where = f"{rec.get('section', '')} {rec.get('date', '')} (발행 전)"
        for f in rec.get('style_findings') or ():
            if isinstance(f, dict):
                rows.append(dict(f, path=where, at=rec.get('recorded_at')))
    return rows


def digest(rows, examples=3):
    by = defaultdict(list)
    for r in rows:
        by[r.get('kind') or '기타'].append(r)
    posts = len({r['path'] for r in rows})
    out = ['문체 지적 묶음 — %d건, 글 %d편' % (len(rows), posts)]
    for kind, items in sorted(by.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append('\n[%s] %d건' % (kind, len(items)))
        for r in items[:examples]:
            out.append('  - %s 「%s」 — %s' % (r['path'], r.get('quote', ''), r.get('note', '')))
    return '\n'.join(out)


# ── 명료성 지적(발행 전 검토, 2026-11-18) ─────────────────────────────────────────

def prepub_records(root, since):
    """발행 전 검토 기록(그 기간) — 읽지 못하는 파일은 건너뛴다."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, PREPUB, '*', '*.json'))):
        try:
            with open(path, encoding='utf-8') as fh:
                rec = json.load(fh)
        except (OSError, ValueError):
            continue
        at = _at(rec.get('recorded_at')) if isinstance(rec, dict) else None
        if at is not None and at >= since:
            out.append(rec)
    return out


def collect_clarity(root, since):
    rows = []
    for rec in prepub_records(root, since):
        for c in rec.get('clarity') or ():
            if isinstance(c, dict):
                rows.append(dict(c, section=rec.get('section', ''), date=rec.get('date', ''),
                                 request_id=rec.get('request_id', '')))
    return rows


def _git(root, *args):
    r = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def publish_text(root, row):
    """그 글이 **처음 올라간 커밋**의 글자(독자가 보는 글) — 발행 뒤 정정이 섞이지 않게. 못 읽으면 None.

    지웠다 다시 올린 글은 올린 커밋이 여럿이다 — 가장 오래된 것을 본다.
    """
    section, date = row.get('section'), str(row.get('date') or '')
    if section not in POSTS or not _DAY.match(date):
        return None
    path = POSTS[section] % date
    added = _git(root, 'log', '--diff-filter=A', '--format=%H', '--', path)
    shas = (added or '').split()
    if not shas:
        return None
    html = _git(root, 'show', f'{shas[-1]}:{path}')
    return None if html is None else visible(html)


def residual(row, text):
    """지적 표현의 발행본 잔존 여부. 「없음」은 그 글자가 없다는 뜻일 뿐 — 나아졌다는 판정이 아니다."""
    quote = norm(row.get('quote') or '')
    if not quote or text is None:
        return '알 수 없음'
    return '남아 있음' if quote in text else '없음'


def fetch_review(rid):
    """비공개 저장소의 검토 원문 → 글. 못 읽으면 None. 화면에 찍는 데만 쓴다 — 어디에도 저장하지 않는다."""
    if not _RID.match(rid or ''):
        return None
    r = subprocess.run(['gh', 'api', f'repos/{RUNNER_REPO}/contents/results/{rid}.json', '--jq', '.content'],
                       capture_output=True, text=True)
    if r.returncode:
        return None
    try:
        import base64
        return json.loads(base64.b64decode(r.stdout)).get('review')
    except (ValueError, AttributeError):
        return None


def _private_notes(review):
    """검토 원문 → {(분류, 인용 앞 40자): 이유 글}. 표식 아래의 지적 줄만 읽는다.

    분류까지 맞춰 찾는다 — 같은 대목을 두 분류가 짚으면 이유가 다르다. 발행 전 읽기는 명료성 분류의 인용 안
    표식 「(나) …」을 떼어 기록하므로 그 꼴로도 찾되, 글자 그대로 맞는 줄이 먼저다. 공개 인용은 앞 40자뿐이라
    **같은 열쇠에 줄이 둘 이상이면 어느 이유인지 짐작하지 않고 버린다**(자리 찾기 `split._place` 와 같은 원칙).
    """
    import review_gate as gate
    at = (review or '').rfind(gate.STYLE_FINDINGS_HEAD)
    exact, bare = {}, {}
    if at < 0:
        return {}
    for line in review[at + len(gate.STYLE_FINDINGS_HEAD):].splitlines():
        m = gate._FINDING_RE.match(line)
        if not (m and m.group(2)):
            continue
        kind, quote, why = m.group(1).strip(), norm(m.group(2)), m.group(3).strip()
        exact.setdefault((kind, quote[:40]), []).append(why)
        if kind in KIND_ORDER and _MARK.match(quote):
            bare.setdefault((kind, _MARK.sub('', quote, count=1).strip()[:40]), []).append(why)
    out = {}
    for key in set(exact) | set(bare):
        lines = exact.get(key) or bare.get(key)      # 글자 그대로 맞는 줄이 있으면 그것만 본다
        if len(lines) == 1:
            out[key] = lines[0]
    return out


def load_patterns(path, root):
    """꼴 목록 → (목록, 오류 글). 공개 저장소 안의 파일은 받지 않는다 — 손으로 쓴 메모가 발행 커밋에 딸려 가지 않게."""
    real = os.path.realpath(path)
    top = (_git(root, 'rev-parse', '--show-toplevel') or '').strip()   # `--root` 가 하위 폴더여도 저장소 전체를 본다
    for base in {os.path.realpath(root)} | ({os.path.realpath(top)} if top else set()):
        if real == base or real.startswith(base + os.sep):
            return None, '꼴 목록은 공개 저장소 밖에 둔다(예: 프로젝트 루트의 clarity-patterns.json)'
    try:
        with open(real, encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        return None, f'꼴 목록을 읽지 못했다: {type(exc).__name__}'
    return [p for p in data if isinstance(p, dict) and p.get('name')] if isinstance(data, list) else [], None


def _recurrence(root, pattern):
    """지시문·표본을 고친 날 뒤에 처음 발행된 글 가운데 그 낱말이 다시 나온 글 수 → (나온 글, 본 글).

    검토자의 지적 건수로 세지 않는다 — 검토자가 덜 찾으면 좋아진 것처럼 보인다. 낱말만 바뀐 같은 꼴은 놓친다.
    """
    fixed, words = str(pattern.get('fixed_on') or ''), [w for w in pattern.get('words') or () if isinstance(w, str) and w]
    if not _DAY.match(fixed) or not words:
        return None
    seen = hit = 0
    for path in sorted(glob.glob(os.path.join(root, 'posts', '*.html'))):
        date = os.path.basename(path)[:-5]
        if not _DAY.match(date) or date <= fixed:
            continue
        text = publish_text(root, {'section': 'us', 'date': date})
        if text is None:
            continue
        seen += 1
        hit += any(w in text for w in words)
    return hit, seen


def clarity_digest(root, since, private=False, patterns=None, examples=3):
    records = [r for r in prepub_records(root, since) if 'clarity' in r]
    rows = collect_clarity(root, since)
    if not records and not patterns:
        return ''
    texts = {}

    def text_of(r):
        key = (r.get('section'), r.get('date'))
        if key not in texts:
            texts[key] = publish_text(root, r)
        return texts[key]

    for r in rows:
        r['residual'] = residual(r, text_of(r))
    out = ['', '명료성 지적(발행 전 검토) — %d건, 글 %d편' % (len(rows), len(records))]
    if rows:
        by = {k: [r for r in rows if r.get('kind') == k] for k in KIND_ORDER}
        out.append('  분류별: ' + ' · '.join('%s %d' % (k, len(v)) for k, v in by.items()))
        path = [r for r in rows if r.get('route') == 'style_path']
        cand = [r for r in path if r.get('placed') == 'candidate']
        out.append('  가는 길: 문체 길 %d(후보 %d · 자리 못 찾음 %d · 보호 구간 %d) · 기록만 %d · 정확성 검토로 %d' % (
            len(path), len(cand), sum(r.get('placed') == 'not_located' for r in path),
            sum(r.get('placed') == 'protected' for r in path),
            sum(r.get('route') == 'record_only' for r in rows), sum(r.get('route') == 'accuracy' for r in rows)))
        res = {k: sum(r['residual'] == k for r in cand) for k in ('남아 있음', '없음', '알 수 없음')}
        out.append('  지적 표현의 발행본 잔존 여부(문체 길 후보 %d건): ' % len(cand)
                   + ' · '.join('%s %d' % kv for kv in res.items()))
        out.append('    ※ 처음 발행된 글에 그 글자가 남았는지만 본다. 「없음」은 나아졌다는 뜻이 아니다 — 다른 수정으로 '
                   '지워졌을 수도, 인용(앞 40자) 뒤쪽만 바뀌어 「남아 있음」으로 잡혔을 수도 있다. '
                   '실제로 뜻이 전해지게 됐는지는 초안과 발행본을 나란히 읽어 사람이 본다.')
    if records:
        def total(key):
            return sum(v for v in (r.get(key) for r in records) if isinstance(v, int) and not isinstance(v, bool))
        states = {}
        for r in records:
            if r.get('state') != 'reviewed':
                states[str(r.get('state'))] = states.get(str(r.get('state')), 0) + 1
        out.append('  그날 집계(문체 길에서 반영되지 않은 까닭 — 지적별이 아니라 그날 합계다): '
                   '가드 기각 %d · 판단 뼈대 기각 %d · 의미 검사 기각 %d' % (
                       total('style_rejected'), total('skeleton_rejected'), total('checker_rejected'))
                   + (' · 검토를 못 마친 날 ' + ', '.join('%s %d' % kv for kv in sorted(states.items())) if states else ''))
        metas = [r.get('clarity_meta') or {} for r in records]
        out.append('  읽기 상태: 인용이 빈 지적 %d건 · 표식 없는 답 %d일 · 읽히지 않은 줄 %d · 상한 초과 %d' % (
            sum(not norm(r.get('quote') or '') for r in rows), sum(m.get('marker') is not True for m in metas),
            sum(m.get('lines_skipped') or 0 for m in metas), sum(m.get('over_cap') or 0 for m in metas)))
        out.append('    ※ 지적 건수가 줄었다고 글이 나아진 것은 아니다 — 검토자가 덜 찾았거나 답의 꼴이 깨졌을 수 있다.')
    notes, missing_days, unmatched = {}, 0, 0
    if private:
        for rec in records:
            if not rec.get('clarity'):
                continue
            review = fetch_review(rec.get('request_id') or '')
            if review is None:
                missing_days += 1
                continue
            notes[rec.get('request_id')] = _private_notes(review)
    for kind in KIND_ORDER:
        items = [r for r in rows if r.get('kind') == kind]
        if not items:
            continue
        out.append('\n  [%s] %d건' % (kind, len(items)))
        for r in items[:examples] if not private else items:
            tell = TELL.get(r.get('cannot_tell'), '')
            out.append('    - %s %s 「%s」%s → %s' % (
                r['section'], r['date'], r.get('quote', ''), ' (%s)' % tell if tell else '',
                {'record_only': '기록만', 'accuracy': '정확성 검토로'}.get(
                    r.get('route'), {'candidate': '발행본에 ' + r['residual'], 'not_located': '자리 못 찾음',
                                     'protected': '보호 구간'}.get(r.get('placed'), '알 수 없음'))))
            if private and r.get('request_id') in notes:
                why = (notes[r['request_id']].get((r.get('kind'), norm(r.get('quote') or '')[:40]))
                       if r.get('quote') else None)
                if why:
                    out.append('        이유(비공개 원문): ' + why)
                else:
                    unmatched += 1
    if private:
        out.append('\n  비공개 원문: 원문 없음 %d일 · 원문에서 이유를 찾지 못한 지적 %d건 '
                   '(이 출력은 화면용이다 — 저장소 안 파일로 옮기지 않는다)' % (missing_days, unmatched))
    for p in patterns or ():
        got = _recurrence(root, p)
        if got is None:
            out.append('\n  되풀이되는 꼴 「%s」 — 고친 날·낱말이 적히지 않았다' % p['name'])
        else:
            out.append('\n  되풀이되는 꼴 「%s」 — 고친 날(%s) 뒤 발행본 %d편 중 %d편에 다시 나옴' % (
                p['name'], p.get('fixed_on'), got[1], got[0]))
    if patterns:
        out.append('    ※ 낱말이 발행본에 다시 나왔는지로 센다(검토자의 지적 건수가 아니다). 낱말만 바뀐 같은 꼴은 놓친다 — '
                   '이 수만으로 지시문을 고친 효과를 단정하지 않는다. 다시 나오면 금지어를 더하기 전에 그 표현을 '
                   '끌어낸 지시문 문구·자료의 이름·표본을 먼저 본다.')
    return '\n'.join(out)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--since', default='7d')
    ap.add_argument('--root', default='.')
    ap.add_argument('--examples', type=int, default=3)
    ap.add_argument('--private', action='store_true',
                    help='비공개 저장소의 검토 원문에서 지적의 이유를 읽어 화면에만 찍는다')
    ap.add_argument('--patterns', default=None, help='사람이 이름 붙인 꼴의 목록(JSON, 공개 저장소 밖)')
    args = ap.parse_args(argv)
    patterns = None
    if args.patterns:
        patterns, err = load_patterns(args.patterns, args.root)
        if err:
            print(err)
            return 2
    since = _since(args.since)
    print(digest(collect(args.root, since), args.examples))
    extra = clarity_digest(args.root, since, private=args.private, patterns=patterns, examples=args.examples)
    if extra:
        print(extra)
    return 0


if __name__ == '__main__':
    sys.exit(main())
