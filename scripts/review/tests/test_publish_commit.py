"""`publish_commit()` 은 조판만 바꾼 커밋을 건너뛰어 본문이 들어온 커밋을 가리킨다.

2026-09-26 실측: 방문 통계 소급(8458e9a, 9/25)이 발행본 SHA 를 전부 움직여, 미검토
US·KR 12편 중 11편의 「발행 커밋」이 9/25 커밋이 됐다. 근거 데이터는 날짜별이 아니라
한 자리를 덮어쓰므로, 9/17 글이 9/25 데이터와 맞대져 정상 문장이 오류로 정정될 뻔했다.
"""
import subprocess

import pytest

import review_gate as g
from common import analytics
from review.tests.blocks import CUR, PREV

POST = 'posts/2026-09-21.html'
DATA = 'data/market_data.json'
BODY = "<div class='card'><p>S&amp;P 500 은 0.4% 올랐다.</p></div>"


def _doc(css=CUR, body=BODY):
    return ("<!DOCTYPE html><html><head><title>t</title><style>" + css + "</style>\n"
            "</head><body>" + body + "</body></html>")


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = str(tmp_path / 'origin.git')
    root = str(tmp_path / 'work')
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', origin], check=True)
    subprocess.run(['git', 'clone', '-q', origin, root], check=True,
                   capture_output=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    return root


def commit(repo, files, message):
    for rel, text in files.items():
        path = f'{repo}/{rel}'
        subprocess.run(['mkdir', '-p', path.rsplit('/', 1)[0]], check=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        git(repo, 'add', rel)
    git(repo, 'commit', '-q', '-m', message)
    git(repo, 'push', '-q', 'origin', 'HEAD:main')
    git(repo, 'fetch', '-q', 'origin')
    return git(repo, 'rev-parse', 'HEAD')


def blob(repo):
    return git(repo, 'rev-parse', f'origin/main:{POST}')


def test_analytics_backfill_points_back_to_the_publishing_commit(repo):
    published = commit(repo, {POST: _doc(), DATA: '{"day": "09-21"}'}, 'publish')
    commit(repo, {DATA: '{"day": "09-25"}'}, 'collect')
    commit(repo, {POST: analytics.inject(_doc())}, 'backfill loader')
    assert g.publish_commit(repo, POST, blob(repo)) == published


def test_readability_upgrade_then_loader_still_points_back(repo):
    published = commit(repo, {POST: _doc(css=PREV), DATA: '{"day": "09-21"}'}, 'publish')
    commit(repo, {POST: _doc(css=CUR), DATA: '{"day": "09-23"}'}, 'typeset')
    commit(repo, {POST: analytics.inject(_doc(css=CUR))}, 'backfill loader')
    assert g.publish_commit(repo, POST, blob(repo)) == published


def test_a_prose_correction_stops_the_walk(repo):
    """정정 재발행은 새 판이다 — 그 판을 넣은 커밋에서 멈춘다(기존 동작)."""
    commit(repo, {POST: _doc(), DATA: '{"day": "09-21"}'}, 'publish')
    fixed = commit(repo, {POST: _doc(body=BODY.replace('0.4%', '0.5%'))}, 'correct')
    assert g.publish_commit(repo, POST, blob(repo)) == fixed


def test_loader_smuggled_with_a_prose_edit_stops_the_walk(repo):
    commit(repo, {POST: _doc(), DATA: '{"day": "09-21"}'}, 'publish')
    sneaky = commit(repo, {POST: analytics.inject(_doc(body=BODY.replace('0.4%', '0.9%')))},
                    'backfill loader')
    assert g.publish_commit(repo, POST, blob(repo)) == sneaky


def test_unknown_blob_is_none(repo):
    commit(repo, {POST: _doc()}, 'publish')
    assert g.publish_commit(repo, POST, '0' * 40) is None


def _item(sha, path=POST, section='us'):
    from types import SimpleNamespace
    return SimpleNamespace(path=path, section=section, sha=sha)


def test_evidence_from_the_same_day_passes(repo):
    commit(repo, {POST: _doc(), DATA: '{"report_date": "2026-09-21"}'}, 'publish')
    commit(repo, {DATA: '{"report_date": "2026-09-25"}'}, 'collect')
    commit(repo, {POST: analytics.inject(_doc())}, 'backfill loader')
    assert g.evidence_mismatch(repo, _item(blob(repo))) is None


def test_backfilled_post_with_next_days_data_is_held_back(repo):
    """9/17 글이 9/19 에 9/18 데이터로 소급 발행된 모양."""
    commit(repo, {POST: _doc(), DATA: '{"report_date": "2026-09-22"}'}, 'late publish')
    why = g.evidence_mismatch(repo, _item(blob(repo)))
    assert why and '2026-09-22' in why and '2026-09-21' in why


def test_missing_evidence_date_is_held_back(repo):
    commit(repo, {POST: _doc()}, 'publish')
    assert g.evidence_mismatch(repo, _item(blob(repo)))


def test_non_daily_pages_are_not_judged(repo):
    commit(repo, {'weekly/2026-W38.html': _doc()}, 'weekly')
    sha = git(repo, 'rev-parse', 'origin/main:weekly/2026-W38.html')
    assert g.evidence_mismatch(repo, _item(sha, 'weekly/2026-W38.html', 'weekly')) is None


def test_misdated_items_are_dropped_before_quota(repo):
    commit(repo, {POST: _doc(), DATA: '{"report_date": "2026-09-22"}'}, 'late publish')
    errs = {}
    assert g._drop_misdated(repo, [_item(blob(repo))], errs) == []
    assert '근거' in errs
    commit(repo, {DATA: '{"report_date": "2026-09-21"}', POST: _doc(body='<p>x</p>')}, 'fix')
    assert len(g._drop_misdated(repo, [_item(blob(repo))], errs)) == 1
    assert '근거' not in errs
