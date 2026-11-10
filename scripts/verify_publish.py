#!/usr/bin/env python3
"""발행 건별 알림의 계산 — GitHub Actions `publish-watch.yml`(2.5단계, 2026-11-10).

    python3 scripts/verify_publish.py --github              # Actions: fetch → 사건 계산 → 상태 브랜치 push → Worker poke
    python3 scripts/verify_publish.py --dry-run             # 맥: 지금 계산하면 outbox 에 실릴 문장만 출력(쓰기·push 없음)
    python3 scripts/verify_publish.py --preview us 2026-11-10   # 맥: 글 하나의 알림 미리보기(상태 무관)

US·KR 일간이 올라오면 그 발행의 발행 전 기록을 읽어, 직접 대조한 짝과 루틴이 남긴 검사 결과를 나눠 사건으로 만든다.
거래 세션의 기준 시각까지 글이 없으면 미발행을, 그 뒤 올라오면 해소를 만든다.

**이 파일은 텔레그램으로 보내지 않는다.** 토큰은 공개 레포 밖 Cloudflare Worker 에만 있다. 여기서는 상태 브랜치
`alerts-state` 에 계산 상태(`verify_publish.json`)와 보낼 사건(`outbox.json`)을 한 커밋으로 올리고, Worker 에 빈 poke 를
보낼 뿐이다. Worker 가 `/acks`·`/failed` 로 알려 준 사건만(id 와 본문 해시가 둘 다 맞을 때) outbox 에서 뺀다. 비밀값·pip 의존성 없음.
맥 launchd 로는 돌리지 않는다(`runner_launch.py` 의 `publish` 진입점은 지웠다).
설계: docs/superpowers/specs/2026-11-08-telegram-prepub-records.md(2.5단계 절)
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import urllib.request
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from review import prepub_view as V  # noqa: E402
from review import publish_watch as W  # noqa: E402

STATE_BRANCH = 'alerts-state'
STATE_REF = f'refs/remotes/origin/{STATE_BRANCH}'
STATE_FILE, OUTBOX_FILE = 'verify_publish.json', 'outbox.json'
WORKER_ENV = 'ALERTS_WORKER_URL'
BOT = {'GIT_AUTHOR_NAME': 'github-actions[bot]', 'GIT_COMMITTER_NAME': 'github-actions[bot]',
       'GIT_AUTHOR_EMAIL': '41898282+github-actions[bot]@users.noreply.github.com',
       'GIT_COMMITTER_EMAIL': '41898282+github-actions[bot]@users.noreply.github.com'}
MAX_REJECTED = 3                  # push 거절 뒤 처음부터 다시 계산하는 횟수(설계 v3 #5) — 그 밖의 실패는 바로 끝낸다
HTTP_TIMEOUT = 10
HTTP_MAX = 1024 * 1024


class Fatal(Exception):
    """인증·네트워크·손상 — 다시 해 봐야 같은 실패. 0 이 아닌 코드로 끝낸다."""


def now_kst():
    return datetime.now(W.KST)


def repo_root():
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if out.returncode:
        sys.exit('git 레포 안에서 실행해야 한다.')
    return out.stdout.strip()


def _git(root, *args, env=None, data=None, timeout=120):
    """(코드, stdout bytes, stderr 꼬리). 메시지를 해석하는 자리가 있어 LC_ALL=C 로 고정한다."""
    full = dict(os.environ, LC_ALL='C', GIT_TERMINAL_PROMPT='0')
    full.update(env or {})
    try:
        out = subprocess.run(['git', '-C', root, *args], capture_output=True, input=data, env=full, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 255, b'', f'{type(exc).__name__}: {exc}'[:300]
    return out.returncode, out.stdout, out.stderr.decode('utf-8', 'replace').strip()[-300:]


def _must(root, *args, **kw):
    code, out, err = _git(root, *args, **kw)
    if code:
        raise Fatal(f'git {args[0]} 실패(코드 {code}) — {err}')
    return out


def fetch(root):
    code, _, _ = _git(root, 'fetch', '--quiet', 'origin', '+refs/heads/main:refs/remotes/origin/main')
    return code == 0


def fetch_state(root):
    """상태 브랜치를 받는다 → 있으면 True, 원격에 없으면 False. 못 물어봤으면 Fatal —
    네트워크 실패를 「없음」으로 읽으면 처음 실행인 줄 알고 전부 조용히 기준선으로 잡는다."""
    code, _, err = _git(root, 'ls-remote', '--exit-code', '--heads', 'origin', STATE_BRANCH)
    if code == 2:
        _git(root, 'update-ref', '-d', STATE_REF)          # 지워진 브랜치의 옛 사본을 상태로 읽지 않는다
        return False
    if code:
        raise Fatal(f'상태 브랜치 조회 실패(코드 {code}) — {err}')
    _must(root, 'fetch', '--quiet', 'origin', f'+refs/heads/{STATE_BRANCH}:{STATE_REF}')
    return True


def read_branch(root):
    """(부모 커밋 | None, 상태 파일 blob id | None, 상태 파일 bytes | None) — 받아 둔 상태 브랜치에서."""
    code, out, _ = _git(root, 'rev-parse', '--verify', '--quiet', f'{STATE_REF}^{{commit}}')
    if code:
        return None, None, None
    parent = out.decode().strip()
    row = _must(root, 'ls-tree', parent, '--', STATE_FILE).decode('utf-8', 'replace').strip()
    if not row:
        return parent, None, None
    blob = row.split()[2]
    return parent, blob, _must(root, 'cat-file', 'blob', blob)


def compute(root, now, acked, failed):
    """받아 둔 origin/main 과 상태 브랜치에서 **순수하게** 다시 계산한다 — 거절된 push 뒤에도 이 함수만 다시 부른다.
    → (상태, outbox, 부모 커밋, 그대로 둘 파일 {이름: blob id})."""
    parent, blob, raw = read_branch(root)
    keep = {}
    if parent is None:
        st = W.new_state('처음 실행했어요', baseline=True)
    elif raw is None:
        st = W.new_state('상태 파일이 없어져 새로 시작했어요')        # 브랜치는 있는데 파일이 없다 — 기준선으로 조용히 넘기지 않는다
    else:
        try:
            st = W.loads_state(raw)
        except W.StateError as exc:
            print(f'상태 파일 손상: {exc}', file=sys.stderr)
            # 손상본을 브랜치에 그대로 남긴다(같은 blob 을 다른 이름으로) — 새 상태가 덮어도 원인을 볼 수 있다
            keep[f'verify_publish.corrupt-{now:%Y%m%d%H%M%S}.json'] = blob
            st = W.new_state('상태 파일이 손상돼 복사해 두고 새로 시작했어요')
    W.step(st, root, now, True, who=V.GITHUB)
    # 계산 뒤에 뺀다 — 상태를 새로 시작해 같은 id 가 다시 만들어져도, 이미 전송된 것은 outbox 에 다시 싣지 않는다
    W.apply_acks(st, acked, failed, now)
    return st, W.build_outbox(st, now), parent, keep


def commit(root, parent, files, keep, message):
    """작업 트리·index 를 건드리지 않고 상태 브랜치 커밋을 만든다(임시 index). 부모의 다른 파일은 그대로 둔다."""
    fd, index = tempfile.mkstemp(prefix='alerts-index-')
    os.close(fd)
    os.unlink(index)
    env = dict(BOT, GIT_INDEX_FILE=index)
    try:
        _must(root, 'read-tree', *([parent] if parent else ['--empty']), env=env)
        entries = dict(keep)
        for name, body in files.items():
            entries[name] = _must(root, 'hash-object', '-w', '--stdin', data=body.encode('utf-8')).decode().strip()
        for name, blob in sorted(entries.items()):
            _must(root, 'update-index', '--add', '--cacheinfo', f'100644,{blob},{name}', env=env)
        tree = _must(root, 'write-tree', env=env).decode().strip()
        args = ['commit-tree', tree, '-m', message] + (['-p', parent] if parent else [])
        return _must(root, *args, env=env).decode().strip()
    finally:
        try:
            os.unlink(index)
        except OSError:
            pass


def push(root, sha):
    """'ok' | 'rejected'(다른 실행이 먼저 올렸다 — 다시 계산). 그 밖(인증·네트워크·원격 규칙)은 Fatal. 강제 push 없음."""
    code, out, err = _git(root, 'push', '--porcelain', 'origin', f'{sha}:refs/heads/{STATE_BRANCH}', timeout=180)
    if not code:
        return 'ok'
    text = out.decode('utf-8', 'replace')
    if any(line.startswith('!') and '[rejected]' in line for line in text.splitlines()):
        return 'rejected'
    raise Fatal(f'상태 브랜치 push 실패(코드 {code}) — {(err or text.strip())[-300:]}')


# ── Worker(공개 주소만 — 인증·비밀값 없음) ─────────────────────────────────

def worker_url():
    url = (os.environ.get(WORKER_ENV) or '').strip().rstrip('/')
    if url and not url.startswith('https://'):
        print(f'{WORKER_ENV} 가 https 주소가 아니다 — 쓰지 않는다', file=sys.stderr)
        return ''
    return url


def http_json(url):
    req = urllib.request.Request(url, headers={'Accept': 'application/json', 'User-Agent': 'publish-watch'})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        if resp.status != 200:
            raise ValueError(f'HTTP {resp.status}')
        body = resp.read(HTTP_MAX + 1)
    if len(body) > HTTP_MAX:
        raise ValueError('응답이 너무 크다')
    return json.loads(body.decode('utf-8'))


ACK_FORMAT = 'alerts-{name}/2'       # 계약 §2 — 모르는 판(옛 /1 포함)은 못 읽은 것으로 본다


def read_pairs(url, name):
    """Worker `/acks`·`/failed` → {(id, 보낸 본문 해시)}. 못 읽었거나 형식·판이 다르면 None — 그러면 outbox 에서
    아무것도 빼지 않는다."""
    if not url:
        return None
    try:
        obj = http_json(f'{url}/{name}')
    except Exception as exc:  # noqa: BLE001 — 시간 초과·연결·형식, 무엇이든 「못 읽음」
        print(f'Worker /{name} 못 읽음 — {type(exc).__name__}', file=sys.stderr)
        return None
    if not isinstance(obj, dict) or obj.get('format') != ACK_FORMAT.format(name=name):
        print(f'Worker /{name} 형식(판)이 다르다', file=sys.stderr)
        return None
    pairs = W.clean_pairs(obj.get('events'))
    if pairs is None:
        print(f'Worker /{name} 사건 형식이 다르다', file=sys.stderr)
    return pairs


def poke(url):
    """빈 요청으로 Worker 를 깨운다. 실패해도 다음 계기(예약·Worker cron)가 같은 outbox 를 읽는다 — 기록만 한다."""
    if not url:
        print(f'{WORKER_ENV} 가 비어 있어 poke 를 건너뛴다')
        return False
    try:
        req = urllib.request.Request(f'{url}/poke', data=b'', method='POST', headers={'User-Agent': 'publish-watch'})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            resp.read(1024)
        return True
    except Exception as exc:  # noqa: BLE001
        print(f'poke 실패(다음 계기에 읽힌다) — {type(exc).__name__}', file=sys.stderr)
        return False


# ── 실행 ─────────────────────────────────────────────────────────────────

def github(root):
    url = worker_url()
    acked, failed = read_pairs(url, 'acks'), read_pairs(url, 'failed')
    for _ in range(MAX_REJECTED + 1):
        now = now_kst()
        if not fetch(root):                              # 거절 뒤에도 main·상태 브랜치를 **둘 다** 다시 받는다
            raise Fatal('origin/main 을 받지 못했다')
        fetch_state(root)
        st, outbox, parent, keep = compute(root, now, acked, failed)
        if not st.get('last_seen'):
            raise Fatal(f'한 번도 정상 계산하지 못했다 — {st["fetch"].get("why", "사유 모름")}')
        sha = commit(root, parent, {STATE_FILE: W.dumps_state(st) + '\n', OUTBOX_FILE: W.dumps_outbox(outbox)}, keep,
                     f'alerts: {st["last_seen"][:7]} 기준, 보낼 사건 {len(outbox["events"])}건')
        if push(root, sha) == 'rejected':
            print('상태 브랜치 push 거절 — 최신을 다시 받아 처음부터 계산한다')
            continue
        poke(url)
        print(f'발행 알림 계산 — outbox {len(outbox["events"])}건, 기준점 {st["last_seen"][:7]}, '
              f'전송 확인 {"읽음" if acked is not None and failed is not None else "못 읽음(아무것도 빼지 않음)"}')
        if st['fetch']:                                  # 이번 회차는 읽지 못했다 — 실패 시작 시각은 올렸고, 실행은 빨갛게
            print(f'이번 계산은 읽기에 실패했다 — {st["fetch"].get("why")}', file=sys.stderr)
            return 1
        return 0
    print(f'상태 브랜치 push 가 {MAX_REJECTED + 1}번 거절됐다 — 다음 실행이 이어서 한다', file=sys.stderr)
    return 1


def dry_run(root, fetched):
    """지금 GitHub 이 계산하면 outbox 에 실릴 사건 — 아무것도 쓰지 않는다(상태 브랜치·Worker 전송 확인도 안 본다)."""
    if not fetched:
        print('⚠ fetch 안 함·실패 — 마지막으로 받아 둔 origin/main·상태 브랜치 기준', file=sys.stderr)
    st, outbox, _, _ = compute(root, now_kst(), None, None)
    for e in outbox['events']:
        print(f'{e["text"]}\n#{e["id"]} · {e["kind"]} · {e["key"]}\n')
    print(f'outbox {len(outbox["events"])}건(전송 확인을 읽지 않아, 이미 보낸 것도 들어 있다) · 기준점 '
          f'{(st.get("last_seen") or "-")[:7]}')
    return 0


def preview(root, market, date, fetched):
    """상태를 읽지도 쓰지도 않는다. 확인 주체는 맥(이 명령을 돌린 자리) — GitHub 알림 문장은 --dry-run 으로 본다."""
    if market not in V.TARGETS:
        print(f'시장은 {", ".join(V.TARGETS)} 중 하나', file=sys.stderr)
        return 2
    if not fetched:
        print('⚠ fetch 실패 — 마지막으로 받아 둔 origin/main 기준', file=sys.stderr)
    try:
        v = V.view(root, W.REF, market, date)
    except V.GitError as exc:
        print(f'읽지 못함: {exc}', file=sys.stderr)
        return 1
    print('── 발행 건별 알림 ──')
    print(V.render_publish(v))
    print('\n── 매일 요약의 [발행 전 기록] 줄 ──')
    print('\n'.join(V.digest_lines(v)))
    bad = V.anomalies(v)
    print('\n── 첫 실행(기준선)이라면 ──')
    print('알림을 보낸다 — 이상: ' + ', '.join(bad) if bad else
          '조용히 기준선으로 잡는다' + ('' if V.fully_verified(v) else '(검증 완료 아님 — 아침 요약에 보인다)'))
    print(f'\n기준: 기록 커밋 {(v.get("record_commit") or "-")[:10]} · 글 추가 커밋 '
          f'{", ".join(c[:10] for c in v.get("post_adds") or []) or "-"}')
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--github', action='store_true', help='Actions 한 회차: 계산 → 상태 브랜치 push → poke')
    ap.add_argument('--dry-run', action='store_true', help='outbox 에 실릴 문장만 출력(쓰기 없음)')
    ap.add_argument('--no-fetch', action='store_true')
    ap.add_argument('--preview', nargs=2, metavar=('MARKET', 'DATE'),
                    help='글 하나의 알림을 미리 본다 — 상태·기준점을 건드리지 않는다(시범용)')
    args = ap.parse_args(argv)
    root = repo_root()
    if args.preview:
        return preview(root, *args.preview, fetched=args.no_fetch or fetch(root))
    try:
        if args.dry_run:
            fetched = False
            if not args.no_fetch and fetch(root):
                try:
                    fetch_state(root)
                    fetched = True
                except Fatal as exc:
                    print(exc, file=sys.stderr)
            return dry_run(root, fetched)
        if args.github:
            return github(root)
    except Fatal as exc:
        print(f'실패: {exc}', file=sys.stderr)
        return 1
    print('--github(Actions) · --dry-run · --preview 중 하나를 준다. 맥에서 직접 보내는 길은 없다(2.5단계).', file=sys.stderr)
    return 2


if __name__ == '__main__':
    sys.exit(main())
