#!/usr/bin/env python3
"""일본어판 로컬 진입점.

    python3 scripts/runner_launch.py ja run        # launchd(30분마다) — origin/main 사본에서 이 파일의 `run`
    python3 scripts/ja_local.py run [--dry-run]    # tick 한 번(사람이 직접)
    python3 scripts/ja_local.py status [--root <레포>]   # 원장 요약: 발행·보류·대기·갱신 대기 문구, 보류 이유, 브레이크
    python3 scripts/ja_local.py retry <path>       # 같은 입력으로 다시 하지 않는 글을 다음 tick 에 다시
    python3 scripts/ja_local.py retry --auth       # `claude auth login` 뒤 — 로그인 만료 브레이크를 바로 푼다
    python3 scripts/ja_local.py build <path> --out <DIR> [--no-review] [--root <레포>]

`run`: 런처는 이 파일을 **git 이 아닌 사본**(그 tick 의 origin/main 을 푼 임시 폴더)에서, 작업 폴더를 사람 폴더
(`site/`)로 두고 부른다. 그래서 ① 설정은 이 사본의 `ja/config.json`(= origin/main)을 먼저 읽어 꺼져 있으면 clone 도
하지 않고 끝내고 ② 켜져 있으면 사람 폴더의 origin 주소로 임시 폴더에 새로 clone 한다(`contested_local.tick` 과 같다,
깊이 80). 사람 폴더는 `reviews/runner.json`(한글 쪽 한도 흔적)을 읽기만 한다. 로컬 상태는 `JA_CACHE_DIR`
(기본 `~/Library/Caches/fdo2a-ja`). SIGTERM 은 예외로 받아 임시 clone 을 지우고 143 으로 끝낸다.

레포 작업 트리의 한글 글 `<path>`(예: `japan/daily/2026-11-13.html`)를 일본어로 만들어
`<DIR>/ja/<path>`(ready 일 때만), `<DIR>/ja/_tm/<path>.json`(사이드카, 모든 결과),
`<DIR>/report.json`(status·reason·detail·tokens·rounds·calls·prefs·seconds)을 쓴다.
사이드카는 `<DIR>` 의 것을 먼저 읽고(다시 돌리면 이어진다), 없으면 레포의 `ja/_tm/` 것을 읽는다.
git 은 부르지 않고 레포 파일은 고치지 않는다.

종료 코드: 0 ready · 3 held · 4 pending · 1 예외 · 2 사용법.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.ja import pipeline, runner, state  # noqa: E402

EXIT = {"ready": 0, "held": 3, "pending": 4}
KST = timezone(timedelta(hours=9))
CACHE_ENV = runner.CACHE_ENV
CLONE_DEPTH = 80


def cache_dir() -> str:
    return runner.cache_dir_default()


class Interrupted(BaseException):
    """launchd·런처의 SIGTERM — 일반 예외 처리에 삼켜지지 않게(`contested_local.Interrupted` 와 같다)."""


def _git(cwd, *args, timeout=120):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}")
    return p.stdout.strip()


def _report(out: Path, obj: dict) -> None:
    state.write_json(out / "report.json", obj)


def cmd_build(argv) -> int:
    ap = argparse.ArgumentParser(prog="ja_local.py build")
    ap.add_argument("path")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-review", action="store_true")
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    if not runner.SCOPE.fullmatch(a.path):      # 러너와 같은 범위 — 주간·KR 은 일본어판에 없다
        print(f"[ja] {a.path}: 일본어판 범위 밖 — {', '.join(runner.SCOPE_DIRS)} 의 날짜 글만 만든다", file=sys.stderr)
        return 2
    root, out = Path(a.root), Path(a.out)
    side, why = state.load_sidecar(out, a.path)
    side_from = "out"
    if why is not None:
        side2, why2 = state.load_sidecar(root, a.path)
        side, side_from = (side2, "repo") if why2 is None else (side, None)
    cfg = pipeline.Config(review=not a.no_review)
    t0 = time.monotonic()
    base = {"path": a.path, "sidecar_from": side_from, "review": not a.no_review}
    try:
        res = pipeline.build_page(root, a.path, sidecar=side, translate=pipeline.real_translate(),
                                  review=pipeline.real_review(), cfg=cfg)
    except Exception as e:  # noqa: BLE001 — 어떤 실패든 보고서는 남긴다
        _report(out, {**base, "status": "error", "reason": f"{type(e).__name__}: {e}",
                      "traceback": traceback.format_exc(), "seconds": round(time.monotonic() - t0, 1)})
        print(f"[ja] {a.path}: error — {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    secs = round(time.monotonic() - t0, 1)
    if res.html_ja is not None:
        dst = out / "ja" / a.path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(res.html_ja, encoding="utf-8")
    state.save_sidecar(out, a.path, res.sidecar)
    _report(out, {**base, "status": res.status, "reason": res.reason, "detail": res.detail,
                  "tokens": res.tokens, "rounds": res.rounds, "calls": res.calls,
                  "prefs": res.detail.get("prefs", []), "seconds": secs})
    print(f"[ja] {a.path}: {res.status}" + (f" — {res.reason}" if res.reason else "")
          + f" (번역 {res.calls['translate']}회·검토 {res.calls['review']}회·판정 {res.calls.get('adjudicate', 0)}회, "
            f"토큰 {res.tokens['in']}/{res.tokens['out']}, {secs}초)")
    return EXIT.get(res.status, 1)


def cmd_run(argv) -> int:
    ap = argparse.ArgumentParser(prog="ja_local.py run")
    ap.add_argument("--dry-run", action="store_true", help="커밋·푸시하지 않는다")
    ap.add_argument("--code-root", default=str(ROOT), help=argparse.SUPPRESS)   # 시험용 — 설정을 먼저 읽는 자리
    a = ap.parse_args(argv)
    pre = runner.load_config(a.code_root)
    if not pre.enabled:
        print(f"[ja] 꺼짐 — {pre.why}")
        return 0
    root = _git(os.getcwd(), "rev-parse", "--show-toplevel")
    remote = _git(root, "remote", "get-url", "origin")

    def _term(*_):
        raise Interrupted()
    old = signal.signal(signal.SIGTERM, _term)
    now = datetime.now(KST)
    try:
        with tempfile.TemporaryDirectory(prefix="ja-runner-") as temp:
            clone = os.path.join(temp, "repo")
            _git(temp, "clone", "-q", "--no-local", "--single-branch", "--branch", "main", "--depth",
                 str(CLONE_DEPTH), remote, clone, timeout=300)
            rep = runner.tick(root, clone, now=now, cfg=runner.load_config(clone),
                              translate=pipeline.real_translate(), review=pipeline.real_review(),
                              cache_dir=cache_dir(), push=not a.dry_run)
    except Interrupted:
        print("[ja] SIGTERM — 정리하고 끝낸다", file=sys.stderr)
        return 143
    except Exception as e:  # noqa: BLE001 — launchd 로그에 남기고 다음 tick 에
        print(f"[ja] 실패 — {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, old)
    print(f"[ja {now:%m-%d %H:%M}] {rep.line()}")
    return 1 if rep.errors or rep.publish.startswith("error") else 0


def cmd_status(argv) -> int:
    ap = argparse.ArgumentParser(prog="ja_local.py status")
    ap.add_argument("--root", default=str(ROOT))
    a = ap.parse_args(argv)
    cfg = runner.load_config(a.root)
    ledger, why = state.load_ledger(a.root)
    last, _ = state.read_json(Path(cache_dir()) / "last.json")
    now = datetime.now(KST)
    print(f"설정: {'켜짐' if cfg.enabled else '꺼짐 — ' + cfg.why}, start={cfg.start}")
    if why:
        print(f"원장: {why}")
    for line in runner.summary(ledger, now, last if isinstance(last, dict) else None,
                               runner.Local(cache_dir()).get("attempts.json")):
        print(line)
    pages = ledger.get("pages") or {}
    for st in ("held", "pending", "notice"):
        for p, e in sorted(pages.items()):
            if isinstance(e, dict) and e.get("status") == st:
                print(f"  {st:8} {p}  {e.get('reason') or ''}  ({e.get('updated') or '-'})")
    loc = runner.Local(cache_dir())
    att = loc.get("attempts.json")
    for name in ("budget.json", "limit.json", "ko_limit.json", "ko_missing.json", "auth.json", "review_calls.json"):
        loc.get(name)
    if loc.bad:
        print(f"기록 파일이 깨졌다(모델 호출을 멈춘다): {', '.join(loc.bad)} — {cache_dir()} 에서 보고 고치거나 지운다")
    if att:
        print("시도 기록(같은 입력으로는 다시 하지 않는다 — retry <path> 로 지운다):")
        for p, r in sorted(att.items()):
            print(f"  {p}  {r.get('code')} ×{r.get('n')} ({r.get('day')})  {r.get('reason') or ''}")
    if isinstance(last, dict):
        print(f"마지막 tick: {last.get('at')}  브레이크={last.get('brakes')}  발행={last.get('publish') or '-'}")
    return 0


def cmd_retry(argv) -> int:
    ap = argparse.ArgumentParser(prog="ja_local.py retry")
    ap.add_argument("path", nargs="?")
    ap.add_argument("--auth", action="store_true", help="로그인 만료 브레이크를 푼다(`claude auth login` 뒤)")
    a = ap.parse_args(argv)
    if a.auth:
        done = runner.clear_auth(cache_dir())
        print("[ja] 로그인 만료 브레이크를 풀었다 — 다음 tick 이 다시 부른다" if done else "[ja] 걸린 로그인 만료 브레이크가 없다")
        if not a.path:
            return 0
    if not a.path:
        ap.error("path 또는 --auth")
    try:
        forgot = runner.forget_attempt(cache_dir(), a.path)
    except runner.CacheCorrupt as e:
        print(f"[ja] 시도 기록 파일이 깨졌다({e.name}) — {cache_dir()} 에서 직접 고치거나 지운다", file=sys.stderr)
        return 1
    if forgot:
        print(f"[ja] {a.path}: 시도 기록을 지웠다 — 다음 tick 에 다시 한다(브레이크는 그대로 지킨다)")
    else:
        print(f"[ja] {a.path}: 지울 시도 기록이 없다")
    return 0


COMMANDS = {"build": cmd_build, "run": cmd_run, "status": cmd_status, "retry": cmd_retry}


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if not argv or argv[0] not in COMMANDS:
        print(f"usage: ja_local.py {{{'|'.join(COMMANDS)}}} …", file=sys.stderr)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main())
