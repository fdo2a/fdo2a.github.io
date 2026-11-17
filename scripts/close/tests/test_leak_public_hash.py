"""staged-scan — 공개될 글 자체의 해시는 유출이 아니다 (2026-11-17).

발행 전 검증 기록(`verification/<market>/<date>.json`, 2026-11-08 도입)은 글의 sha256 을 정당하게 담는다.
그런데 감사 기록의 지문에도 같은 값이 들어 있어(편집 0 이면 `source_sha256`, 편집이 실리면
`rounds[].proposed_sha256`) 문체 마감 길이 돈 날마다 staged-scan 이 FOUND 를 냈다. 2026-11-09 루틴은
중단 규칙을 넘겨 발행했고, 2026-11-16 루틴은 검토 전 초안으로 되돌려 정확성 수정이 빠졌다.

허용은 좁다: 그 날짜 검증 기록의 `post.sha256` 과 작업 파일(html) 입력 항목의 `sha256` 이 **staged 된 글의
실제 바이트**(또는 에디터 노트 한 블록을 걷어낸 바이트)의 해시일 때만. 그 밖의 자리·파일·지문은 그대로 잡는다.
"""

import hashlib
import json
import os
import subprocess
import sys

import pytest

from close import leak
from us.editor_note import apply_note, render_note

SCRIPTS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUARD = os.path.join(SCRIPTS, 'close_guard.py')
DATE = '2026-11-16'
POST = 'posts/%s.html' % DATE
RECORD = 'verification/us/%s.json' % DATE
BODY = ('<html><body><div class="doc"><section><h2>오늘의 장</h2><div class="card">'
        '<p>지수는 저점 부근에서 끝났다.</p></div></section></div></body></html>\n')
EDITED = BODY.replace('저점 부근에서', '저점 가까이에서')
UUID = 'f59fa088f25d4705a7a0d135ddbf601c'
WHY = '주체와 관계가 그대로 유지된다'


def sha(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _git(repo, *args):
    subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    r.mkdir()
    _git(r, 'init', '-q')
    _git(r, 'config', 'user.email', 't@t')
    _git(r, 'config', 'user.name', 't')
    (r / 'posts.json').write_text('[]\n')
    _git(r, 'add', '-A')
    _git(r, 'commit', '-qm', 'init')
    return r


def record(post_sha, ws_sha, extra=None, post_path=POST):
    """실제 검증 기록의 뼈대(2026-11-16 판)."""
    doc = {
        'gates': [{'name': 'check_macro', 'output_sha256': 'a' * 64, 'script_sha256': 'b' * 64}],
        'inputs': {'files': [
            {'path': '<datadir>/market_data.json', 'ref': 'repo:data/market_data.json', 'sha256': 'c' * 64},
            {'path': '<datadir>/morning_brief_%s.body.html' % DATE, 'ref': 'workspace-only', 'sha256': 'd' * 64},
            {'path': '<datadir>/morning_brief_%s.html' % DATE, 'ref': 'workspace-only', 'sha256': ws_sha},
        ]},
        'market': 'us',
        'post': {'blob': '0' * 40, 'path': post_path, 'sha256': post_sha},
    }
    doc.update(extra or {})
    return json.dumps(doc, ensure_ascii=False, indent=1) + '\n'


def stage(repo, post_text, record_text, others=None):
    for rel, text in [(POST, post_text), (RECORD, record_text), *(others or {}).items()]:
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    _git(repo, 'add', '-A')


def audit(source, approved, proposed=None, **more):
    doc = {'uuid': UUID, 'market': 'us', 'date': DATE, 'source_sha256': source, 'rounds': [],
           'outcome': 'applied' if proposed else 'zero:guard_input', 'approved_sha256': approved}
    if proposed:
        doc['rounds'] = [{'round': 1, 'proposed_sha256': proposed, 'bundles': [{'hash': 'e' * 64}],
                          'verdicts': {'B01': {'verdict': 'same', 'why': WHY}}}]
    doc.update(more)
    return doc


# ------------------------------------------------------------ 정상 기록은 걸리지 않는다

def test_zero_edit_day_is_clean(repo):
    """11/16 꼴 — 편집 0: source == approved == 글 해시."""
    h = sha(BODY)
    stage(repo, BODY, record(h, h))
    assert leak.staged_hits(str(repo), audit(h, h)) == []


def test_applied_edit_day_is_clean(repo):
    """11/09 꼴 — 편집이 실림: rounds[].proposed_sha256 == 글 해시, source 는 고치기 전 판."""
    h = sha(EDITED)
    stage(repo, EDITED, record(h, h))
    assert leak.staged_hits(str(repo), audit(sha(BODY), h, proposed=h)) == []


def test_gate_restored_day_is_clean(repo):
    """편집 뒤 게이트가 막아 고치기 전 판으로 복원 — 감사 기록의 approved 는 편집판 그대로 남는다."""
    h = sha(BODY)
    stage(repo, BODY, record(h, h))
    a = audit(h, sha(EDITED), proposed=sha(EDITED), outcome='gate_restored')
    assert leak.staged_hits(str(repo), a) == []


def test_editor_note_day_is_clean(repo):
    """노트가 붙은 날 — 글 해시는 노트 포함, 작업 파일 입력 항목은 노트 없는 승인판 해시."""
    noted = apply_note(BODY, render_note('# 메모\n\n오늘은 반도체를 본다.\n', DATE))
    assert noted != BODY
    stage(repo, noted, record(sha(noted), sha(BODY)))
    assert leak.staged_hits(str(repo), audit(sha(BODY), sha(BODY))) == []


def test_cli_exit_zero_on_normal_record(repo, tmp_path):
    h = sha(BODY)
    stage(repo, BODY, record(h, h))
    (tmp_path / 'audit.json').write_text(json.dumps(audit(h, h), ensure_ascii=False))
    r = subprocess.run([sys.executable, GUARD, 'staged-scan', '--repo', str(repo),
                        '--audit', str(tmp_path / 'audit.json')], capture_output=True, text=True)
    assert r.returncode == 0 and 'clean' in r.stdout


# ------------------------------------------------------------ 실제 유출은 계속 잡는다

def test_private_draft_hash_in_allowed_field_is_found(repo):
    """고치기 전 초안(비공개)의 해시가 post.sha256 자리에 있어도, 글의 실제 바이트와 다르면 유출이다."""
    stage(repo, EDITED, record(sha(BODY), sha(EDITED)))
    assert leak.staged_hits(str(repo), audit(sha(BODY), sha(EDITED), proposed=sha(EDITED))) == [RECORD]


def test_same_hash_in_other_field_is_found(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h, extra={'manual': '참고 ' + h}))
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_same_hash_in_other_input_entry_is_found(repo):
    """html 작업 파일이 아닌 입력 항목에 글 해시가 들어가면 허용하지 않는다."""
    h = sha(BODY)
    text = record(h, h).replace('c' * 64, h)
    stage(repo, BODY, text)
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_same_hash_in_other_file_is_found(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h), others={'reviews/prepublish/us/%s.json' % DATE: '{"draft": "%s"}\n' % h})
    assert leak.staged_hits(str(repo), audit(h, h)) == ['reviews/prepublish/us/%s.json' % DATE]


def test_other_date_record_is_not_allowed(repo):
    """허용은 감사 기록의 시장·날짜 검증 기록 하나뿐이다."""
    h = sha(BODY)
    stage(repo, BODY, record(h, h), others={'verification/us/2026-11-13.json': record(h, h)})
    assert leak.staged_hits(str(repo), audit(h, h)) == ['verification/us/2026-11-13.json']


@pytest.mark.parametrize('extra', [{'manual': UUID}, {'manual': WHY}, {'outcome': 'applied'},
                                   {'manual': 'e' * 64}, {'proposed_sha256': 'x'}])
def test_other_fingerprints_in_record_are_found(repo, extra):
    h = sha(BODY)
    stage(repo, BODY, record(h, h, extra=extra))
    assert leak.staged_hits(str(repo), audit(h, h, proposed=h)) == [RECORD]


def test_editor_note_on_real_post_shape_is_clean(repo):
    """줄바꿈으로 나뉜 실제 글 꼴에서도 노트를 걷어낸 판이 승인판과 바이트가 같다."""
    body = BODY.replace('><', '>\n<')
    noted = apply_note(body, render_note('# 메모\n\n오늘은 반도체를 본다.\n', DATE))
    stage(repo, noted, record(sha(noted), sha(body)))
    assert leak.staged_hits(str(repo), audit(sha(body), sha(body))) == []


def test_note_day_with_unrelated_hash_is_found(repo):
    """노트가 붙은 날에도 글·승인판과 무관한 비공개 해시는 잡는다."""
    noted = apply_note(BODY, render_note('# 메모\n\n오늘은 반도체를 본다.\n', DATE))
    stage(repo, noted, record(sha(noted), sha(EDITED)))
    assert leak.staged_hits(str(repo), audit(sha(BODY), sha(EDITED), proposed=sha(EDITED))) == [RECORD]


def test_broken_record_gets_no_allowance(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h).rstrip()[:-1])          # 닫는 중괄호 없음
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_duplicate_keys_get_no_allowance(repo):
    h = sha(BODY)
    text = record(h, h).replace('"market": "us"', '"post": {"sha256": "%s"},\n "market": "us"' % ('f' * 64))
    stage(repo, BODY, text)
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_record_pointing_at_unstaged_post_gets_no_allowance(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h, post_path='posts/없는글.html'))
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_audit_without_market_or_date_gets_no_allowance(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h))
    a = audit(h, h)
    del a['date']
    assert leak.staged_hits(str(repo), a) == [RECORD]


def test_working_tree_post_is_not_trusted(repo):
    """인덱스의 글이 기준이다 — add 뒤 작업 파일만 바꿔도 허용이 따라 바뀌지 않는다."""
    h = sha(BODY)
    stage(repo, EDITED, record(h, h))                       # 인덱스의 글은 EDITED, 기록은 BODY 해시
    (repo / POST).write_text(BODY, encoding='utf-8')        # 작업 파일만 BODY 로
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


# ------------------------------------------------------------ codex 구현 검토 1회차 (2026-11-17)

def test_editor_note_after_blank_lines_is_clean(repo):
    """#1 — 승인판이 빈 줄로 끝나면 노트 앞 공백이 여러 개다. 노트를 붙이기 전 판을 정확히 되돌려야 한다."""
    body = '<html><body><div class="doc"><p>지수는 저점 부근에서 끝났다.</p>\n\n</div>\n\n</body></html>\n'
    noted = apply_note(body, render_note('# 메모\n\n오늘은 반도체를 본다.\n', DATE))
    assert noted != body
    stage(repo, noted, record(sha(noted), sha(body)))
    assert leak.staged_hits(str(repo), audit(sha(body), sha(body))) == []


def test_escaped_slot_does_not_hide_plain_copy(repo):
    """#2 — 허용 자리의 값을 \\u 이스케이프로 적고 같은 해시를 다른 필드에 평문으로 두면 잡는다."""
    h = sha(BODY)
    text = record(h, 'f' * 64, extra={'manual': h})
    i = next(n for n, c in enumerate(h) if c in 'abcdef')       # 숫자는 \\u003N 의 끝 글자가 자기 자신이다
    escaped = h[:i] + '\\u00%02x' % ord(h[i]) + h[i + 1:]
    text = text.replace('"sha256": "%s"' % h, '"sha256": "%s"' % escaped, 1)
    assert json.loads(text)['post']['sha256'] == h and text.count(h) == 1
    stage(repo, BODY, text)
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_other_fingerprint_on_same_line_is_found(repo):
    """#2 — 허용 해시와 같은 줄에 다른 지문이 있으면 그 줄은 그대로 걸린다."""
    h = sha(BODY)
    doc = json.loads(record(h, h))
    doc['post']['note'] = UUID
    stage(repo, BODY, json.dumps(doc, ensure_ascii=False) + '\n')        # 한 줄 JSON
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_post_path_must_be_that_days_publish_path(repo):
    """#4 — 기록의 post.path 를 인덱스의 다른 파일로 돌려도 그 파일의 해시는 공개 글 해시가 아니다."""
    h = sha(BODY)
    stage(repo, EDITED, record(h, h, post_path='draft.html'), others={'draft.html': BODY})
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_symlinked_post_gets_no_allowance(repo):
    """#4 — 글 경로가 심볼릭 링크면 받지 않는다."""
    h = sha(BODY)
    (repo / 'real.html').write_text(BODY, encoding='utf-8')
    (repo / 'posts').mkdir()
    os.symlink('../real.html', repo / POST)
    (repo / 'verification' / 'us').mkdir(parents=True)
    (repo / RECORD).write_text(record(h, h), encoding='utf-8')
    _git(repo, 'add', '-A')
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_unknown_market_gets_no_allowance(repo):
    h = sha(BODY)
    stage(repo, BODY, record(h, h), others={'verification/jp/%s.json' % DATE: record(h, h)})
    a = audit(h, h)
    a['market'] = 'jp'
    assert set(leak.staged_hits(str(repo), a)) == {RECORD, 'verification/jp/%s.json' % DATE}


def test_kr_record_shape_is_clean(repo):
    """#5 — KR 기록에는 작업 파일 html 항목이 없다: post.sha256 한 자리뿐."""
    h = sha(BODY)
    doc = json.loads(record(h, 'f' * 64, post_path='kr/posts/%s.html' % DATE))
    doc['market'] = 'kr'
    doc['inputs']['files'] = [{'path': '<datadir>/kr_sector.html', 'ref': 'repo:kr/data/kr_sector.html',
                               'sha256': 'c' * 64}]
    for rel, text in (('kr/posts/%s.html' % DATE, BODY),
                      ('verification/kr/%s.json' % DATE, json.dumps(doc, ensure_ascii=False, indent=1) + '\n')):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding='utf-8')
    _git(repo, 'add', '-A')
    a = audit(h, h)
    a['market'] = 'kr'
    assert leak.staged_hits(str(repo), a) == []


def test_html_input_recorded_as_repo_post_is_clean(repo):
    """#5 — record 가 작업 파일 html 을 같은 바이트의 레포 글로 적은 경우(`repo:<글 경로>`)."""
    h = sha(BODY)
    text = record(h, h).replace('"ref": "workspace-only",\n    "sha256": "%s"' % h,
                                '"ref": "repo:%s",\n    "sha256": "%s"' % (POST, h))
    assert 'repo:' + POST in text
    stage(repo, BODY, text)
    assert leak.staged_hits(str(repo), audit(h, h)) == []


def test_html_input_recorded_as_other_repo_file_is_found(repo):
    h = sha(BODY)
    text = record(h, h).replace('"ref": "workspace-only",\n    "sha256": "%s"' % h,
                                '"ref": "repo:data/other.html",\n    "sha256": "%s"' % h)
    stage(repo, BODY, text)
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_rerecord_after_commit_is_clean(repo):
    """#5 — pull·rebase 뒤 record 를 다시 돌려 amend 하는 길: 글·기록이 이미 커밋돼 있고 둘 다 새로 staged 된다."""
    h = sha(BODY)
    stage(repo, BODY, record(h, h))
    _git(repo, 'commit', '-qm', 'publish')
    assert leak.staged_hits(str(repo), audit(h, h)) == []               # staged 변경 없음
    h2 = sha(EDITED)
    stage(repo, EDITED, record(h2, h2))
    assert leak.staged_hits(str(repo), audit(h, h2, proposed=h2)) == []
    stage(repo, EDITED, record(h2, h2, extra={'manual': h}))             # 고치기 전 판(비공개) 해시가 섞이면
    assert leak.staged_hits(str(repo), audit(h, h2, proposed=h2)) == [RECORD]


# ------------------------------------------------------------ codex 구현 검토 2회차 (2026-11-17)

@pytest.mark.parametrize('bad', [[], {}, 7, None, True])
def test_non_string_hash_in_slot_keeps_scanning(repo, bad):
    """허용 자리의 값이 문자열이 아니어도 예외 없이 지문 검사를 계속한다."""
    h = sha(BODY)
    doc = json.loads(record(h, h, extra={'manual': UUID}))
    doc['post']['sha256'] = bad
    stage(repo, BODY, json.dumps(doc, ensure_ascii=False, indent=1) + '\n')
    assert leak.staged_hits(str(repo), audit(h, h)) == [RECORD]


def test_replaced_note_is_found_not_allowed(repo):
    """한계 — 승인판에 이미 노트가 있었고 새 노트로 갈아 끼웠으면 승인판을 되돌릴 수 없다: 허용 없이 멈춘다."""
    first = apply_note(BODY, render_note('# 메모\n\n어제 쓴 노트.\n', DATE))
    second = apply_note(first, render_note('# 메모\n\n오늘 쓴 노트.\n', DATE))
    assert second != first
    stage(repo, second, record(sha(second), sha(first)))
    assert leak.staged_hits(str(repo), audit(sha(first), sha(first))) == [RECORD]
