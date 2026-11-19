"""직전 발행본에서 작성자가 쓰는 부분만 잘라 준다 — 복기 절·전략 코멘트 lede·제목·(KR) 향후 확인 일정.

작성자는 직전 발행본 전체(US ~105 KB, KR ~68 KB)를 읽어 왔다. 지시된 쓰임은 TRADER_LEARNING 「Research handoff」
1 하나다 — 직전 글의 학습 질문·시험 조건·기한(「learning block only, not the editor's personal note」). 고르는 글과
자르는 자리는 계산할 수 있으니 코드가 한다(2026-11-19).

- 글은 **커밋 하나**에서만 읽는다(작업 트리의 고친 글·커밋 안 된 글을 넘기지 않는다).
- 상태: ok(조각) · full(조각을 깨끗이 못 잘라 커밋된 글 전체) · bootstrap(직전 글 없음·복기 절 없음) ·
  error(git 실패 — bootstrap 으로 읽히면 안 된다, exit 2, 파일을 남기지 않는다. 다른 출처를 짐작하지 않는다 —
  부른 쪽이 지금까지처럼 직전 발행본 경로를 넘긴다).

`digest`·`pick` 은 순수 함수, `run` 이 git 을 부른다. CLI 는 `scripts/prev_post_digest.py`.
"""
import os
import re
import subprocess

from common.numbers import TAG_RE

DIRS = {'us': 'posts/', 'kr': 'kr/posts/'}
SCHEDULE_H2 = '향후 확인 일정'
_NAME = re.compile(r'<\s*(/?)\s*([a-zA-Z][\w-]*)')
_VOID = frozenset(('br', 'hr', 'img', 'meta', 'link', 'input', 'source', 'wbr', 'area', 'base', 'embed',
                   'param', 'track', 'col'))
_RAW_NAMES = frozenset(('script', 'style'))


class Unbalanced(Exception):
    pass


def pick(names, market, date):
    """커밋된 파일 이름들 → 날짜가 date 보다 앞선 가장 최근 일간 글 (path, date) 또는 None."""
    rx = re.compile(re.escape(DIRS[market]) + r'(\d{4}-\d{2}-\d{2})\.html$')
    best = None
    for n in names:
        m = rx.fullmatch(n)
        if m and m.group(1) < date and (best is None or m.group(1) > best[1]):
            best = (n, m.group(1))
    return best


def _attr(raw, name):
    return re.search(r'\s%s(?=[\s=>/])' % re.escape(name), raw) is not None


_FOREIGN = frozenset(('svg', 'math'))      # 이 안에서만 `<path …/>` 같은 자기 닫음이 요소 하나다


def elements(html):
    """→ [(이름, 시작 태그 원문, 시작, 끝)] 문서 순서. 짝이 하나라도 어긋나면 Unbalanced.

    느슨하게 읽지 않는다 — 안 닫힌 요소를 건너뛰며 읽으면 실어야 할 조각이 말없이 빠진 채 ok 가 된다
    (2026-11-19 codex 구현 검토 1·2회차). HTML 요소의 `<p …/>` 는 자기 닫음이 아니라 시작 태그다.
    주석·선언·script/style 안은 보지 않는다.
    """
    out, stack, raw_in = [], [], None
    for m in TAG_RE.finditer(html):
        raw = m.group(0)
        n = _NAME.match(raw)
        if raw_in:                      # script/style 안 — 그 끝 태그만 본다(주석처럼 보이는 것도 글이다)
            if not (n and n.group(1) and n.group(2).lower() == raw_in):
                continue
            raw_in = None
        elif raw.startswith('<!') or raw.startswith('<?'):
            continue                    # 주석·선언 — 안에 적힌 <script> 는 태그가 아니다(codex 구현 검토 3회차)
        if not n:
            raise Unbalanced('읽을 수 없는 태그(%d)' % m.start())
        name = n.group(2).lower()
        if name in _VOID:
            continue
        if not n.group(1):
            if raw.endswith('/>') and (name in _FOREIGN or any(t in _FOREIGN for t, _, _ in stack)):
                continue
            stack.append((name, raw, m.start()))
            if name in _RAW_NAMES:
                raw_in = name
            continue
        if not stack or stack[-1][0] != name:
            raise Unbalanced('%s 의 짝이 맞지 않는다(%d)' % (name, m.start()))
        _, start_raw, at = stack.pop()
        out.append((name, start_raw, at, m.end()))
    if stack:
        raise Unbalanced('닫히지 않은 %s' % stack[-1][0])
    return sorted(out, key=lambda e: e[2])


def _is_schedule(text):
    return re.sub(r'<[^>]+>|\s+', '', text) == SCHEDULE_H2.replace(' ', '')


def digest(html, market):
    """→ (state, body). ok = 조각을 이은 글, full = 글 전체, bootstrap = ''.

    글 전체의 태그 짝이 맞을 때만 자른다(실제 발행본 88편이 모두 맞는다, 2026-11-19 실측). 하나라도 어긋나면
    어느 조각이 빠졌는지 알 수 없으니 full — 읽는 쪽은 지금까지처럼 글 전체를 본다.
    """
    if not re.search(r'<[a-zA-Z][^>]*\sdata-learning(?=[\s=>/])', html):
        return 'bootstrap', ''
    try:
        els = elements(html)
    except Unbalanced:
        return 'full', html
    notes = [(s, e) for _, raw, s, e in els if _attr(raw, 'data-editor-note')]
    want = [(s, e) for name, _, s, e in els if name == 'h1'][:1]
    want.extend((s, e) for _, raw, s, e in els if _attr(raw, 'data-lede') or _attr(raw, 'data-learning'))
    if market == 'kr':
        for name, raw, s, e in els:
            if name == 'h2' and _is_schedule(html[s + len(raw):e]):
                boxes = [(a, b) for n2, _, a, b in els if n2 == 'section' and a < s and e <= b]
                if not boxes:
                    return 'full', html
                want.append(max(boxes))            # 가장 안쪽 section
    if not any(_attr(raw, 'data-learning') for _, raw, _, _ in els):
        return 'full', html                        # 표식이 주석·script 안에만 있다 — 짐작하지 않는다
    want = sorted(set(want))
    top = [w for w in want if not any(o != w and o[0] <= w[0] and w[1] <= o[1] for o in want)]
    top = [w for w in top if not any(a <= w[0] and w[1] <= b for a, b in notes)]
    parts = []
    for s, e in top:
        piece, at = [], s
        for a, b in sorted(notes):
            if s <= a and b <= e and a >= at:
                piece.append(html[at:a])
                at = b
        piece.append(html[at:e])
        parts.append(''.join(piece))
    return 'ok', '\n\n'.join(parts) + '\n'


def _git(repo, *args):
    r = subprocess.run(['git', '-C', repo, *args], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError('git %s: %s' % (args[0], r.stderr.decode('utf-8', 'replace').strip()[:200]))
    return r.stdout


def run(market, date, repo, out):
    """→ (exit, 마지막 줄). ok·full·bootstrap = 0(out 을 쓴다), error = 2(out 을 남기지 않는다)."""
    if os.path.exists(out):
        os.remove(out)
    try:
        commit = _git(repo, 'rev-parse', '--verify', 'HEAD^{commit}').decode().strip()
        names = _git(repo, 'ls-tree', '--name-only', commit, DIRS[market]).decode('utf-8', 'replace').splitlines()
        got = pick(names, market, date)
        if got is None:
            state, body, path, pdate, blob = 'bootstrap', '', '-', '-', '-'
        else:
            path, pdate = got
            blob = _git(repo, 'rev-parse', '%s:%s' % (commit, path)).decode().strip()
            state, body = digest(_git(repo, 'show', '%s:%s' % (commit, path)).decode('utf-8', 'replace'), market)
    except (RuntimeError, OSError) as exc:
        return 2, 'prev_post: error %s' % str(exc).replace('\n', ' ')[:200]
    note = {'ok': '직전 발행본에서 코드가 잘라 낸 조각(제목·전략 코멘트 lede·복기 절·KR 향후 확인 일정) — 글자 그대로다',
            'full': '조각을 자르지 못해 커밋된 글 전체를 싣는다',
            'bootstrap': '직전 글이 없거나 복기 절이 없다 — bootstrap, 이전 질문을 지어내지 않는다'}[state]
    head = '<!-- prev_post: %s · path %s · date %s · commit %s · blob %s · %s -->\n' % (
        state, path, pdate, commit, blob, note)
    with open(out, 'w', encoding='utf-8') as fh:
        fh.write(head + body)
    return 0, 'prev_post: %s %s %s %s (%d B)' % (state, path, pdate, commit, len((head + body).encode('utf-8')))
