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
        {'events': {'MU': [{'confirmed': True}]}, 'triggers': {'MU': []}},
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
        {'events': {'MU': [{'confirmed': True}]}, 'triggers': {'MU': []}},
    )

    assert findings == []
