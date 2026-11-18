"""실패한 수집 잡에서 국채 16:00 원장만 따로 보존한다 — 다른 미커밋·스테이징 파일과 섞지 않는다."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ci" / "preserve_yields_ledger.sh"
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e",
           GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e", PUSH_RETRY_SLEEP="0")


def git(*a, cwd):
    return subprocess.run(["git", *a], cwd=cwd, env=ENV, check=True, capture_output=True, text=True)


def entry(src, v):
    return {"source": src, "target": "16:00",
            "tenors": {t: {"value": v, "stamp": "15:59"} for t in ("2Y", "5Y", "10Y", "30Y")}}


@pytest.fixture()
def world(tmp_path):
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "--bare", "-b", "main", str(origin)], check=True, capture_output=True)
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(origin), str(seed)], check=True, capture_output=True)
    (seed / "scripts" / "us").mkdir(parents=True)
    shutil.copy(ROOT / "scripts" / "us" / "yield_cut.py", seed / "scripts" / "us" / "yield_cut.py")
    (seed / "data").mkdir()
    (seed / "data" / "yields_1600.json").write_text(json.dumps({"2026-11-05": entry("naver", 4.4)}))
    git("add", "-A", cwd=seed)
    git("commit", "-m", "seed", cwd=seed)
    git("push", "-u", "origin", "main", cwd=seed)
    job = tmp_path / "job"
    subprocess.run(["git", "clone", str(origin), str(job)], check=True, capture_output=True)
    yield origin, seed, job
    shutil.rmtree(tmp_path, ignore_errors=True)


def run(job):
    return subprocess.run(["bash", str(SCRIPT), "data/yields_1600.json"], cwd=job, env=ENV,
                          capture_output=True, text=True)


def remote_ledger(origin):
    return json.loads(git("show", "main:data/yields_1600.json", cwd=origin).stdout)


def test_pushes_only_the_ledger_and_merges_with_remote(world):
    origin, seed, job = world
    # 다른 잡이 그 사이에 원격 원장을 바꿨다
    led = json.loads((seed / "data" / "yields_1600.json").read_text())
    led["2026-11-04"] = entry("naver", 4.3)
    (seed / "data" / "yields_1600.json").write_text(json.dumps(led))
    git("commit", "-am", "other run", cwd=seed)
    git("push", cwd=seed)
    # 실패한 잡: 원장 + 스테이징된 다른 산출물 + push 못 한 로컬 커밋
    ledger = {"2026-11-05": entry("cnbc", 9.9), "2026-11-06": entry("naver", 4.5)}
    (job / "data" / "yields_1600.json").write_text(json.dumps(ledger))
    (job / "junk.json").write_text("{}")
    git("add", "junk.json", cwd=job)
    r = run(job)
    assert r.returncode == 0, r.stderr
    got = remote_ledger(origin)
    assert set(got) == {"2026-11-04", "2026-11-05", "2026-11-06"}
    assert got["2026-11-05"]["source"] == "naver"          # 네이버 기록은 덮지 않는다
    files = git("ls-tree", "-r", "--name-only", "main", cwd=origin).stdout.split()
    assert "junk.json" not in files                         # 다른 산출물은 섞지 않는다


def test_nothing_to_do_when_remote_already_has_it(world):
    origin, _, job = world
    before = git("rev-parse", "main", cwd=origin).stdout
    r = run(job)                                            # 작업 트리의 원장 = 원격과 같다
    assert r.returncode == 0, r.stderr
    assert git("rev-parse", "main", cwd=origin).stdout == before


def test_first_run_without_a_remote_ledger(world):
    origin, seed, job = world
    git("rm", "-q", "data/yields_1600.json", cwd=seed)
    git("commit", "-m", "no ledger yet", cwd=seed)
    git("push", cwd=seed)
    (job / "data" / "yields_1600.json").write_text(json.dumps({"2026-11-06": entry("naver", 4.5)}))
    r = run(job)
    assert r.returncode == 0, r.stderr
    assert set(remote_ledger(origin)) == {"2026-11-06"}


def test_corrupt_local_ledger_fails_loudly(world):
    origin, _, job = world
    before = git("rev-parse", "main", cwd=origin).stdout
    (job / "data" / "yields_1600.json").write_text('{"2026-11-06": ')
    r = run(job)
    assert r.returncode != 0
    assert git("rev-parse", "main", cwd=origin).stdout == before
