#!/usr/bin/env python3
"""매일 검증 알림 — 발행본마다 숫자 재검사·codex 검토 상태를 텔레그램 한 통으로 (2026-11-08).

  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/runner_launch.py digest
                                                   # launchd(매시) — origin/main 사본. 3.9 는 런처가 못 푼다
  python3 scripts/verify_digest.py --dry-run       # 보내지 않고 출력만(기록도 안 남긴다)
  python3 scripts/verify_digest.py --force         # 오늘 보냈어도 다시 보낸다
  python3 scripts/verify_digest.py --setup-chat    # 봇에게 메시지를 보낸 뒤 한 번
  python3 scripts/verify_digest.py --status        # 세션 시작 훅 한 줄(멈춘 알림 표시)

매시 깨어나도 KST 9시 이후 그날 처음 한 번만 보낸다 — launchd 시각이 Mac 시간대를 따르고, 잠자기
중엔 깨어날 때 돌기 때문이다. 발행본·발행 루틴은 건드리지 않고, AI 를 부르지 않는다.
로직 `scripts/review/digest.py`.
"""
import argparse
import fcntl
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from review import digest as D  # noqa: E402

CHECKER = os.path.join(HERE, 'check_numbers.py')
# 숫자 재검사 결과를 바꾸는 파일 — 캐시 키. 검사기가 부르는 묶음(us·fund·common)까지 통째로 —
# 그 밖의 커밋(발행·문서)으로는 캐시를 버리지 않는다.
def _checker_files():
    out = [CHECKER, os.path.join(os.path.dirname(HERE), 'config', 'number_audit.json'),
           os.path.join(HERE, 'review', 'digest.py')]
    for pkg in ('us', 'fund', 'common'):
        for dirpath, dirs, files in os.walk(os.path.join(HERE, pkg)):
            dirs[:] = [d for d in dirs if d not in ('tests', '__pycache__')]
            out += [os.path.join(dirpath, f) for f in files if f.endswith('.py')]
    return out


def _published_view(G, root, want_fetch):
    """공개판만 분류한다 — 독자가 보는 판. 작업 폴더의 편집 중인 글은 섞지 않는다."""
    published, _work, _basis, stale, blobs = G.trees(root, want_fetch)
    ledger = G.load_ledger(root)
    blobs.prefetch(G._needed_shas(ledger, (published,)))
    c = G.classify(ledger, published, blobs.equivalent)
    queue, expired = G._split_expired(root, c.todo + c.unavailable, published)
    buckets = {p.path: 'typography' for p in c.typography}
    unavailable = {p.path for p in c.unavailable}
    for p in queue:
        buckets[p.path] = 'unavailable' if p.path in unavailable else 'pending'
    for p in expired:
        buckets[p.path] = 'expired'
    reviewed = ledger.get('reviewed', {}) if isinstance(ledger, dict) else {}
    drafts = set()
    try:
        from review.runner import draft_name
        have = set(os.listdir(os.path.join(root, G.DRAFTS)))
        drafts = {p.path for p in queue if draft_name(p) in have}
    except OSError:
        pass
    return published, buckets, reviewed, stale, drafts


def build(state, now, args, notes):
    import review_gate as G
    root = G.repo_root()
    published, buckets, reviewed, stale, drafts = _published_view(G, root, not args.no_fetch)
    if stale:
        notes.append('최신 판을 못 받았어요 — 마지막으로 받아 둔 판 기준이에요')
    code_id = D.checker_version(_checker_files(), base=os.path.dirname(HERE))
    cache = state.get('numbers') if isinstance(state.get('numbers'), dict) else {}
    numbers, posts = {}, []
    today = now.date()
    for path, sha, _day in D.kept_posts(published, today):
        st, findings = D.review_state(path, sha, reviewed, buckets)
        number = None
        if D.needs_replay(path) and not args.no_replay:
            hit = cache.get(path) or {}
            if hit.get('sha') == sha and hit.get('code') == code_id and hit.get('result'):
                number = hit['result']
            else:
                number = D.replay_numbers(root, path, sha, CHECKER)
                number['checker'] = code_id[:8]
            if number.get('kind') != 'error':       # 일시 오류는 기억하지 않는다 — 다음에 다시
                numbers[path] = {'sha': sha, 'code': code_id, 'result': number}
        posts.append({'path': path, 'sha': sha, 'state': st, 'findings': findings,
                      'number': number, 'auto': D.auto_reviewed(path), 'draft': path in drafts})
    return posts, numbers, dict(published)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-fetch', action='store_true')
    ap.add_argument('--no-replay', action='store_true', help='숫자 재검사를 건너뛴다(시험용)')
    ap.add_argument('--setup-chat', action='store_true')
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args(argv)
    path = D.state_path()
    now = D.now_kst()

    if args.status:
        note = D.digest_note(path, now)
        if note:
            print(note)
        return 0
    if args.setup_chat:
        try:
            D.setup_chat()
        except D.SendError as exc:
            print(exc, file=sys.stderr)
            return 1
        print('대화 번호를 열쇠고리에 넣었어요.')
        return 0

    notes = []
    lock = None
    if not args.dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path + '.lock', 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            print('다른 알림 실행이 돌고 있다 — 이번 tick 은 건너뛴다')
            return 0
        except OSError as exc:      # 경합이 아닌 잠금 실패는 실패다 — 세션 훅이 보게 기록한다(codex 재검토 #3)
            lock.close()
            why = f'잠금 — {type(exc).__name__}: {exc}'[:200]
            print(f'알림 실패: {why}', file=sys.stderr)
            try:
                st = D.load_state(path)
                st.update(last_error=why, last_attempt=now.isoformat())
                D.save_state(path, st)
            except (D.StateError, OSError):
                pass
            return 1
    try:
        try:
            state = D.load_state(path)
        except D.StateError as exc:
            notes.append('기록 파일이 손상돼 새로 시작했어요 — 지난 상태와 비교하지 못했어요')
            if not args.dry_run:
                os.replace(path, f'{path}.corrupt-{now:%Y%m%d%H%M}')
            print(f'기록 파일 손상: {exc}', file=sys.stderr)
            state = {}
        if not (args.dry_run or args.force) and not D.due(now, state):
            return 0
        if not state.get('last_sent'):
            notes.append(f'첫 알림이라 최근 {D.WINDOW_DAYS}일 글과 끝나지 않은 옛 글을 담았어요')
        if state.get('last_error'):
            notes.append(f'지난번 알림이 실패했어요 — {state["last_error"]}')
        try:
            posts, numbers, published = build(state, now, args, notes)
            lines, more, tracked = D.reconcile(posts, state, published, now.date())
            text, lines = D.render(posts, lines, now, notes + more)
            if args.dry_run:
                print(text)
                return 0
            D.send_telegram(text)
        except Exception as exc:  # noqa: BLE001 — 어떤 실패든 기록해야 세션 훅이 보인다(codex 구현 검토 #4)
            why = str(exc) if isinstance(exc, D.SendError) else f'{type(exc).__name__}: {exc}'[:200]
            print(f'알림 실패: {why}', file=sys.stderr)
            if not args.dry_run:
                state.update(last_error=why, last_attempt=now.isoformat())
                D.save_state(path, state)
            return 1
        # 전송 뒤 저장이 실패하면 다음 tick 에 한 번 더 보낸다 — 중복은 유실보다 낫다.
        state.update(last_sent=now.isoformat(), last_sent_day=now.date().isoformat(),
                     last_attempt=now.isoformat(), last_error=None, lines=lines, numbers=numbers,
                     open=sorted(p['path'] for p in posts if not D.resolved(p)), tracked=tracked,
                     all=sorted(p for p in published if D.post_day(p)))
        state.pop('seen', None)
        D.save_state(path, state)
        print(f'보냈다 — 글 {len(posts)}편, {len(text)}자')
        return 0
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    sys.exit(main())
