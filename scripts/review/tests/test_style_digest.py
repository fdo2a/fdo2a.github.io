import json
import os

from review import style_digest as d


def _rec(root, name, at, findings):
    folder = os.path.join(root, d.FOLDER)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, name), 'w', encoding='utf-8') as fh:
        json.dump({'at': at, 'path': 'posts/%s.html' % name[:10], 'findings': findings}, fh, ensure_ascii=False)


def test_digest_groups_by_kind_and_window(tmp_path):
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    _rec(tmp_path, '2026-11-05.json', now.isoformat(), [
        {'kind': '끊긴 흐름', 'quote': 'a', 'note': 'b'}, {'kind': '번역투', 'quote': 'c', 'note': 'd'},
        {'kind': '끊긴 흐름', 'quote': 'e', 'note': 'f'}])
    _rec(tmp_path, '2026-10-01.json', (now - timedelta(days=30)).isoformat(), [{'kind': '반복'}])
    _rec(tmp_path, 'broken.json', 'x', [{'kind': '반복'}])
    rows = d.collect(str(tmp_path), d._since('7d'))
    assert len(rows) == 3
    text = d.digest(rows)
    assert text.splitlines()[0] == '문체 지적 묶음 — 3건, 글 1편'
    assert text.index('[끊긴 흐름] 2건') < text.index('[번역투] 1건')
    assert '반복' not in text


def test_digest_cli_empty(tmp_path, capsys):
    assert d.main(['--root', str(tmp_path)]) == 0
    assert '0건' in capsys.readouterr().out


# ── 명료성 지적의 주간 묶음(2026-11-18) — 아무것도 고치지 않고, 아무것도 쓰지 않는다 ─────────────

import subprocess


def _git(root, *args):
    subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True)


def _repo(tmp_path):
    root = tmp_path / 'repo'
    (root / 'posts').mkdir(parents=True)
    (root / 'reviews/prepublish/us').mkdir(parents=True)
    _git(root, 'init', '-q')
    _git(root, 'config', 'user.email', 't@example.invalid')
    _git(root, 'config', 'user.name', 't')
    return root


def _publish(root, date, html, clarity, **extra):
    from datetime import datetime, timezone
    (root / f'posts/{date}.html').write_text(html, encoding='utf-8')
    rec = {'section': 'us', 'date': date, 'request_id': f'us-{date}-0123456789ab', 'state': 'reviewed',
           'style_rejected': 0, 'skeleton_rejected': 0, 'checker_rejected': 0, 'style_findings': [],
           'clarity': clarity, 'clarity_meta': {'marker': True, 'lines_skipped': 0, 'over_cap': 0},
           'recorded_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    rec.update(extra)
    (root / f'reviews/prepublish/us/{date}.json').write_text(json.dumps(rec, ensure_ascii=False), encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', f'Add {date} brief')


def _c(kind, quote, route='style_path', placed='candidate', tell='가'):
    return {'kind': kind, 'quote': quote, 'cannot_tell': tell, 'route': route, 'placed': placed}


def test_whether_a_flagged_phrase_is_still_in_the_published_post(tmp_path):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 결과가 갈릴 발표를 앞두고 올랐다. S&amp;P <b>500</b>은 원판정으로 내렸다.</p>',
             [_c('용어', '이분 사건을 앞둔 노출 축소'), _c('용어', 'S&P 500은 원판정으로'),
              _c('용어', ''), _c('문장 구조', '금은 결과가', route='record_only', placed='')])
    rows = d.collect_clarity(str(root), d._since('7d'))
    got = [d.residual(r, d.publish_text(str(root), r)) for r in rows]
    assert got == ['없음', '남아 있음', '알 수 없음', '남아 있음']


def test_the_digest_names_it_residue_and_never_a_completed_fix(tmp_path, capsys):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')],
             style_rejected=1, checker_rejected=1)
    assert d.main(['--root', str(root)]) == 0
    out = capsys.readouterr().out
    assert '지적 표현의 발행본 잔존 여부' in out
    assert '수정 완료' not in out and '고쳐졌' not in out
    assert '그날 집계' in out and '의미 검사 기각 1' in out


def test_the_first_publish_is_compared_not_a_later_correction(tmp_path):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 이분 사건을 앞둔 노출 축소 흐름에 올랐다.</p>',
             [_c('용어', '이분 사건을 앞둔 노출 축소')])
    (root / 'posts/2026-11-20.html').write_text('<p>금은 올랐다.</p>', encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', 'review: 정정')
    _git(root, 'rm', '-q', 'posts/2026-11-20.html')
    _git(root, 'commit', '-q', '-m', 'remove')
    (root / 'posts').mkdir(exist_ok=True)
    (root / 'posts/2026-11-20.html').write_text('<p>금은 올랐다.</p>', encoding='utf-8')
    _git(root, 'add', '-A')
    _git(root, 'commit', '-q', '-m', 're-add')            # 다시 올린 커밋이 아니라 처음 올린 커밋을 본다
    row = d.collect_clarity(str(root), d._since('7d'))[0]
    assert d.residual(row, d.publish_text(str(root), row)) == '남아 있음'


def test_a_post_that_cannot_be_read_is_reported_as_unknown(tmp_path):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>x</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')])
    row = dict(d.collect_clarity(str(root), d._since('7d'))[0], date='2026-11-21')
    assert d.publish_text(str(root), row) is None
    assert d.residual(row, None) == '알 수 없음'


def test_the_digest_writes_nothing_and_fetches_nothing_unless_asked(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')])

    def never(*a, **k):
        raise AssertionError('비공개 원문은 --private 일 때만 읽는다')
    monkeypatch.setattr(d, 'fetch_review', never)
    before = sorted(str(p) for p in root.rglob('*') if '.git' not in p.parts)
    status = subprocess.run(['git', '-C', str(root), 'status', '--porcelain'], capture_output=True, text=True).stdout
    assert d.main(['--root', str(root)]) == 0
    assert sorted(str(p) for p in root.rglob('*') if '.git' not in p.parts) == before
    assert subprocess.run(['git', '-C', str(root), 'status', '--porcelain'],
                          capture_output=True, text=True).stdout == status


def test_private_reasons_go_to_the_screen_only(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>',
             [_c('용어', '이분 사건을 앞둔 노출 축소'), _c('용어', '원판정')])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: (
        '사실 지적.\n=== 문체 지적 ===\n- [용어] 「이분 사건을 앞둔 노출 축소」 — (가) 사건이 무엇인지 모른다 / 풀어 쓴다\n'
        if rid == 'us-2026-11-20-0123456789ab' else None))
    before = sorted(str(p) for p in root.rglob('*') if '.git' not in p.parts)
    assert d.main(['--root', str(root), '--private']) == 0
    out = capsys.readouterr().out
    assert '사건이 무엇인지 모른다' in out
    assert '원문에서 이유를 찾지 못한 지적 1건' in out
    assert sorted(str(p) for p in root.rglob('*') if '.git' not in p.parts) == before


def test_a_missing_private_review_is_counted_not_hidden(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: None)
    assert d.main(['--root', str(root), '--private']) == 0
    assert '원문 없음 1일' in capsys.readouterr().out


def test_recurrence_is_counted_in_published_posts_not_in_findings(tmp_path, capsys):
    root = _repo(tmp_path)
    _publish(root, '2026-11-19', '<p>원판정이 나왔다.</p>', [])
    _publish(root, '2026-11-20', '<p>원판정이 또 나왔다.</p>', [])          # 검토자는 짚지 않았지만 글에는 있다
    _publish(root, '2026-11-21', '<p>처음으로 약세 조건에 들었다.</p>', [])
    pat = tmp_path / 'clarity-patterns.json'
    pat.write_text(json.dumps([{'name': '판정 이름을 그대로', 'words': ['원판정', '판단 방향'],
                                'fixed_on': '2026-11-19'}], ensure_ascii=False), encoding='utf-8')
    assert d.main(['--root', str(root), '--patterns', str(pat)]) == 0
    out = capsys.readouterr().out
    assert '판정 이름을 그대로' in out and '고친 날(2026-11-19) 뒤 발행본 2편 중 1편' in out


def test_the_patterns_file_must_live_outside_the_public_repo(tmp_path, capsys):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>x</p>', [])
    inside = root / 'clarity-patterns.json'
    inside.write_text('[]', encoding='utf-8')
    assert d.main(['--root', str(root), '--patterns', str(inside)]) == 2
    assert '공개 저장소 밖' in capsys.readouterr().out


def test_empty_quotes_and_broken_answers_are_shown_next_to_the_counts(tmp_path, capsys):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>x</p>', [_c('용어', '')],
             clarity_meta={'marker': False, 'lines_skipped': 3, 'over_cap': 0})
    assert d.main(['--root', str(root)]) == 0
    out = capsys.readouterr().out
    assert '인용이 빈 지적 1건' in out and '표식 없는 답 1일' in out and '읽히지 않은 줄 3' in out


def test_a_private_reason_is_found_even_when_the_reviewer_put_the_mark_inside_the_quote(tmp_path, capsys, monkeypatch):
    """발행 전 읽기는 「(나) …」의 표식을 인용에서 뗀다 — 원문에서 이유를 찾을 때도 같게 뗀다(codex 구현 검토 1회차)."""
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소', tell='나')])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: (
        '=== 문체 지적 ===\n- [용어] 「(나) 이분 사건을 앞둔 노출 축소」 — 무엇을 줄였는지 모른다 / 풀어 쓴다\n'))
    assert d.main(['--root', str(root), '--private']) == 0
    out = capsys.readouterr().out
    assert '무엇을 줄였는지 모른다' in out and '원문에서 이유를 찾지 못한 지적 0건' in out


def test_the_patterns_file_is_refused_anywhere_inside_the_repository(tmp_path, capsys):
    """`--root` 가 저장소의 하위 폴더여도 저장소 안의 꼴 목록은 받지 않는다(codex 구현 검토 1회차)."""
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>x</p>', [])
    (root / 'scripts').mkdir()
    inside = root / 'clarity-patterns.json'
    inside.write_text('[]', encoding='utf-8')
    assert d.main(['--root', str(root / 'scripts'), '--patterns', str(inside)]) == 2
    assert '공개 저장소 밖' in capsys.readouterr().out


def test_a_private_reason_is_matched_by_kind_as_well_as_quote(tmp_path, capsys, monkeypatch):
    """같은 대목을 두 분류가 짚었을 때 다른 분류의 이유를 붙이지 않는다(codex 구현 검토 2회차)."""
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: (
        '=== 문체 지적 ===\n'
        '- [번역투] 「(나) 이분 사건을 앞둔 노출 축소」 — 번역투 이유다 / x\n'
        '- [용어] 「이분 사건을 앞둔 노출 축소」 — 용어 이유다 / y\n'))
    assert d.main(['--root', str(root), '--private']) == 0
    out = capsys.readouterr().out
    assert '용어 이유다' in out and '번역투 이유다' not in out


def test_an_exact_private_quote_wins_over_a_mark_stripped_one(tmp_path, capsys, monkeypatch):
    root = _repo(tmp_path)
    _publish(root, '2026-11-20', '<p>금은 올랐다.</p>', [_c('용어', '이분 사건을 앞둔 노출 축소')])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: (
        '=== 문체 지적 ===\n'
        '- [용어] 「(나) 이분 사건을 앞둔 노출 축소」 — 표식이 안에 든 줄 / x\n'
        '- [용어] 「이분 사건을 앞둔 노출 축소」 — 글자 그대로인 줄 / y\n'))
    assert d.main(['--root', str(root), '--private']) == 0
    out = capsys.readouterr().out
    assert '글자 그대로인 줄' in out and '표식이 안에 든 줄' not in out


def test_a_private_reason_is_not_guessed_when_two_lines_share_the_recorded_quote(tmp_path, capsys, monkeypatch):
    """공개 인용은 앞 40자다 — 원문에 그 40자가 같은 지적이 둘이면 어느 이유인지 짐작하지 않는다(codex 구현 검토 3회차)."""
    root = _repo(tmp_path)
    q = '가' * 40
    _publish(root, '2026-11-20', '<p>x</p>', [_c('용어', q)])
    monkeypatch.setattr(d, 'fetch_review', lambda rid: (
        '=== 문체 지적 ===\n'
        f'- [용어] 「{q}나」 — 첫째 이유 / x\n'
        f'- [용어] 「{q}」 — 둘째 이유 / y\n'))
    assert d.main(['--root', str(root), '--private']) == 0
    out = capsys.readouterr().out
    assert '첫째 이유' not in out and '둘째 이유' not in out
    assert '원문에서 이유를 찾지 못한 지적 1건' in out
