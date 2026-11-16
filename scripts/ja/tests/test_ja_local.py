"""ja_local build — 파일 쓰기·보고서·사이드카 이어 읽기. 모델은 가짜."""
import json
import subprocess

import pytest

from scripts import ja_local as L
from scripts.ja import pipeline as P
from scripts.ja.tests.test_pipeline import FR, FT, PATH, make_root, no_call


@pytest.fixture
def fakes(monkeypatch):
    box = {"ft": FT(), "fr": FR()}
    monkeypatch.setattr(P, "real_translate", lambda: box["ft"])
    monkeypatch.setattr(P, "real_review", lambda: box["fr"])
    return box


def snapshot(root):
    return {p.relative_to(root): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_build_writes_outputs_and_leaves_repo_alone(tmp_path, fakes):
    root = make_root(tmp_path / "repo")
    before = snapshot(root)
    out = tmp_path / "out"
    assert L.main(["build", PATH, "--out", str(out), "--root", str(root)]) == 0
    assert snapshot(root) == before
    html = (out / "ja" / PATH).read_text(encoding="utf-8")
    assert '<html lang="ja">' in html
    side = json.loads((out / "ja/_tm" / (PATH + ".json")).read_text(encoding="utf-8"))
    assert side["list_src"]["title"]
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "ready" and rep["calls"] == {"translate": 1, "review": 1, "adjudicate": 0}
    assert {"reason", "detail", "tokens", "rounds", "prefs", "seconds"} <= set(rep)
    # 다시 돌리면 out 의 사이드카를 읽어 0 호출
    fakes["ft"], fakes["fr"] = no_call, no_call
    assert L.main(["build", PATH, "--out", str(out), "--root", str(root)]) == 0
    rep2 = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep2["sidecar_from"] == "out" and rep2["calls"] == {"translate": 0, "review": 0, "adjudicate": 0}


def test_no_review_flag(tmp_path, fakes):
    root = make_root(tmp_path / "repo")
    fakes["fr"] = no_call
    out = tmp_path / "out"
    assert L.main(["build", PATH, "--out", str(out), "--root", str(root), "--no-review"]) == 0
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["review"] is False and rep["detail"]["review_skipped"]


def test_held_writes_sidecar_and_report_but_no_html(tmp_path, fakes):
    root = make_root(tmp_path / "repo")
    fakes["ft"] = FT(names=["가타야마 사쓰키"])
    out = tmp_path / "out"
    assert L.main(["build", PATH, "--out", str(out), "--root", str(root)]) == 3
    assert not (out / "ja" / PATH).exists()
    assert (out / "ja/_tm" / (PATH + ".json")).exists()
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "held" and "가타야마 사쓰키" in rep["reason"]


def test_exception_still_reports(tmp_path, fakes):
    root = make_root(tmp_path / "repo")
    out = tmp_path / "out"
    assert L.main(["build", "japan/daily/2099-01-01.html", "--out", str(out), "--root", str(root)]) == 1
    rep = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert rep["status"] == "error" and "FileNotFoundError" in rep["reason"]


def test_usage():
    assert L.main([]) == 2 and L.main(["nope"]) == 2
    assert set(L.COMMANDS) == {"build", "run", "status", "retry"}


# ── run · status · retry ─────────────────────────────────────────────────

def test_run_disabled_does_not_clone(tmp_path, monkeypatch, capsys):
    (tmp_path / "ja").mkdir()
    (tmp_path / "ja/config.json").write_text('{"enabled": false}', encoding="utf-8")
    called = []
    monkeypatch.setattr(L, "_git", lambda *a, **k: called.append(a))
    assert L.main(["run", "--code-root", str(tmp_path)]) == 0
    assert called == [] and "꺼짐" in capsys.readouterr().out


def test_run_enabled_clones_origin_and_publishes(tmp_path, monkeypatch, fakes, capsys):
    from scripts.ja.tests import test_runner as TR
    env = {"tmp": tmp_path, "n": 0}
    seed = tmp_path / "seed"
    seed.mkdir()
    TR.git(seed, "init", "-q", "-b", "main")
    TR._ident(seed)
    files = TR.seed_files()
    files["ja/config.json"] = json.dumps({"enabled": True, "start": "2026-11-01", "windows_kst": [[0, 24]]})
    for rel, body in files.items():
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    TR.git(seed, "add", "-A")
    TR.git(seed, "commit", "-qm", "seed")
    bare = tmp_path / "remote.git"
    TR.git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    site = tmp_path / "site"                                   # 사람 폴더 — 런처의 작업 폴더
    TR.git(tmp_path, "clone", "-q", str(bare), str(site))
    monkeypatch.chdir(site)
    monkeypatch.setenv(L.CACHE_ENV, str(tmp_path / "cache"))
    monkeypatch.setenv("GIT_AUTHOR_NAME", "t")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "t@t")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "t")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "t@t")
    before = TR.git(site, "status", "--porcelain")
    assert L.main(["run", "--code-root", str(seed)]) == 0, capsys.readouterr()
    out = capsys.readouterr().out
    assert "published 1" in out and "발행 pushed" in out
    show = subprocess.run(["git", "show", f"main:ja/{PATH}"], cwd=bare, capture_output=True, text=True)
    assert show.returncode == 0 and '<html lang="ja">' in show.stdout
    assert TR.git(site, "status", "--porcelain") == before     # 사람 폴더는 움직이지 않는다
    # status·retry
    TR.git(site, "pull", "-q")
    assert L.main(["status", "--root", str(site)]) == 0
    assert "발행 1편" in capsys.readouterr().out
    assert L.main(["retry", PATH]) == 0
    assert "지울 시도 기록이 없다" in capsys.readouterr().out


def test_run_entry_is_registered_in_launcher():
    from scripts import runner_launch
    assert runner_launch.ENTRIES["ja"] == "ja_local.py"


def test_plist_example_matches_contested_shape():
    import plistlib
    from pathlib import Path
    p = Path(L.__file__).resolve().parent / "ja" / "com.fdo2a.ja-runner.plist.example"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "com.fdo2a.ja-runner" and d["StartInterval"] == 1800
    assert d["ProgramArguments"][1:] == ["scripts/runner_launch.py", "ja", "run"]
    assert d["WorkingDirectory"].endswith("/site") and d["ExitTimeOut"] == 30


def test_retry_auth_clears_the_login_brake(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(L.CACHE_ENV, str(tmp_path))
    (tmp_path / "auth.json").write_text('{"since": "2026-11-14T11:00:00+09:00", "until": "2026-11-14T17:00:00+09:00"}',
                                        encoding="utf-8")
    assert L.main(["retry", "--auth"]) == 0
    assert "풀었다" in capsys.readouterr().out and not (tmp_path / "auth.json").exists()
    assert L.main(["retry", "--auth"]) == 0 and "없다" in capsys.readouterr().out


def test_retry_with_corrupt_attempts_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(L.CACHE_ENV, str(tmp_path))
    (tmp_path / "attempts.json").write_text("{", encoding="utf-8")
    assert L.main(["retry", PATH]) == 1
    assert "깨졌다" in capsys.readouterr().err and (tmp_path / "attempts.json").read_text() == "{"
