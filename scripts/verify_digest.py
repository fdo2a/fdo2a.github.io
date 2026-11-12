#!/usr/bin/env python3
"""매일 검증 알림 — 발행본마다 숫자 재검사·codex 검토 상태를 하루 한 통으로 (2026-11-08, 2.5단계 2026-11-10).

  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 scripts/runner_launch.py digest
                                                   # launchd(매시) — origin/main 사본. 3.9 는 런처가 못 푼다
  python3 scripts/verify_digest.py --dry-run       # 제출하지 않고 출력만(기록·열쇠고리·Worker 를 안 건드린다)
  python3 scripts/verify_digest.py --force         # 오늘 접수됐어도 수정본(v2…)으로 다시 제출
  python3 scripts/verify_digest.py --status        # 세션 시작 훅(멈춘 알림 + Worker 공개 /health 의 설정 오류, 키 없이 5초)

맥은 텔레그램에 직접 보내지 않는다. 요약을 Cloudflare Worker 에 제출하고(`POST /digest`) Worker 가 보낸다.
맥이 읽는 값은 둘뿐이고 사람이 직접 넣는다(값을 파일·명령 인자에 적지 않는다 — `-w` 뒤를 비우면 물어본다):

  security add-generic-password -U -s fdo2a-alerts -a digest_key -w     # 제출 키(Worker 의 DIGEST_SUBMIT_KEY)
  security add-generic-password -U -s fdo2a-alerts -a worker_url -w     # https://<worker 주소> (경로 없이)

매시 깨어나 (1) 접수된 요약이 실제로 전송됐는지 Worker `/status` 로 확인하고 (2) 접수 안 된 제출본을 같은
본문으로 다시 내고 (3) KST 9시 이후 그날 치가 아직 접수되지 않았으면 새 요약을 만들어 제출한다.
「무엇을 이미 알렸나」는 전송이 확인된 뒤에만 전진한다. 발행본·발행 루틴은 건드리지 않고, AI 를 부르지 않는다.
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


def _prepub_target(path):
    """2단계 모듈을 못 불러와도 매일 요약은 나간다(codex 재검토) — 그때는 대상 글을 「읽지 못함」으로."""
    try:
        from review import prepub_view as V
    except Exception:  # noqa: BLE001
        import re
        m = re.match(r'^(?:posts|kr/posts)/(\d{4}-\d{2}-\d{2})\.html$', path)
        return None if not m or m.group(1) < '2026-11-09' else ('?', m.group(1))
    return V.target_of(path)


def _prepub(root, target):
    """발행 전 기록 한 건. 실패는 **그 자리에서 고정 코드로** 바꾼다(module·read·other) — 예외 문장은 이 맥의 stderr 에만.
    기록을 못 읽어도 매일 요약은 나가야 한다(codex 구현 검토 #6)."""
    try:
        from review import prepub_view as V
    except Exception as exc:  # noqa: BLE001
        print(f'발행 전 기록 모듈을 못 불러왔다: {type(exc).__name__}: {exc}'[:300], file=sys.stderr)
        return {'error': 'module'}
    try:
        return V.view(root, 'origin/main', *target)
    except Exception as exc:  # noqa: BLE001
        # GitError = git 실행 실패·시간 초과·기록 파일 읽기 실패가 모두 이 클래스로 온다
        code = 'read' if isinstance(exc, V.GitError) else 'other'
        print(f'발행 전 기록을 못 읽었다({code}): {type(exc).__name__}: {exc}'[:300], file=sys.stderr)
        return {'error': code}


# build 가 이번 판에 낸 KR 검사 줄의 (키, 줄) — _text 가 비우고 읽는다. build 의 호출 모양을 바꾸지 않으려고
# 모듈 변수로 둔다(시험이 build 를 네 인자 람다로 바꿔 끼운다).
KR_KEYS = []


def build(state, now, args, notes):
    import review_gate as G
    root = G.repo_root()
    published, buckets, reviewed, stale, drafts = _published_view(G, root, not args.no_fetch)
    if stale:
        notes.append(D.NOTE_STALE)
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
        post = {'path': path, 'sha': sha, 'state': st, 'findings': findings,
                'number': number, 'auto': D.auto_reviewed(path), 'draft': path in drafts}
        target = _prepub_target(path)
        if target:                       # 발행 전 기록(2단계) — 대상 글에만 키를 둔다
            post['prepub'] = _prepub(root, target)
        posts.append(post)
    # KR 주간 지수 누락 — 자동 보완하지 않으므로 사람에게 알린다(2026-11-10). 실패해도 알림은 계속
    try:
        notes.extend(D.kr_index_gap_notes(D.kr_weekly_aggs(root)))
    except Exception as exc:  # noqa: BLE001
        print(f'KR 주간 지수 누락 확인 실패: {exc}', file=sys.stderr)
    # KR 수집 검사 기록(실행 manifest 의 checks, 최근 3거래일) — 경고까지 전부 다음 날 아침에(2026-11-12).
    # 이미 알린 (거래일, 항목, status) 는 빼고, 키는 접수가 확인된 뒤에만 기억한다(mark_accepted)
    try:
        lines, keys = D.kr_check_notes(root, seen=state.get('kr_checks_seen'))
        notes.extend(lines)
        KR_KEYS.extend(keys)
    except Exception as exc:  # noqa: BLE001 — 읽기 실패는 조용히 넘기지 않는다
        print(f'KR 수집 검사 기록 확인 실패: {exc}', file=sys.stderr)
        notes.append(D.KR_CHECK_UNREAD)
    return posts, numbers, dict(published)


def _fail(path, state, kind, detail='', why=None):
    """실패는 종류와 이유 코드만 기록한다 — 자세한 문장은 이 맥의 stderr(launchd 로그)에만."""
    print(f'알림 실패: {kind}' + (f' — {detail}' if detail else ''), file=sys.stderr)
    D.set_error(state, kind, why)
    state['last_attempt'] = D.now_kst().isoformat()
    D.save_state(path, state)
    return 1


def _log_trimmed(sid, lines):
    """요약에서 줄이거나 뺀 줄의 원문을 맥 로그(stderr)에 남긴다 — 쓰기만 하고 다시 읽지 않는다.
    「되면 좋은」 일이다: 찍다 실패해도 요약은 그대로 만들어 제출한다."""
    try:
        if not lines:
            return
        for line in [f'줄인 안내 원문 — {sid}'] + list(lines):
            sys.stderr.write(str(line).encode('utf-8', 'backslashreplace').decode('utf-8') + '\n')
        sys.stderr.flush()
    except Exception:  # noqa: BLE001
        pass


def _text(state, now, args, notes, health_tail, v=1):
    """(제출본, 글 수). 상태를 바꾸지 않는다."""
    import review_gate as G
    notes = list(notes) + D.carry_notes(state)
    if not state.get('last_sent'):
        notes.append(D.NOTE_FIRST)
    if state.get('last_error'):
        notes.append(D.ERROR_NOTE + D.error_text(state))
    del KR_KEYS[:]
    posts, numbers, published = build(state, now, args, notes)
    lines, more, tracked = D.reconcile(posts, state, published, now.date())
    trimmed = []
    # 접수 결과·전송기 줄은 꼭 싣는 줄이다. 발행 알림 꼬리는 publish_tail 이 줄마다 붙인 표시를 그대로 넘긴다
    tail = [D.Must(x) for x in D.carry_lines(state, now.date(), trimmed)] \
        + list(D.publish_tail(G.repo_root(), now, fetch=not args.no_fetch)) + [D.Must(x) for x in health_tail]
    pending = D.compose(posts, lines, now, notes + more, tail, numbers, tracked, published, v, trimmed=trimmed)
    pending['kr_checks'] = D.surviving_kr_keys(KR_KEYS, pending['text'])     # 실린 줄만 — 빠진 줄은 다음에 다시
    _log_trimmed(pending['id'], trimmed)
    return pending, len(posts)


def _tick(path, state, now, args, notes):
    def save(st):
        D.save_state(path, st)

    def lookup(sid):
        try:
            return D.fetch_status(sid)['events'].get(sid)
        except D.AuthError:
            D.auth_failed(state, now)
            raise

    def archive(p, outcome):         # 접수되지 못한 제출본은 지우지 않는다 — 기록 파일 옆에 30일
        entry = {'archived_at': now.isoformat(), 'outcome': outcome, 'pending': p}
        try:
            D.append_archive(path, [entry], now)
        except OSError as exc:
            # 보관에 실패하면 원문을 기록 파일 안에 남긴다 — pending 을 지운 뒤에도 원문이 사라지지 않게(codex 구현 2회 #2)
            state.setdefault('unarchived', []).append(entry)
            print(f'접수 안 된 제출본을 보관하지 못했다 — 기록 파일에 남겼다({type(exc).__name__}: {exc})',
                  file=sys.stderr)

    today = now.date()
    before = repr(sorted(state.items(), key=lambda kv: kv[0]))
    if state.get('unarchived'):      # 지난번에 못 옮긴 원문 — 다시 보관. 스냅숏 뒤라 성공하면 저장된다(codex 3회 #2)
        try:
            D.append_archive(path, state['unarchived'], now)
            state.pop('unarchived')
        except OSError as exc:
            print(f'남겨 둔 제출본 보관 재시도 실패 — {type(exc).__name__}: {exc}', file=sys.stderr)

    want = args.force or D.due(now, state)
    status = None
    unread = (None, None)                        # 전송기 상태를 못 읽은 이유(코드, HTTP 코드) — 요약의 전송기 줄에만 쓴다
    if want or D.pending_of(state) or D.unconfirmed(state):
        try:
            status = D.fetch_status()
        except D.ConfigError as exc:
            return _fail(path, state, '제출 키 없음', str(exc), why=D.config_why(exc))
        except D.AuthError:
            D.auth_failed(state, now)            # 키가 Worker 와 다르다 — 세션 훅·다음 요약 머리에 보인다
            status, unread = None, ('auth', None)
        except D.TransportError as exc:
            status = None                        # 확인은 다음 tick 에. 제출은 그대로 해 본다
            unread = (getattr(exc, 'why', None), getattr(exc, 'status', None))
        if status:
            D.auth_ok(state)
            D.confirm(state, status['events'], now)
            if status['health'] is None:         # 사건 목록은 정상 — 사건 확인은 위에서 그대로 했다
                unread = ('health', None)

    p = D.pending_of(state)
    if p:
        day = D.date.fromisoformat(p['date'])
        age = (today - day).days
        # 기한: 어제 치는 오늘 요약을 만들 때(9시 이후 첫 tick)까지 다시 낸다. 그보다 오래된 날짜는 Worker 가 안 받는다.
        expired = age > 1 or (age == 1 and (now.hour >= D.SEND_HOUR or args.force))
        known = status is not None and p['id'] in status['events']
        if expired:
            D.settle(state, now, (lambda sid: status['events'][sid]) if known else lookup, True, archive)
        # 기한 전에는 /status 에 id 가 보여도 같은 본문을 다시 낸다 — 200 이면 내 본문, 409 면 남의 본문이다.
        # 상태만 믿으면 (기록을 잃고 새로 만든 본문 + 무응답) 때 가지 않은 본문의 기준이 적용된다.
        elif D.attempt(state, now, save, D.post_digest) == 'conflict':
            D.settle(state, now, lookup, False, archive)
        save(state)
        if D.pending_of(state):                  # 아직 접수 안 됨 — 다음 tick 에 같은 본문으로
            print(f'알림 실패: {state.get("last_error")}', file=sys.stderr)
            return 1
        want = D.due(now, state)                 # 밀린 제출본을 정리한 tick 에는 --force 로 새 판을 만들지 않는다

    if not want:
        if repr(sorted(state.items(), key=lambda kv: kv[0])) != before:
            save(state)
        return 0

    v = 1
    last = state.get('submitted') if isinstance(state.get('submitted'), dict) else {}
    if last.get('date') == today.isoformat():    # --force 로 같은 날 다시 — 같은 id 에 다른 본문은 409 다
        v = int(last.get('v') or 1) + 1
        if v > 9:
            return _fail(path, state, '요약 만들기 오류', '오늘 수정본을 9개까지 냈다', why='max_versions')
    try:
        health = D.health_lines(status['health'] if status else None, now, why=unread[0], status=unread[1])
        pending, count = _text(state, now, args, notes, health, v)
    except D.SizeError as exc:
        return _fail(path, state, '크기 초과', str(exc), why='size')
    except Exception as exc:  # noqa: BLE001 — 어떤 실패든 기록해야 세션 훅이 보인다(codex 구현 검토 #4)
        return _fail(path, state, '요약 만들기 오류', f'{type(exc).__name__}: {exc}'[:300], why='exception')
    state['pending'] = pending                   # 제출본을 먼저 고정한다(설계 v7 #1) — attempt 가 보내기 전에 저장
    state['carry'] = []
    result = D.attempt(state, now, save, D.post_digest)
    if result == 'conflict':
        D.settle(state, now, lookup, False, archive)
        save(state)
    if D.pending_of(state):
        print(f'알림 실패: {state.get("last_error")} — 다음 tick 에 같은 본문으로 다시 낸다', file=sys.stderr)
        return 1
    print(f'접수됐다 — 글 {count}편, {len(pending["text"])}자 ({pending["id"]}, {result})')
    return 0


def _lock_failed(path, now, why):
    """잠금 실패를 세션 훅이 보게 적는다. 잠금 없이 쓰는 자리라 migrate 를 부르지 않고, 못 쓰면 조용히 넘어간다
    (폴더를 못 만든 경우는 저장도 실패한다 — stderr 에만 남는다)."""
    try:
        st = D.load_state(path)
        D.set_error(st, '잠금 오류', why)
        st['last_attempt'] = now.isoformat()
        D.save_state(path, st)
    except (D.StateError, OSError):
        pass


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--no-fetch', action='store_true')
    ap.add_argument('--no-replay', action='store_true', help='숫자 재검사를 건너뛴다(시험용)')
    ap.add_argument('--status', action='store_true')
    args = ap.parse_args(argv)
    path = D.state_path()
    now = D.now_kst()

    if args.status:
        note = D.digest_note(path, now)
        if note:
            print(note)
        try:                 # 전송기 설정 오류는 텔레그램으로 알릴 수 없다 — 공개 /health 를 여기서 본다(키 없이, 5초)
            worker = D.worker_note(path)
        except Exception:  # noqa: BLE001 — 훅 한 줄 때문에 세션 시작이 깨지면 안 된다
            worker = ''
        if worker:
            print(worker)
        return 0

    notes = []
    lock = None
    if not args.dry_run:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            lock = open(path + '.lock', 'w')
        except OSError as exc:      # 폴더·잠금 파일을 못 열었다 — 예전에는 기록 없이 죽었다
            print(f'알림 실패: 잠금 파일 — {type(exc).__name__}: {exc}'[:200], file=sys.stderr)
            _lock_failed(path, now, 'lock_open')
            return 1
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            print('다른 알림 실행이 돌고 있다 — 이번 tick 은 건너뛴다')
            return 0
        except OSError as exc:      # 경합이 아닌 잠금 실패는 실패다 — 세션 훅이 보게 기록한다(codex 재검토 #3)
            lock.close()
            print(f'알림 실패: 잠금 — {type(exc).__name__}: {exc}'[:200], file=sys.stderr)
            _lock_failed(path, now, 'lock_set')
            return 1
    try:
        try:
            state = D.load_state(path)
        except D.StateError as exc:
            notes.append(D.NOTE_CORRUPT)
            if not args.dry_run:
                os.replace(path, f'{path}.corrupt-{now:%Y%m%d%H%M}')
            print(f'기록 파일 손상: {exc}', file=sys.stderr)
            state = {}
        D.migrate(state)
        if args.dry_run:                         # 열쇠고리·Worker 를 건드리지 않는다 — 전송기 줄은 없다
            pending, _count = _text(state, now, args, notes, [])
            print(pending['text'])
            return 0
        try:
            return _tick(path, state, now, args, notes)
        except D.ConfigError as exc:
            return _fail(path, state, '제출 키 없음', str(exc), why=D.config_why(exc))
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    sys.exit(main())
