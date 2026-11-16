"""publish — 임시 bare 저장소로 ① 정상 ② 무관한 커밋으로 앞섬 ③ 원본 바뀜 ④ ja/ 밖 스테이징 ⑤ 코드 바뀜."""
import json
import subprocess

import pytest

from scripts.ja import publish as PB

PAGE = "posts/2026-11-13.html"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


def _config(repo):
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    git(repo, "config", "commit.gpgsign", "false")


def write(repo, files, msg="c"):
    for rel, body in files.items():
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", msg)


@pytest.fixture
def remote(tmp_path):
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q", "-b", "main")
    _config(seed)
    write(seed, {PAGE: "<p>원본</p>", "posts.json": json.dumps([{"date": "2026-11-13", "title": "제목"}]),
                 "scripts/ja/x.py": "A = 1\n", "other.txt": "x"})
    bare = tmp_path / "remote.git"
    git(tmp_path, "clone", "-q", "--bare", str(seed), str(bare))
    return bare


def clone(remote, dest):
    git(dest.parent, "clone", "-q", str(remote), str(dest))
    _config(dest)
    return dest


def expect_for(repo):
    return {PAGE: {PAGE: git(repo, "rev-parse", f"HEAD:{PAGE}"),
                   "list:posts.json": PB.current(repo, "HEAD", PAGE, "list:posts.json")}}


def add_ja(repo):
    (repo / "ja/posts").mkdir(parents=True, exist_ok=True)
    (repo / "ja/posts/2026-11-13.html").write_text("<p>原本</p>", encoding="utf-8")
    (repo / "ja/state.json").write_text("{}", encoding="utf-8")


def remote_files(remote):
    return git(remote, "ls-tree", "-r", "--name-only", "main").split("\n")


def test_normal_push(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    exp = expect_for(a)
    add_ja(a)
    assert PB.push(a, message="ja: t (원본 x)", expect=exp) == "pushed"
    assert "ja/posts/2026-11-13.html" in remote_files(remote)
    assert git(remote, "log", "-1", "--format=%s", "main") == "ja: t (원본 x)"
    assert PB.push(a, message="again", expect=exp) == "nothing"


def test_remote_ahead_with_unrelated_commit_rebases(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"other.txt": "y"})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    add_ja(a)
    assert PB.push(a, message="ja: t", expect=exp) == "pushed"
    files = remote_files(remote)
    assert "ja/posts/2026-11-13.html" in files
    assert git(remote, "show", "main:other.txt") == "y"           # 앞선 커밋 위에 올라갔다


def test_korean_list_change_for_another_page_abandons(remote, tmp_path):
    # 이 글의 항목은 그대로지만 다른 글의 항목이 늘었다 — 일본어 목록 다섯은 통째로 만든 것이라 낡았다
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"posts.json": json.dumps([{"date": "2026-11-14", "title": "새 글"},
                                        {"date": "2026-11-13", "title": "제목"}])})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    add_ja(a)
    assert PB.push(a, message="ja: t", expect=exp) == "abandoned: 한글 목록이 그 사이 바뀌었다(posts.json)"
    assert "ja/posts/2026-11-13.html" not in remote_files(remote)


def test_absent_dependency_that_appears_abandons(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"japan/data/news/daily/2026-11-13.json": "{}"})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    exp[PAGE]["japan/data/news/daily/2026-11-13.json"] = ""            # 그때는 없었다
    add_ja(a)
    assert PB.push(a, message="ja: t", expect=exp).startswith("abandoned: 원본이 그 사이 바뀌었다")


def test_list_files_match_lists_module():
    from scripts.ja import lists as L
    assert PB.LIST_FILES == tuple(rel for rel, _f, _t in L.LISTS)


def test_head_ahead_of_origin_is_not_pushed(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    write(a, {"other.txt": "로컬 한글 수정"})                         # 앞선 로컬 커밋(ja/ 밖)
    add_ja(a)
    with pytest.raises(PB.GitError):
        PB.push(a, message="ja: t", expect=expect_for(a))
    assert git(remote, "show", "main:other.txt") == "x" and git(a, "diff", "--cached", "--name-only") == ""


def test_source_changed_on_remote_is_not_pushed(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {PAGE: "<p>정정</p>"})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    add_ja(a)
    got = PB.push(a, message="ja: t", expect=exp)
    assert got.startswith("abandoned") and PAGE in got
    assert "ja/posts/2026-11-13.html" not in remote_files(remote)


def test_list_item_changed_on_remote_is_not_pushed(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"posts.json": json.dumps([{"date": "2026-11-13", "title": "고친 제목"}])})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    add_ja(a)
    assert PB.push(a, message="ja: t", expect=exp).startswith("abandoned")
    assert "ja/state.json" not in remote_files(remote)


def test_path_outside_ja_staged_raises_without_commit(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    head = git(a, "rev-parse", "HEAD")
    add_ja(a)
    (a / "other.txt").write_text("한글 파일을 건드렸다", encoding="utf-8")
    git(a, "add", "other.txt")
    with pytest.raises(PB.OutsideJa):
        PB.push(a, message="ja: t", expect=expect_for(a))
    assert git(a, "rev-parse", "HEAD") == head
    assert "ja/state.json" not in remote_files(remote)


def test_unstaged_change_outside_ja_is_left_alone(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    add_ja(a)
    (a / "other.txt").write_text("작업 트리만", encoding="utf-8")
    assert PB.push(a, message="ja: t", expect=expect_for(a)) == "pushed"
    assert git(remote, "show", "main:other.txt") == "x"


def test_code_changed_on_remote_abandons(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"scripts/ja/x.py": "A = 2\n"})
    git(b, "push", "-q", "origin", "HEAD:main")
    exp = expect_for(a)
    add_ja(a)
    got = PB.push(a, message="ja: t", expect=exp)
    assert got.startswith("abandoned") and "코드" in got
    assert "ja/state.json" not in remote_files(remote)


def test_deletion_is_staged(remote, tmp_path):
    a = clone(remote, tmp_path / "a")
    add_ja(a)
    assert PB.push(a, message="ja: add", expect=expect_for(a)) == "pushed"
    (a / "ja/posts/2026-11-13.html").unlink()
    assert PB.push(a, message="ja: rm", expect={}) == "pushed"
    assert "ja/posts/2026-11-13.html" not in remote_files(remote)


def test_item_hash():
    rows = [{"date": "2026-11-13", "title": "a"}, {"key": "2026-W46", "title": "b"}]
    assert PB.item_hash(rows, "2026-11-13") and PB.item_hash(rows, "2026-W46")
    assert PB.item_hash(rows, "2026-11-12") == "" and PB.item_hash({}, "x") == ""
    assert PB.item_hash(rows, "2026-11-13") != PB.item_hash([{"date": "2026-11-13", "title": "c"}], "2026-11-13")


def test_origin_ahead_of_head_takes_the_reject_path(remote, tmp_path):
    # 그림용 fetch 가 origin/main 을 앞으로 옮겨 둔 사본 — 거절 → 재확인 → rebase 로 올라간다
    a = clone(remote, tmp_path / "a")
    b = clone(remote, tmp_path / "b")
    write(b, {"other.txt": "y"})
    git(b, "push", "-q", "origin", "HEAD:main")
    git(a, "fetch", "-q", "origin", "main")
    exp = expect_for(a)
    add_ja(a)
    assert PB.push(a, message="ja: t", expect=exp) == "pushed"
    assert git(remote, "show", "main:other.txt") == "y"
