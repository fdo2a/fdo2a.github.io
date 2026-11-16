"""일본어판 발행 — `ja/**` 만 커밋하고 `git push origin HEAD:main`.

`scripts/ci/push_with_retry.sh` 는 쓰지 않는다: 그 스크립트는 커밋 뒤 `pull --rebase` 하고 그대로 밀어서,
그 사이 정정된 한글판 위에 정정 전 원본으로 만든 일본어판이 올라간다(codex 설계 검토 #9).

순서(`contested_local.push` 와 같은 꼴):
1. `git add -A -f -- ja` — 지운 파일까지. 레포 `.gitignore` 의 `/news/` 는 루트에만 걸리지만, 앞으로 생길 규칙에
   일본어 파일이 조용히 빠지지 않게 `-f`.
2. **인덱스**에 오른 경로가 전부 `ja/` 로 시작하는지 본다 — 하나라도 아니면 커밋하지 않고 `OutsideJa`.
   (넘긴 목록이 아니라 인덱스를 본다: 누가 미리 올려 둔 한글 파일도 잡는다.)
0. 커밋 전에 HEAD 에 origin/main 에 없는 커밋이 없는지 본다 — 있으면 `GitError`. 앞선 로컬 커밋(한글 파일을 고친 것일
   수 있다)이 `HEAD:main` 푸시에 딸려 가지 않게.
3. 확인한 HEAD 위에 커밋 → 푸시. 거절되면 fetch 하고
   - 그 사이 일본어판 코드(`CODE_PATHS` — 일본어판이 불러 쓰는 공유 코드 포함)가 바뀌었으면 포기 — 옛 코드로 만든
     결과를 밀지 않는다.
   - 한글 목록 다섯(`LIST_FILES`) 가운데 하나라도 바뀌었으면 포기 — 일본어 목록은 다섯 파일을 통째로 다시 만들므로,
     이번 커밋에 들지 않은 글의 항목(삭제·제목 정정)도 낡는다. rebase 하지 않는다.
   - 이 커밋에 든 글마다 원본과 의존 파일을 origin/main 에서 다시 잰다(`expect`). 하나라도 다르면 **커밋 전체를
     포기**한다 — 그 글만 빼려면 원장·목록까지 되돌려야 해서다. 러너는 번역을 `cache_dir` 에 남겨 두므로 다음
     tick 이 모델 호출 없이 다시 만든다.
   - 같으면 rebase 뒤 다시 푸시(모두 `tries` 번까지).

`expect = {글 경로: {열쇠: 값}}`. 열쇠가 경로면 값은 그 경로의 blob(없으면 "" — 그때 없던 후보도 ""로 넣어 새로
생기면 다르다고 본다), `list:<목록 json>` 이면 그 글 항목의 해시(`item_hash`).
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import PurePosixPath

# 일본어판 코드 + 그것이 불러 쓰는 공유 코드(`test_code_paths_cover_shared_code_the_edition_loads` 가 import 를 따라가 본다)
# 결과 글에 닿지 않는 신호용 모듈(`review.publish_watch` 와 그 import — 브레이크만 정한다)은 넣지 않는다.
CODE_PATHS = ("scripts/ja", "scripts/ja_local.py", "ja/config.json",
              "scripts/collect_market_data.py", "scripts/us/__init__.py", "scripts/us/close_cut.py",
              "scripts/common/__init__.py", "scripts/common/analytics.py",
              "scripts/review/__init__.py", "scripts/review/runner.py", "scripts/review/queue.py",
              "scripts/review/kinds.py")
LIST_FILES = ("posts.json", "news.json", "weekly.json", "japan/daily.json", "japan/posts.json")
LIST_PREFIX = "list:"


class OutsideJa(RuntimeError):
    """`ja/` 밖 경로가 인덱스에 있다 — 한글 파일 무접촉 계약."""


class GitError(RuntimeError):
    pass


def _git(cwd, *args, check=True, timeout=120):
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if check and p.returncode:
        raise GitError(f"git {args[0]} 실패: {(p.stderr or p.stdout).strip()[-300:]}")
    return p


def item_hash(rows, stem: str) -> str:
    """목록(json 배열)에서 `date` 또는 `key` 가 stem 인 항목의 해시. 없으면 ""."""
    if not isinstance(rows, list):
        return ""
    for it in rows:
        if isinstance(it, dict) and stem in (it.get("date"), it.get("key")):
            raw = json.dumps(it, ensure_ascii=False, sort_keys=True)
            return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
    return ""


def current(clone, ref: str, page: str, key: str) -> str:
    """`ref` 트리에서 잰 값 — `expect` 와 같은 꼴."""
    if key.startswith(LIST_PREFIX):
        rel = key[len(LIST_PREFIX):]
        p = _git(clone, "show", f"{ref}:{rel}", check=False)
        if p.returncode:
            return ""
        try:
            rows = json.loads(p.stdout)
        except ValueError:
            return ""
        return item_hash(rows, PurePosixPath(page).stem)
    p = _git(clone, "rev-parse", "--verify", "--quiet", f"{ref}:{key}", check=False)
    return p.stdout.strip() if p.returncode == 0 else ""


def staged(clone) -> list:
    p = _git(clone, "diff", "--cached", "--name-only", "--no-renames", "-z")
    return [x for x in p.stdout.split("\0") if x]


def changed_pages(clone, ref, expect) -> list:
    out = []
    for page, deps in sorted((expect or {}).items()):
        for key, want in sorted(deps.items()):
            if current(clone, ref, page, key) != (want or ""):
                out.append(page)
                break
    return out


def push(clone, *, message: str, expect: dict, tries: int = 3, code_paths=CODE_PATHS,
         list_files=LIST_FILES) -> str:
    """'pushed' · 'nothing' · 'abandoned: 이유'. `ja/` 밖이 인덱스에 있으면 OutsideJa(커밋 없음).
    HEAD 에 origin/main 에 없는 커밋이 있으면 GitError(스테이징도 하지 않는다)."""
    # 확인한 기준 위인가 — origin/main 에 없는 로컬 커밋이 하나라도 있으면 `HEAD:main` 에 딸려 간다. origin/main 이
    # 앞서 간 것(그림용 fetch 가 옮겼다)은 괜찮다: 커밋 → 거절 → 재확인 → rebase 길로 간다.
    ahead = _git(clone, "rev-list", "--count", "origin/main..HEAD", check=False)
    if ahead.returncode or ahead.stdout.strip() != "0":
        raise GitError(f"HEAD 에 origin/main 에 없는 커밋이 있다({ahead.stdout.strip() or '확인 실패'}) — 올리지 않는다")
    _git(clone, "add", "-A", "-f", "--", "ja")
    names = staged(clone)
    outside = [n for n in names if not n.startswith("ja/")]
    if outside:
        raise OutsideJa(f"ja/ 밖 경로가 스테이징됐다: {outside[:5]}")
    if not names:
        return "nothing"
    base = _git(clone, "rev-parse", "HEAD").stdout.strip()
    _git(clone, "commit", "-q", "-m", message)
    for attempt in range(tries):
        if _git(clone, "push", "-q", "origin", "HEAD:main", check=False, timeout=300).returncode == 0:
            return "pushed"
        if attempt + 1 >= tries:
            break
        if _git(clone, "fetch", "-q", "origin", "main", check=False, timeout=300).returncode:
            return "abandoned: fetch 실패"
        remote = _git(clone, "rev-parse", "origin/main").stdout.strip()
        moved = _git(clone, "diff", "--name-only", base, remote, "--", *code_paths, check=False).stdout.strip()
        if moved:
            return "abandoned: 일본어판 코드가 그 사이 바뀌었다"
        lst = _git(clone, "diff", "--name-only", base, remote, "--", *list_files, check=False).stdout.split()
        if lst:
            return f"abandoned: 한글 목록이 그 사이 바뀌었다({', '.join(lst[:3])})"
        bad = changed_pages(clone, remote, expect)
        if bad:
            return f"abandoned: 원본이 그 사이 바뀌었다({', '.join(bad[:3])})"
        if _git(clone, "rebase", "-q", remote, check=False).returncode:
            _git(clone, "rebase", "--abort", check=False)
            return "abandoned: rebase 충돌"
        base = remote
    return f"abandoned: push 거절 {tries}회"
