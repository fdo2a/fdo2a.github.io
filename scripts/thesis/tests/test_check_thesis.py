import subprocess

from check_thesis import check_page


BASE = '''<article data-ticker="MU" data-grade="홀딩 강화" data-since="2026-08-24">
<span>홀딩 강화 · 등급 유지 2026-08-24부터</span>
<ol data-block="changelog">
  <li data-date="2026-08-24" data-signal="init"><h4>최초 작성</h4></li>
</ol>
<section data-block="thesis">기준표</section>
<section data-block="valuation" data-computed="2026-08-26">밸류 932.97</section>
</article>'''

ENTRY = '''
  <li data-date="2026-08-27" data-signal="홀딩 강화" data-stance="Neutral">
    <h4>President·COO 중심으로 책임 재편</h4>
    <div data-part="fact">8-K로 확인. <cite>Micron 8-K, 2026-08-26</cite></div>
    <div data-part="inference">추론: 실행 속도를 높이려는 재편.</div>
    <div data-part="delta">RPO와 총이익률 논거는 그대로다.</div>
    <div data-part="next">9월 30일 실적을 확인한다.</div>
  </li>'''


def test_confirmed_changelog_does_not_count_as_numeric_drift(tmp_path, monkeypatch):
    """Removing the changelog exemption must make this fail as false numeric drift."""
    repo = tmp_path / 'repo'
    page = repo / 'thesis' / 'micron.html'
    page.parent.mkdir(parents=True)
    page.write_text(BASE, encoding='utf-8')

    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-qm', 'baseline'], cwd=repo, check=True)

    page.write_text(BASE.replace('</ol>', ENTRY + '\n</ol>'), encoding='utf-8')
    monkeypatch.chdir(repo)

    findings = check_page(
        'MU', 'thesis/micron.html',
        {'MU': {'grade': '홀딩 강화'}},
        ['event:Micron 8-K'],
    )

    assert findings == []


def test_grade_transition_date_does_not_count_as_numeric_drift(tmp_path, monkeypatch):
    """A real state transition must not be blocked by its rendered grade-since date."""
    repo = tmp_path / 'repo'
    page = repo / 'thesis' / 'micron.html'
    page.parent.mkdir(parents=True)
    page.write_text(BASE, encoding='utf-8')

    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-qm', 'baseline'], cwd=repo, check=True)

    entry = ENTRY.replace('data-signal="홀딩 강화"', 'data-signal="주의"')
    changed = BASE.replace(
        'data-grade="홀딩 강화" data-since="2026-08-24"',
        'data-grade="주의" data-since="2026-08-28"',
    ).replace(
        '홀딩 강화 · 등급 유지 2026-08-24부터',
        '주의 · 등급 유지 2026-08-28부터',
    ).replace('</ol>', entry + '\n</ol>')
    page.write_text(changed, encoding='utf-8')
    monkeypatch.chdir(repo)

    findings = check_page(
        'MU', 'thesis/micron.html',
        {'MU': {'grade': '주의'}},
        ['event:Micron 8-K'],
    )

    assert findings == []


# ── 근거는 HEAD 의 수집 자료에서 다시 계산한다 (2026-11-23) ──

import json  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

import check_thesis  # noqa: E402
import thesis_evidence as EV  # noqa: E402
from thesis.tests.test_evidence import (  # noqa: E402
    TODAY, days_before, disclosures, filing, history, text, watch_for)

BOT_ENV = {'GIT_AUTHOR_NAME': 'github-actions[bot]', 'GIT_AUTHOR_EMAIL': EV.BOT,
           'GIT_COMMITTER_NAME': 'github-actions[bot]', 'GIT_COMMITTER_EMAIL': EV.BOT}


def _commit(repo, message, env=None):
    subprocess.run(['git', 'add', '-A'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '-qm', message], cwd=repo, check=True,
                   env={**os.environ, **(env or {})})


def write(repo, rel, content):
    path = repo / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else
                    json.dumps(content, ensure_ascii=False), encoding='utf-8')


def make_repo(tmp_path, monkeypatch, rows=None, disc=None, grade='홀딩 강화', bot=True):
    repo = tmp_path / 'repo'
    repo.mkdir()
    subprocess.run(['git', 'init', '-q'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)
    write(repo, 'thesis/micron.html', BASE.replace('홀딩 강화', grade))
    write(repo, check_thesis.STATE,
          {'tickers': {'MU': {'grade': grade, 'grade_since': '2026-08-24'}}})
    _commit(repo, 'pages')
    rows = rows if rows is not None else history(25)
    write(repo, 'thesis/data/history.jsonl', text(rows))
    write(repo, 'thesis/data/watch.json', watch_for(rows))
    write(repo, 'thesis/data/disclosures.json', disc or disclosures([]))
    write(repo, 'thesis/data/events.json', {'items': []})
    _commit(repo, 'thesis watch data', BOT_ENV if bot else None)
    monkeypatch.chdir(repo)
    return repo


def run_gate(monkeypatch, *extra):
    monkeypatch.setattr(sys, 'argv', ['check_thesis.py', 'thesis/micron.html',
                                      '--skip-layout', '--today', TODAY, *extra])
    return check_thesis.main()


def test_quiet_day_passes(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch)
    assert run_gate(monkeypatch) == 0


def test_page_edit_without_licence_or_run_json_is_silence(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, monkeypatch)
    write(repo, 'thesis/micron.html', BASE.replace('</ol>', ENTRY + '\n</ol>'))
    assert run_gate(monkeypatch) == 1
    assert 'silence' in capsys.readouterr().out


def test_numeric_trigger_recomputed_from_head_licenses_the_edit(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch, rows=history(25, cross_on=TODAY))
    write(repo, 'thesis/micron.html', BASE.replace('</ol>', ENTRY + '\n</ol>'))
    assert run_gate(monkeypatch) == 0


def test_event_only_move_helper_and_gate_agree(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, monkeypatch)
    run = repo / 'run.json'
    run.write_text(json.dumps({'events': {'MU': [{
        'title': 'Micron 8-K', 'confirmed': True,
        'source': 'https://www.sec.gov/x'}]}}), encoding='utf-8')
    helper = EV.assess_today(TODAY, str(run))['tickers']['MU']['licences']
    assert helper == ['event:Micron 8-K']
    entry = ENTRY.replace('data-signal="홀딩 강화"', 'data-signal="주의"')
    write(repo, 'thesis/micron.html', BASE.replace(
        'data-grade="홀딩 강화" data-since="2026-08-24"',
        f'data-grade="주의" data-since="{TODAY}"').replace(
        '홀딩 강화 · 등급 유지 2026-08-24부터', f'주의 · 등급 유지 {TODAY}부터').replace(
        '</ol>', entry + '\n</ol>'))
    write(repo, check_thesis.STATE, {'tickers': {'MU': {'grade': '주의', 'grade_since': TODAY}}})
    assert run_gate(monkeypatch, '--triggers', str(run)) == 0
    # the same move two steps at once is not what propose() allows — page and state agree
    # with each other here, so only the grade check can be what blocks
    write(repo, 'thesis/micron.html', (repo / 'thesis/micron.html').read_text(
        encoding='utf-8').replace('주의', '비중 조절 검토'))
    write(repo, check_thesis.STATE,
          {'tickers': {'MU': {'grade': '비중 조절 검토', 'grade_since': TODAY}}})
    capsys.readouterr()
    assert run_gate(monkeypatch, '--triggers', str(run)) == 1
    out = capsys.readouterr().out
    assert 'grade_discipline' in out and 'state_consistency' not in out


def test_gate_hands_the_helpers_T_to_silence_and_to_the_grade_check(tmp_path, monkeypatch):
    """Not just the same exit code: the lists the gate judges with are the helper's lists."""
    repo = make_repo(tmp_path, monkeypatch, rows=history(25, cross_on=TODAY))
    run = repo / 'run.json'
    run.write_text(json.dumps({'events': {'MU': [{
        'title': 'Micron 8-K', 'confirmed': True,
        'source': 'https://www.sec.gov/x'}]}}), encoding='utf-8')
    helper = EV.assess_today(TODAY, str(run))['tickers']
    assert helper['MU']['licences'] == ['bear_proximity', 'event:Micron 8-K']
    seen = {}
    real_silence, real_grades = check_thesis.G.check_silence, check_thesis.G.check_grades

    def silence(triggers, events, page_changed):
        seen['silence'] = list(triggers)
        return real_silence(triggers=triggers, events=events, page_changed=page_changed)

    def grades(base, state, today, tickers):
        seen['grades'] = {s: (t['licences'], t['kill_evidence']) for s, t in tickers.items()}
        return real_grades(base, state, today, tickers)

    monkeypatch.setattr(check_thesis.G, 'check_silence', silence)
    monkeypatch.setattr(check_thesis.G, 'check_grades', grades)
    run_gate(monkeypatch, '--triggers', str(run))
    assert seen['silence'] == helper['MU']['licences']
    assert seen['grades'] == {s: (t['licences'], t['kill_evidence'])
                              for s, t in helper.items()}


def test_routine_edit_of_collector_file_blocks(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, monkeypatch)
    write(repo, 'thesis/data/disclosures.json', disclosures([filing(TODAY)]))
    assert run_gate(monkeypatch) == 1
    assert 'collector_data' in capsys.readouterr().out


def test_non_bot_collector_version_gives_no_evidence(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch, rows=history(40, cross_on=days_before(3)),
              disc=disclosures([filing(days_before(2))]), bot=False)
    mu = EV.assess_today(TODAY)['tickers']['MU']
    assert mu['numeric'] is None and mu['kill_evidence'] == () and mu['filings'] == []


def test_kill_needs_both_axes_from_bot_data(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch, rows=history(40, cross_on=days_before(3)),
                     disc=disclosures([filing(days_before(2))]), grade='비중 조절 검토')
    assert EV.assess_today(TODAY)['tickers']['MU']['kill_evidence'] == ('contract', 'price')
    run = repo / 'run.json'
    run.write_text(json.dumps({'events': {'MU': [{
        'title': '고객 계약 해지 공시', 'confirmed': True,
        'source': 'https://dart.example/1'}]}}), encoding='utf-8')
    write(repo, check_thesis.STATE,
          {'tickers': {'MU': {'grade': 'kill condition', 'grade_since': TODAY}}})
    write(repo, 'thesis/micron.html', BASE.replace('홀딩 강화', '비중 조절 검토').replace(
        'data-grade="비중 조절 검토" data-since="2026-08-24"',
        f'data-grade="kill condition" data-since="{TODAY}"').replace(
        '비중 조절 검토 · 등급 유지 2026-08-24부터', f'kill condition · 등급 유지 {TODAY}부터').replace(
        '</ol>', ENTRY.replace('data-signal="홀딩 강화"', 'data-signal="kill condition"')
        + '\n</ol>'))
    assert run_gate(monkeypatch, '--triggers', str(run)) == 0


def test_kill_with_contract_axis_outside_the_window_is_blocked(tmp_path, monkeypatch, capsys):
    """Price today, contract 31 days ago: the axes are 31 days apart → no kill."""
    repo = make_repo(tmp_path, monkeypatch, rows=history(60, cross_on=TODAY),
                     disc=disclosures([filing(days_before(31))]), grade='비중 조절 검토')
    assert EV.assess_today(TODAY)['tickers']['MU']['kill_evidence'] == ('price',)
    write(repo, check_thesis.STATE,
          {'tickers': {'MU': {'grade': 'kill condition', 'grade_since': TODAY}}})
    assert run_gate(monkeypatch) == 1
    assert 'kill_needs_two_axes' in capsys.readouterr().out


def test_contract_filing_from_an_older_snapshot_still_counts(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch, disc=disclosures([filing(days_before(5))],
                                                              as_of=days_before(5)))
    write(repo, 'thesis/data/disclosures.json', disclosures([]))
    _commit(repo, 'thesis watch data', BOT_ENV)
    assert EV.assess_today(TODAY)['tickers']['MU']['contract_days'] == [days_before(5)]


def test_shallow_boundary_commit_is_not_trusted(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, monkeypatch)
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repo, capture_output=True,
                          text=True).stdout.strip()
    (repo / '.git' / 'shallow').write_text(head + '\n')
    out = EV.assess_today(TODAY)
    assert out['tickers']['MU']['numeric'] is None
    assert any('얕은 복제' in n for n in out['notes'])


def test_unreadable_git_history_falls_back_to_head_snapshot(tmp_path, monkeypatch):
    make_repo(tmp_path, monkeypatch, disc=disclosures([filing(days_before(1))]))
    real = EV._git
    monkeypatch.setattr(EV, '_git', lambda *a: None if any(
        str(x).startswith('--since') for x in a) else real(*a))
    out = EV.assess_today(TODAY)
    assert any('git 기록을 읽지 못했다' in n for n in out['notes'])
    assert out['tickers']['MU']['contract_days'] == [days_before(1)]   # HEAD's own file


def test_unparsable_run_json_blocks(tmp_path, monkeypatch, capsys):
    repo = make_repo(tmp_path, monkeypatch)
    (repo / 'run.json').write_text('{broken', encoding='utf-8')
    assert run_gate(monkeypatch, '--triggers', str(repo / 'run.json')) == 1
    assert 'run.json 을 읽지 못했다' in capsys.readouterr().out
