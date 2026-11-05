"""검토 큐 만료 — 러너가 닿지 않는 오래된 신규 발행본을 미검토로 세지 않는다 (2026-11-06).

나이는 파일명 날짜가 아니라 **현재 판이 공개된 날**(발행 커밋 날짜)로 잰다 — 미검토인 채로 고친
판·재발행한 판은 새로 센다(codex 설계 검토 #1·#2·#3). 모르면 만료하지 않는다.
"""
from datetime import date

import pytest

from review import expiry
from review.queue import Pending

TODAY = date(2026, 11, 6)


def item(path, reason='신규', sha='a' * 40, section=None):
    from review.queue import section_of
    return Pending(path, section or section_of(path), sha, reason)


def decide(it, published_on, *, today=TODAY, published=True, draft=False):
    tree = {it.path: it.sha} if published else {}
    return expiry.is_expired(it, today=today, published=tree,
                             published_on=lambda path, sha: published_on,
                             has_draft=lambda it: draft)


@pytest.mark.parametrize('path,days,want', [
    ('posts/2026-11-02.html', 3, False),       # 경계: 3일 = 아직
    ('posts/2026-11-02.html', 4, True),
    ('kr/posts/2026-11-02.html', 4, True),
    ('news/2026-10-20.html', 4, True),
    ('news/2026-11-04.html', 2, False),
    ('japan/daily/2026-11-02.html', 4, False),  # 일본 일간 4일
    ('japan/daily/2026-11-01.html', 5, True),
    ('weekly/2026-W43.html', 7, False),         # 주간 7일
    ('weekly/2026-W43.html', 8, True),
    ('kr/weekly/2026-W42.html', 8, True),
    ('japan/posts/2026-W42.html', 8, True),
])
def test_deadline_by_section(path, days, want):
    on = date.fromordinal(TODAY.toordinal() - days)
    assert decide(item(path), on) is want


def test_only_new_items_expire():
    old = date(2026, 10, 1)
    assert decide(item('posts/2026-10-01.html', reason='수정됨'), old) is False
    assert decide(item('posts/2026-10-01.html', reason='판정 불가'), old) is False


def test_unknown_publish_date_never_expires():
    assert decide(item('posts/2026-10-01.html'), None) is False


def test_local_only_version_never_expires():
    """작업 폴더에만 있는 판(공개판과 sha 가 다름)은 사람이 지금 만지는 것이다."""
    assert decide(item('posts/2026-10-01.html'), date(2026, 10, 1), published=False) is False


def test_recently_republished_version_counts_from_its_own_publish():
    """파일명은 10/01 이어도 현재 판이 어제 공개됐다면 아직이다(codex #1·#2)."""
    assert decide(item('posts/2026-10-01.html'), date(2026, 11, 5)) is False


def test_matching_draft_keeps_it():
    assert decide(item('posts/2026-10-01.html'), date(2026, 10, 1), draft=True) is False


@pytest.mark.parametrize('path', [
    'thesis/data/thesis_state.json', 'privacy.html', 'about/2026-10-01.html',
    'posts/2026-13-01.html', 'weekly/2026-W60.html', 'posts/notes.html',
])
def test_unknown_sections_and_formats_never_expire(path):
    assert decide(item(path), date(2026, 1, 1)) is False


def test_future_publish_date_never_expires():
    assert decide(item('posts/2026-11-07.html'), date(2026, 11, 7)) is False


@pytest.mark.parametrize('path', ['posts/2026-11-20.html', 'weekly/2026-W50.html'])
def test_future_file_key_never_expires(path):
    """codex 구현 검토 #3 — 공개는 오래전이어도 파일명이 미래면 남긴다."""
    assert decide(item(path), date(2026, 10, 1)) is False


def test_split_keeps_order_and_reasons():
    a = item('posts/2026-10-01.html')
    b = item('posts/2026-11-05.html', sha='b' * 40)
    c = item('posts/2026-10-02.html', reason='수정됨', sha='c' * 40)
    tree = {x.path: x.sha for x in (a, b, c)}
    dates = {a.path: date(2026, 10, 1), b.path: date(2026, 11, 5), c.path: date(2026, 10, 2)}
    keep, gone = expiry.split([a, b, c], today=TODAY, published=tree,
                              published_on=lambda p, s: dates[p], has_draft=lambda it: False)
    assert keep == [b, c] and gone == [a]


# --- 실제 git 이력·초안 폴더(codex 구현 검토 #2·#1·#4) ---

import json
import os
import subprocess

import review_gate as rg
from review.runner import KST


def _repo(tmp_path):
    def run(*a, env=None):
        subprocess.run(a, cwd=tmp_path, check=True, capture_output=True, env=env)
    run('git', 'init', '-q', '-b', 'main')
    run('git', 'config', 'user.email', 't@t'); run('git', 'config', 'user.name', 't')
    os.makedirs(tmp_path / 'posts')

    def commit(text, when):
        (tmp_path / 'posts' / '2026-10-01.html').write_text(text)
        env = dict(os.environ, GIT_COMMITTER_DATE=when, GIT_AUTHOR_DATE=when)
        run('git', 'add', '-A'); run('git', 'commit', '-q', '-m', 'x', env=env)
    return run, commit


def _sha(tmp_path):
    return subprocess.run(['git', 'rev-parse', 'HEAD:posts/2026-10-01.html'], cwd=tmp_path,
                          capture_output=True, text=True).stdout.strip()


def test_first_published_is_when_this_blob_arrived(tmp_path):
    run, commit = _repo(tmp_path)
    commit('v1', '2026-10-01T09:00:00+09:00')
    commit('v2', '2026-11-05T09:00:00+09:00')     # 오늘 가까이 고친 판
    run('git', 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    when = rg.first_published(str(tmp_path), 'posts/2026-10-01.html', _sha(tmp_path), KST)
    assert when == date(2026, 11, 5)


def test_first_published_none_when_not_the_published_blob(tmp_path):
    run, commit = _repo(tmp_path)
    commit('v1', '2026-10-01T09:00:00+09:00')
    run('git', 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    assert rg.first_published(str(tmp_path), 'posts/2026-10-01.html', 'f' * 40, KST) is None


def test_split_expired_keeps_everything_when_drafts_unreadable(tmp_path, monkeypatch):
    it = item('posts/2026-10-01.html')
    real = os.listdir

    def boom(path):
        if str(path).endswith(rg.DRAFTS):
            raise PermissionError(path)
        return real(path)
    monkeypatch.setattr(rg.os, 'listdir', boom)
    monkeypatch.setattr(rg, 'first_published', lambda *a: date(2026, 10, 1))
    keep, gone = rg._split_expired(str(tmp_path), [it], {it.path: it.sha})
    assert keep == [it] and gone == []


def _legacy(monkeypatch, yes=True):
    monkeypatch.setattr(rg, 'rev_parse', lambda root, spec: ('a' * 40) if yes else None)


def test_split_expired_drops_old_new_item(tmp_path, monkeypatch):
    it = item('posts/2026-10-01.html')
    _legacy(monkeypatch)
    monkeypatch.setattr(rg, 'first_published', lambda *a: date(2026, 10, 1))
    keep, gone = rg._split_expired(str(tmp_path), [it], {it.path: it.sha})
    assert keep == [] and gone == [it]


def test_old_commit_pushed_late_counts_from_first_seen(tmp_path, monkeypatch):
    """codex 재검토 — 며칠 묵힌 커밋(기록 시작 뒤)을 오늘 처음 보면 오늘부터 센다."""
    it = item('posts/2026-11-01.html')
    _legacy(monkeypatch, yes=False)      # 기록 시작 때 공개돼 있지 않던 판
    monkeypatch.setattr(rg, 'first_published', lambda *a: date(2026, 11, 1))
    keep, gone = rg._split_expired(str(tmp_path), [it], {it.path: it.sha})
    assert keep == [it] and gone == []
    seen = json.load(open(tmp_path / rg.SEEN))
    assert seen[it.path]['sha'] == it.sha


def test_seen_record_for_other_sha_is_replaced(tmp_path, monkeypatch):
    it = item('posts/2026-10-01.html')
    os.makedirs(tmp_path / 'reviews')
    (tmp_path / rg.SEEN).write_text(json.dumps({it.path: {'sha': 'b' * 40, 'at': '2026-09-01'}}))
    monkeypatch.setattr(rg, 'first_published', lambda *a: date(2026, 10, 1))
    rg._split_expired(str(tmp_path), [it], {it.path: it.sha})
    assert json.load(open(tmp_path / rg.SEEN))[it.path]['sha'] == it.sha


def test_first_published_skips_typography_only_commits(tmp_path, monkeypatch):
    """조판 판 올림 커밋은 공개일을 되돌리지 않는다 — 내용이 바뀐 커밋에서는 멈춘다."""
    run, commit = _repo(tmp_path)
    commit('v1', '2026-09-01T09:00:00+09:00')
    commit('v2', '2026-10-01T09:00:00+09:00')     # 내용 변경
    commit('v2-typo', '2026-11-06T01:00:00+09:00')  # 조판만
    run('git', 'update-ref', 'refs/remotes/origin/main', 'HEAD')
    monkeypatch.setattr(rg.prose_mod, 'typography',
                        lambda path, old, new, root=None: (old, new) == ('v2', 'v2-typo'))
    when = rg.first_published(str(tmp_path), 'posts/2026-10-01.html', _sha(tmp_path), KST)
    assert when == date(2026, 10, 1)


def test_unsaved_seen_record_does_not_expire(tmp_path, monkeypatch):
    """codex 재검토 — 기록을 저장하지 못하면 그 판은 「처음 본 날」을 모르는 것이다."""
    it = item('posts/2026-10-01.html')
    _legacy(monkeypatch)
    monkeypatch.setattr(rg, 'first_published', lambda *a: date(2026, 10, 1))

    def fail(*a, **k):
        raise OSError('disk full')
    monkeypatch.setattr(rg.tempfile, 'mkstemp', fail)
    keep, gone = rg._split_expired(str(tmp_path), [it], {it.path: it.sha})
    assert keep == [it] and gone == []
