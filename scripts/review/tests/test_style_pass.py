"""발행 뒤 codex 문체 수정 — 루틴 STEP 2.5 를 대신한다 (2026-09-27).

codex 는 `prose_in.txt` 만 고치고, 되꽂기·게이트·커밋·푸시는 Python 이 한다. 여기서
잡는 것은 그 경계다: 되꽂기가 거부한 편집은 안 나간다, 원본에서 이미 실패하던 게이트는
출력이 같을 때만 봐준다, 지적 없음은 계약 줄이 있을 때만 원장에 남긴다, 공개판이 움직였으면
아무것도 안 민다.
"""
import json
import os
import subprocess
import sys

import pytest

import review_gate as g
from review import style_pass as sp
from review.queue import Pending

POST = 'posts/2026-09-21.html'
DATA = 'data/market_data.json'


def page(sentence):
    return ('<!DOCTYPE html><html><head><title>t</title></head><body data-register="da">'
            '<div class="card"><p>' + sentence + '</p>'
            '<p>S&amp;P 500 은 0.4% 올랐다.</p></div></body></html>')


ORIG = page('유가가 올랐고 그래서 에너지 업종이 강세를 보인 것으로 나타났다.')


def git(repo, *args):
    return subprocess.run(['git', '-C', repo, *args], check=True,
                          capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    origin = str(tmp_path / 'origin.git')
    root = str(tmp_path / 'work')
    subprocess.run(['git', 'init', '-q', '--bare', '-b', 'main', origin], check=True)
    subprocess.run(['git', 'clone', '-q', origin, root], check=True, capture_output=True)
    git(root, 'config', 'user.email', 't@t')
    git(root, 'config', 'user.name', 't')
    commit(root, {POST: ORIG, DATA: '{"report_date": "2026-09-21"}',
                  'reviews/index.json': '{"reviewed": {}}\n',
                  'scripts/review_gate.py': open(g.__file__, encoding='utf-8').read()},
           'publish')
    return root


def commit(repo, files, message):
    for rel, text in files.items():
        path = os.path.join(repo, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(text)
        git(repo, 'add', rel)
    git(repo, 'commit', '-q', '-m', message)
    git(repo, 'push', '-q', 'origin', 'HEAD:main')
    git(repo, 'fetch', '-q', 'origin')
    return git(repo, 'rev-parse', 'HEAD')


def blob(repo, ref='origin/main'):
    return git(repo, 'rev-parse', f'{ref}:{POST}')


def item(repo):
    return Pending(path=POST, section='us', sha=blob(repo), reason='신규')


def prepared(tmp_path, html):
    work = tmp_path / 'snap'
    work.mkdir(exist_ok=True)
    text = sp.prepare(str(work), html)
    return work, text


# ── 게이트 판정 ───────────────────────────────────────────────────────────────

def test_a_gate_that_starts_failing_after_the_edit_rejects_it():
    base = {'check_style.py': (0, 'ok')}
    after = {'check_style.py': (1, '문장 길이')}
    assert sp.judge(base, after)


def test_a_gate_already_failing_with_the_same_output_is_tolerated():
    base = {'check_weight.py': (1, 'lede 순서')}
    assert sp.judge(base, dict(base)) == []


def test_a_gate_already_failing_for_a_new_reason_rejects_the_edit():
    base = {'check_weight.py': (1, 'lede 순서')}
    after = {'check_weight.py': (1, 'lede 순서\n새 위반')}
    assert sp.judge(base, after)


def test_us_gate_list_matches_step_2_5():
    names = [c[1].rsplit('/', 1)[-1] for c in
             sp.gate_commands('us', '/c/p.html', '/e/data', '/o.html', '2026-09-21', 'us-c', '/e/r')]
    for want in ('check_style.py', 'check_readability.py', 'verify_post.py', 'check_macro.py',
                 'check_price_context.py', 'check_session.py', 'check_weight.py',
                 'check_research.py', 'check_fed.py', 'check_sources.py',
                 'check_calendar.py', 'check_movers.py'):
        assert want in names


def test_kr_gate_list_matches_step_2_5():
    names = [c[1].rsplit('/', 1)[-1] for c in
             sp.gate_commands('kr', '/c/p.html', '/e/kr/data', '/o.html', '2026-09-21', 'kr-c', '/e/r')]
    for want in ('check_style.py', 'check_readability.py', 'check_session.py',
                 'check_weight.py', 'check_kr_stance.py', 'check_news.py',
                 'check_movers.py', 'check_research.py', 'verify_post.py'):
        assert want in names


def test_research_gate_is_skipped_only_without_a_cycle_or_a_ledger():
    for cycle, root in ((None, '/e/r'), ('us-c', None)):
        names = [c[1].rsplit('/', 1)[-1] for c in
                 sp.gate_commands('us', '/c/p.html', '/e/data', '/o.html', '2026-09-21', cycle, root)]
        assert 'check_research.py' not in names


def test_research_gate_reads_the_ledger_as_of_publishing():
    cmd = [c for c in sp.gate_commands('us', 'p', 'd', 'o', '2026-09-21', 'us-c', '/e/research/us')
           if c[1].endswith('check_research.py')][0]
    assert cmd[cmd.index('--root') + 1] == '/e/research/us'


def test_every_gate_script_exists():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__)))))
    for section in ('us', 'kr'):
        for cmd in sp.gate_commands(section, 'p', 'd', 'o', '2026-09-21', 'c', 'r'):
            assert os.path.isfile(os.path.join(root, 'scripts', cmd[1].rsplit('/', 1)[-1]))


# ── 커밋 식별 ─────────────────────────────────────────────────────────────────

def test_style_commit_is_named_by_its_trailer():
    assert sp.is_style_commit('문체: codex 윤문 — x\n\nStyle-Pass: codex abc1234\n')
    assert not sp.is_style_commit('문체: codex 윤문 — x\n')


def test_same_skeleton_allows_words_but_not_numbers_or_tags():
    assert sp.same_skeleton(ORIG, page('유가가 올라 에너지 업종이 강했다.'))
    assert not sp.same_skeleton(ORIG, page('유가가 1% 올랐다.'))
    assert not sp.same_skeleton(ORIG, ORIG.replace('<p>', '<p><b>x</b>', 1))


# ── 적용 (임시 레포에서 실제 git) ─────────────────────────────────────────────

def no_gates(*_a, **_k):
    return []


def edit_payload(text, old, new):
    assert old in text
    return text.replace(old, new)


def test_accepted_edit_is_committed_with_the_trailer_and_pushed(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    work, text = prepared(tmp_path, ORIG)
    payload = edit_payload(text, '올랐고 그래서 에너지 업종이 강세를 보인 것으로 나타났다',
                           '올랐고 그래서 에너지 업종이 강세를 보였다')
    it = item(repo)
    res = sp.apply(repo, it, payload, str(work), str(tmp_path / 'ev'))
    assert res.reason is None, res.reason
    git(repo, 'fetch', '-q', 'origin')
    assert res.sha == blob(repo) != it.sha
    assert sp.is_style_commit(git(repo, 'log', '-1', '--format=%B', 'origin/main'))
    assert '강세를 보였다' in git(repo, 'show', f'origin/main:{POST}')
    # 원장은 건드리지 않는다 — 「지적 없음」도 Claude 가 확인한 뒤 기록한다.
    assert json.loads(git(repo, 'show', 'origin/main:reviews/index.json')) == {'reviewed': {}}


def test_rejected_payload_pushes_nothing(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    work, text = prepared(tmp_path, ORIG)
    payload = edit_payload(text, '0.4%', '0.5%')
    before = git(repo, 'rev-parse', 'origin/main')
    res = sp.apply(repo, item(repo), payload, str(work), str(tmp_path / 'ev'))
    assert res.sha is None and res.reason.startswith(sp.UNCHANGED) and '수치' in res.reason
    git(repo, 'fetch', '-q', 'origin')
    assert git(repo, 'rev-parse', 'origin/main') == before


def test_unchanged_payload_pushes_nothing(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    work, text = prepared(tmp_path, ORIG)
    res = sp.apply(repo, item(repo), text, str(work), str(tmp_path / 'ev'))
    assert res.sha is None and res.reason == sp.UNCHANGED


def test_failing_gate_rejects_the_edit(repo, tmp_path, monkeypatch):
    script = tmp_path / 'gate.py'
    script.write_text('import sys\nsys.exit(1 if "보였다" in open(sys.argv[1]).read() else 0)\n')
    monkeypatch.setattr(sp, 'gate_commands',
                        lambda section, post, *a: [[sys.executable, str(script), post]])
    work, text = prepared(tmp_path, ORIG)
    payload = edit_payload(text, '보인 것으로 나타났다', '보였다')
    res = sp.apply(repo, item(repo), payload, str(work), str(tmp_path / 'ev'))
    assert res.sha is None and 'gate.py' in res.reason


def test_post_republished_meanwhile_is_left_alone(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    it = item(repo)
    work, text = prepared(tmp_path, ORIG)
    commit(repo, {POST: page('다른 판이다.')}, 'republish')
    payload = edit_payload(text, '보인 것으로 나타났다', '보였다')
    res = sp.apply(repo, it, payload, str(work), str(tmp_path / 'ev'))
    assert res.sha is None and '바뀌었다' in res.reason


def test_unrelated_push_meanwhile_is_rebased_over(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    it = item(repo)
    work, text = prepared(tmp_path, ORIG)
    real_push = sp._push

    def race(clone, *a, **k):
        other = str(tmp_path / 'other')
        subprocess.run(['git', 'clone', '-q', git(repo, 'remote', 'get-url', 'origin'), other],
                       check=True, capture_output=True)
        git(other, 'config', 'user.email', 't@t')
        git(other, 'config', 'user.name', 't')
        commit(other, {DATA: '{"report_date": "2026-09-22"}'}, 'collect')
        return real_push(clone, *a, **k)
    monkeypatch.setattr(sp, '_push', race)
    payload = edit_payload(text, '보인 것으로 나타났다', '보였다')
    res = sp.apply(repo, it, payload, str(work), str(tmp_path / 'ev'))
    assert res.reason is None
    git(repo, 'fetch', '-q', 'origin')
    assert '보였다' in git(repo, 'show', f'origin/main:{POST}')
    assert '09-22' in git(repo, 'show', f'origin/main:{DATA}')


# ── 근거 찾기: 문체 커밋은 발행 커밋이 아니다 ─────────────────────────────────

def test_publish_commit_walks_back_past_a_style_commit(repo):
    published = git(repo, 'rev-parse', 'HEAD')
    commit(repo, {DATA: '{"report_date": "2026-09-22"}'}, 'collect')
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')},
           f'문체: codex 윤문 — {POST}\n\n{sp.TRAILER} {blob(repo)[:7]}')
    assert g.publish_commit(repo, POST, blob(repo)) == published


def test_a_style_trailer_on_a_number_change_is_not_trusted(repo):
    commit(repo, {POST: page('유가가 1% 올랐다.')},
           f'문체: codex 윤문 — {POST}\n\n{sp.TRAILER} {blob(repo)[:7]}')
    assert g.publish_commit(repo, POST, blob(repo)) == git(repo, 'rev-parse', 'HEAD')


def test_prose_edit_without_the_trailer_is_a_new_publication(repo):
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')}, 'hand edit')
    assert g.publish_commit(repo, POST, blob(repo)) == git(repo, 'rev-parse', 'HEAD')


def test_corrector_accepts_the_style_pass_between_publish_and_review(repo):
    from review import corrector
    published = blob(repo)
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')},
           f'문체: codex 윤문 — {POST}\n\n{sp.TRAILER} {blob(repo)[:7]}')
    assert corrector._typeset_only(repo, POST, published, blob(repo))


def test_corrector_refuses_a_hand_edit_between_publish_and_review(repo):
    from review import corrector
    published = blob(repo)
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')}, 'hand edit')
    assert not corrector._typeset_only(repo, POST, published, blob(repo))


def test_one_failing_paragraph_does_not_sink_the_rest(repo, tmp_path, monkeypatch):
    """2026-09-27 실측: 한 문단이 닮은 정도 0.79 로 걸려 전체가 버려졌다. 이제 그 문단만 원문이다."""
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    work, text = prepared(tmp_path, ORIG)
    payload = (edit_payload(text, '보인 것으로 나타났다', '보였다')
               .replace('0.4% 올랐다', '0.5% 올랐다'))
    res = sp.apply(repo, item(repo), payload, str(work), str(tmp_path / 'ev'))
    assert res.reason is None and res.sha
    git(repo, 'fetch', '-q', 'origin')
    published = git(repo, 'show', f'origin/main:{POST}')
    assert '강세를 보였다' in published and '0.4% 올랐다' in published
    assert [p for p, _ in res.skipped] == ['P002']
    assert 'P002' in git(repo, 'log', '-1', '--format=%B', 'origin/main')


# ── codex 구현 검토(2026-09-30) 반영 ─────────────────────────────────────────

def test_a_forged_sidecar_in_the_workdir_is_not_trusted(repo, tmp_path, monkeypatch):
    """codex 는 작업 폴더에 쓸 수 있다 — 거기 둔 사이드카의 기대값을 고쳐 판단을 뒤집었다."""
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    html = page('경기는 개선 흐름이라고 판단한다.')
    commit(repo, {POST: html}, 'publish 2')
    work, text = prepared(tmp_path, html)
    forged = tmp_path / 'snap' / 'prose_map.json'
    if forged.exists():
        side = json.loads(forged.read_text(encoding='utf-8'))
        for rec in side['items'].values():
            if rec.get('controlled'):
                rec['controlled'] = {'악화': 1}
        forged.write_text(json.dumps(side, ensure_ascii=False), encoding='utf-8')
    res = sp.apply(repo, item(repo), text.replace('개선', '악화'), str(work), str(tmp_path / 'ev'))
    git(repo, 'fetch', '-q', 'origin')
    assert '개선' in git(repo, 'show', f'origin/main:{POST}')
    assert res.sha is None


def test_known_names_come_from_the_evidence_and_the_tables(tmp_path):
    ev = tmp_path / 'ev'
    ev.mkdir()
    (ev / 'kr_top_value.json').write_text(json.dumps(
        [{'label': 'SK하이닉스', 'members': ['SK하이닉스', 'KODEX 반도체']}], ensure_ascii=False),
        encoding='utf-8')
    html = ('<table><tr><th>종목</th><th>등락</th></tr>'
            '<tr><td>삼성전자</td><td>+1.2%</td></tr></table>')
    names = sp.known_names(html, str(ev))
    assert {'SK하이닉스', 'KODEX 반도체', '삼성전자'} <= set(names)
    assert '+1.2%' not in names


def test_a_known_name_swap_is_left_as_written(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    html = page('삼성전자 실적이 시장 기대를 웃돌았다고 판단한다.').replace(
        '</div></body>', '</div><table><tr><td>삼성전자</td><td>1</td></tr></table></body>')
    commit(repo, {POST: html}, 'publish 2')
    work, text = prepared(tmp_path, html)
    res = sp.apply(repo, item(repo), text.replace('삼성전자 실적', '현대전자 실적'),
                   str(work), str(tmp_path / 'ev'))
    assert res.sha is None and [p for p, _ in res.skipped] == ['P001']


def test_style_trailer_must_close_the_message_and_name_the_parent():
    msg = '문체: codex 윤문 — x\n\nStyle-Pass: codex abc1234\n'
    assert sp.is_style_commit(msg, 'abc1234' + '0' * 33)
    assert not sp.is_style_commit(msg, 'fff1234' + '0' * 33)
    assert not sp.is_style_commit('수동 정정\n\nStyle-Pass: codex 가 놓친 문장을 고친다\n')
    assert not sp.is_style_commit('Style-Pass: codex abc1234\n\n수동 정정 본문\n')


def test_publish_commit_does_not_skip_a_trailer_naming_another_blob(repo):
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')},
           f'문체: codex 윤문 — {POST}\n\n{sp.TRAILER} fff0000')
    assert g.publish_commit(repo, POST, blob(repo)) == git(repo, 'rev-parse', 'HEAD')


def test_gates_are_replayed_on_the_rebased_code(repo, tmp_path, monkeypatch):
    """거절 → rebase 사이에 게이트 코드가 바뀌면, 바뀐 코드로 다시 돌려 봐야 한다."""
    gate = 'scripts/gate_x.py'
    commit(repo, {gate: 'import sys\nsys.exit(0)\n'}, 'gate v1')
    monkeypatch.setattr(sp, 'gate_commands',
                        lambda section, post, *a: [[sys.executable, 'scripts/gate_x.py', post]])
    it = item(repo)
    work, text = prepared(tmp_path, ORIG)
    real_push = sp._push

    def race(clone, *a, **k):
        other = str(tmp_path / 'other')
        subprocess.run(['git', 'clone', '-q', git(repo, 'remote', 'get-url', 'origin'), other],
                       check=True, capture_output=True)
        git(other, 'config', 'user.email', 't@t')
        git(other, 'config', 'user.name', 't')
        commit(other, {gate: 'import sys\nsys.exit(1 if "보였다" in open(sys.argv[1]).read() else 0)\n'},
               'gate v2')
        return real_push(clone, *a, **k)
    monkeypatch.setattr(sp, '_push', race)
    before = git(repo, 'ls-remote', 'origin', 'main').split()[0]
    res = sp.apply(repo, it, edit_payload(text, '보인 것으로 나타났다', '보였다'),
                   str(work), str(tmp_path / 'ev'))
    assert res.sha is None and 'gate_x.py' in res.reason
    git(repo, 'fetch', '-q', 'origin')
    assert '보였다' not in git(repo, 'show', f'origin/main:{POST}')
    assert git(repo, 'rev-parse', 'origin/main') != before   # gate v2 만 나갔다


def test_corrector_refuses_a_hand_edit_after_the_style_pass(repo):
    from review import corrector
    published = blob(repo)
    commit(repo, {POST: page('유가가 올라 에너지 업종이 강했다.')},
           f'문체: codex 윤문 — {POST}\n\n{sp.TRAILER} {published[:7]}')
    commit(repo, {POST: page('유가가 올라 에너지 업종이 약했다.')}, 'hand edit')
    assert not corrector._typeset_only(repo, POST, published, blob(repo))


def test_known_names_skip_header_cells_and_single_syllables(tmp_path):
    html = ('<table><tr><th>지수</th><th>등락</th></tr>'
            '<tr><td>나스닥</td><td>+1.2%</td></tr><tr><td>금</td><td>1%</td></tr></table>')
    names = sp.known_names(html, str(tmp_path))
    assert '나스닥' in names and '지수' not in names and '금' not in names


def test_a_generic_word_is_not_protected_as_a_name(repo, tmp_path, monkeypatch):
    """재검토: 표 제목 「지수」가 이름으로 잡혀 「지수는 올랐다→주가는 상승했다」를 거부했다."""
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    html = page('지수는 크게 올랐다고 판단한다. 반도체 업황 회복 기대와 환율 부담이 엇갈린 하루였고 '
                '수급도 종목별로 크게 갈렸다.').replace(
        '</div></body>', '</div><table><tr><th>지수</th></tr><tr><td>나스닥</td></tr></table></body>')
    commit(repo, {POST: html}, 'publish 2')
    work, text = prepared(tmp_path, html)
    res = sp.apply(repo, item(repo), text.replace('지수는 크게 올랐다고', '주가는 크게 상승했다고'),
                   str(work), str(tmp_path / 'ev'))
    assert res.reason is None and res.sha, res.reason


def test_a_changed_gate_list_during_rebase_stops_the_push(repo, tmp_path, monkeypatch):
    """재검토: 거절 → rebase 사이 게이트 목록이 늘면 재검사가 옛 목록만 돌렸다."""
    defs = 'scripts/review/style_pass.py'
    commit(repo, {defs: '# v1\n'}, 'defs v1')
    monkeypatch.setattr(sp, 'gate_commands', no_gates)
    it = item(repo)
    work, text = prepared(tmp_path, ORIG)
    real_push = sp._push

    def race(clone, *a, **k):
        other = str(tmp_path / 'other')
        subprocess.run(['git', 'clone', '-q', git(repo, 'remote', 'get-url', 'origin'), other],
                       check=True, capture_output=True)
        git(other, 'config', 'user.email', 't@t')
        git(other, 'config', 'user.name', 't')
        commit(other, {defs: '# v2 — 새 게이트\n'}, 'defs v2')
        return real_push(clone, *a, **k)
    monkeypatch.setattr(sp, '_push', race)
    res = sp.apply(repo, it, edit_payload(text, '보인 것으로 나타났다', '보였다'),
                   str(work), str(tmp_path / 'ev'))
    assert res.sha is None and '게이트 목록' in res.reason


# ── 주간·월간·일본 (2026-10-01) ───────────────────────────────────────────────

def _gates(section, key):
    return {c[1].rsplit('/', 1)[-1]: c for c in
            sp.gate_commands(section, '/c/p.html', '/ev', '/o.html', key, None, None)}


def test_us_weekly_gates_replay_check_period_on_the_publish_evidence():
    g_ = _gates('weekly', '2026-W39')
    assert {'check_style.py', 'check_readability.py', 'verify_post.py', 'check_period.py'} <= set(g_)
    cmd = g_['check_period.py']
    assert cmd[cmd.index('--agg') + 1] == '/ev/data/weekly/2026-W39.json'
    assert cmd[cmd.index('--recap') + 1] == '/ev/recap_us.json'
    assert cmd[cmd.index('--insight') + 1] == '/ev/data/weekly_ext/2026-W39.insight.json'
    assert cmd[cmd.index('--research-frozen') + 1] == '/o.html'
    assert cmd[cmd.index('--span') + 1] == 'weekly' and cmd[cmd.index('--market') + 1] == 'us'
    assert '--no-inline-images' not in g_['check_readability.py']
    assert 'check_weight.py' not in g_ and 'check_macro.py' not in g_


def test_kr_monthly_gates_have_no_insight():
    cmd = _gates('kr/monthly', '2026-09')['check_period.py']
    assert '--insight' not in cmd
    assert cmd[cmd.index('--agg') + 1] == '/ev/kr/data/monthly/2026-09.json'
    assert cmd[cmd.index('--span') + 1] == 'monthly' and cmd[cmd.index('--market') + 1] == 'kr'


def test_japan_gates_read_the_publish_evidence():
    g_ = _gates('japan/posts', '2026-W40')
    cmd = g_['check_japan.py']
    assert cmd[cmd.index('--key') + 1] == '2026-W40'
    assert cmd[cmd.index('--datadir') + 1] == '/ev/japan/data'
    assert 'check_period.py' not in g_
