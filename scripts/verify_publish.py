#!/usr/bin/env python3
"""발행 건별 텔레그램 알림 — launchd 5분 간격(`runner_launch.py publish`), 2026-11-08.

    python3 scripts/verify_publish.py              # 한 회차: fetch → 사건 계산 → 저장 → 전송
    python3 scripts/verify_publish.py --dry-run    # 보낼 문장만 출력(저장·전송 없음)

US·KR 일간이 올라오면 그 발행의 발행 전 기록을 읽어, 맥이 직접 확인한 짝과 루틴이 남긴 검사 결과를 나눠 보낸다.
거래 세션의 기준 시각까지 글이 없으면 미발행을, 그 뒤 올라오면 해소를 보낸다. 매일 요약과 상태 파일이 따로다.
5분은 맥이 깨어 있고 네트워크가 될 때의 목표이지 보장이 아니다.
설계: docs/superpowers/specs/2026-11-08-telegram-prepub-records.md
"""
import argparse
import fcntl
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from review import digest as D  # noqa: E402
from review import publish_watch as W  # noqa: E402


def repo_root():
    out = subprocess.run(['git', 'rev-parse', '--show-toplevel'], capture_output=True, text=True)
    if out.returncode:
        sys.exit('git 레포 안에서 실행해야 한다.')
    return out.stdout.strip()


def fetch(root):
    try:
        out = subprocess.run(['git', '-C', root, 'fetch', '--quiet', 'origin', 'main'], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-fetch', action='store_true')
    args = ap.parse_args(argv)
    now = D.now_kst()
    path = W.state_path()
    root = repo_root()

    lock = None
    if not args.dry_run:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        lock = open(path + '.lock', 'w')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close()
            print('다른 발행 알림 실행이 돌고 있다 — 이번 회차는 건너뛴다')
            return 0
    try:
        try:
            st = W.load_state(path)
            if st is None:
                st = W.new_state('처음 실행했어요', baseline=True)
        except W.StateError as exc:
            print(f'상태 파일 손상: {exc}', file=sys.stderr)
            if not args.dry_run:
                # 옮기지 않고 복사한다 — 새 상태 저장이 실패하면 손상 파일이 그대로 남아 다음 회차가 다시 복구에 들어간다
                # (옮겼다가 저장이 실패하면 「처음 실행」으로 보여 복구 안내가 사라진다 — codex 구현 검토 #9). 백업은 덮어쓰지 않는다.
                shutil.copy2(path, f'{path}.corrupt-{now:%Y%m%d%H%M%S}-{os.getpid()}')
            st = W.new_state('상태 파일이 손상돼 복사해 두고 새로 시작했어요')
        fetched = True if args.no_fetch else fetch(root)
        W.step(st, root, now, fetched)
        if args.dry_run:
            for e in W.pending(st):
                print(f'{e["text"]}\n#{e["id"]}\n')
            return 0
        W.save_state(path, st)      # 사건을 먼저 남긴다 — 여기서 실패하면 보내지 않고, 다음 회차가 같은 사건을 다시 만든다
        ok = W.deliver(st, D.send_telegram, lambda s: W.save_state(path, s), now)
        print(f'발행 알림 — 보냄 대기 {len(W.pending(st))}건, 기준점 {(st.get("last_seen") or "-")[:7]}')
        return 0 if ok else 1
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    sys.exit(main())
