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


# ── 쟁점 러너가 발행 뒤 자리표시를 채운 커밋(KR 설계 검토 K05·K06) ─────────────
KR_POST = 'kr/posts/2026-10-20.html'
KR_DATA = 'kr/data/kr_market_data.json'
SECTION = ('<section id="contested" data-contested="abc"><h2>쟁점 분석 — 환율</h2>'
           '<div class="card"><p>원화 강세가 이어진다.</p></div></section>')


def test_contested_fill_points_back_to_the_publishing_commit(repo):
    from common import contested as C
    base = BODY + '\n' + C.PENDING
    published = commit(repo, {KR_POST: _doc(body=base), KR_DATA: '{"report_date": "2026-10-20"}'},
                       'publish')
    commit(repo, {KR_DATA: '{"report_date": "2026-10-21"}'}, 'next day data')
    commit(repo, {KR_POST: _doc(body=BODY + '\n' + SECTION)}, 'contested fill')
    sha = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert g.publish_commit(repo, KR_POST, sha) == published


def test_contested_step_rejects_edits_outside_the_section(repo):
    from common import contested as C
    published = commit(repo, {KR_POST: _doc(body=BODY + '\n' + C.PENDING)}, 'publish')
    edited = commit(repo, {KR_POST: _doc(body=BODY.replace('0.4%', '0.5%') + '\n' + SECTION)},
                    'fill and edit')
    sha = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert g.publish_commit(repo, KR_POST, sha) == edited != published


def test_review_snapshot_drops_contested_section(tmp_path):
    p = tmp_path / 'post.html'
    p.write_text(_doc(body=BODY + '\n' + SECTION), encoding='utf-8')
    g._drop_contested(str(p))
    text = p.read_text(encoding='utf-8')
    assert 'data-contested' not in text and '0.4%' in text


def test_corrector_replays_contested_gate_only_when_section_present(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace
    from review import corrector
    post = tmp_path / KR_POST
    post.parent.mkdir(parents=True)
    post.write_text(_doc(body=BODY + '\n' + SECTION), encoding='utf-8')
    item = SimpleNamespace(path=KR_POST, section='kr')
    name, args = corrector._contested_gate(Path(tmp_path), item, str(post))
    assert name == 'check_contested.py'
    assert args[args.index('--market') + 1] == 'kr' and args[args.index('--date') + 1] == '2026-10-20'
    assert args[args.index('--json') + 1].endswith('data/contested/kr/2026-10-20.json')
    post.write_text(_doc(), encoding='utf-8')
    assert corrector._contested_gate(Path(tmp_path), item, str(post)) is None
    # 결과가 있는 날 정정이 섹션을 통째로 지워도 게이트는 돈다
    data = tmp_path / 'data' / 'contested' / 'kr' / '2026-10-20.json'
    data.parent.mkdir(parents=True)
    data.write_text('{}', encoding='utf-8')
    assert corrector._contested_gate(Path(tmp_path), item, str(post))[0] == 'check_contested.py'
    us = SimpleNamespace(path='posts/2026-10-20.html', section='us')
    assert corrector._contested_gate(Path(tmp_path), us, str(post)) is None


def test_next_day_placeholder_removal_points_back_only_when_result_is_final(repo):
    from common import contested as C
    published = commit(repo, {KR_POST: _doc(body=BODY + '\n' + C.PENDING),
                              KR_DATA: '{"report_date": "2026-10-20"}'}, 'publish')
    commit(repo, {KR_DATA: '{"report_date": "2026-10-21"}'}, 'next day data')
    none = {'schema_version': 1, 'market': 'kr', 'span': 'daily', 'report_date': '2026-10-20',
            'status': 'none', 'reason': 'no_conflict', 'retryable': False}
    none['content_hash'] = C.content_hash(none)
    import json
    commit(repo, {KR_POST: _doc(body=BODY + '\n'),
                  'data/contested/kr/2026-10-20.json': json.dumps(none)}, 'contested clear')
    sha = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert g.publish_commit(repo, KR_POST, sha) == published


def test_hand_deleted_section_is_a_new_publish(repo):
    from common import contested as C
    import json
    commit(repo, {KR_POST: _doc(body=BODY + '\n' + SECTION),
                  'data/contested/kr/2026-10-20.json': json.dumps({'status': 'ok'})}, 'publish')
    deleted = commit(repo, {KR_POST: _doc(body=BODY + '\n')}, 'delete section by hand')
    sha = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert g.publish_commit(repo, KR_POST, sha) == deleted


def test_corrector_entry_accepts_contested_fill(repo):
    from pathlib import Path
    from common import contested as C
    from review import corrector
    commit(repo, {KR_POST: _doc(body=BODY + '\n' + C.PENDING)}, 'publish')
    old = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    commit(repo, {KR_POST: _doc(body=BODY + '\n' + SECTION)}, 'fill')
    new = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert corrector._typeset_only(Path(repo), KR_POST, old, new)
    commit(repo, {KR_POST: _doc(body=BODY.replace('0.4%', '0.9%') + '\n' + SECTION)}, 'edit')
    edited = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert not corrector._typeset_only(Path(repo), KR_POST, old, edited)


def test_corrector_accepts_typesetting_then_fill(repo):
    """A=자리표시·옛 조판 → B=자리표시·새 조판 → C=채움·새 조판 (구현 검토 2차 N3)."""
    from pathlib import Path
    from common import contested as C
    from review import corrector
    commit(repo, {KR_POST: _doc(css=PREV, body=BODY + '\n' + C.PENDING)}, 'publish')
    a = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    commit(repo, {KR_POST: _doc(css=CUR, body=BODY + '\n' + C.PENDING)}, 'typeset')
    commit(repo, {KR_POST: _doc(css=CUR, body=BODY + '\n' + SECTION)}, 'fill')
    c = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
    assert g.publish_commit(repo, KR_POST, c) is not None
    assert corrector._typeset_only(Path(repo), KR_POST, a, c)


def test_contested_step_tolerates_non_object_json(repo):
    from common import contested as C
    commit(repo, {KR_POST: _doc(body=BODY + '\n' + C.PENDING)}, 'publish')
    for bad in ('[1]', '"broken"', '123'):
        commit(repo, {KR_POST: _doc(body=BODY + '\n' + C.PENDING) + bad,
                      'data/contested/kr/2026-10-20.json': bad}, f'reset {bad}')
        removed = commit(repo, {KR_POST: _doc(body=BODY + '\n') + bad}, f'clear {bad}')
        sha = git(repo, 'rev-parse', f'origin/main:{KR_POST}')
        assert g.publish_commit(repo, KR_POST, sha) == removed     # 예외 없이 새 발행으로 본다


def test_contested_gate_is_never_tolerated():
    from review import corrector
    assert 'check_contested.py' in corrector.NEVER_TOLERATE
