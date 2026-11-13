"""scripts/tg_news.py — the Telegram snapshot a news post may use, and the section stripper (2026-11-12).
Design: docs/superpowers/specs/2026-11-12-telegram-news-posts.md"""
import json
import os
import subprocess as sp

import pytest

import tg_news as T

DAY = '2026-11-11'
GOOD = '알파벳이 홍콩 달러 채권 발행을 검토 중이라는 소식이 전해졌다. 조달 자금은 데이터센터 증설에 쓰일 것이라는 시각이 제시됐다.'


def item(i, kind='opinion', group='individual', source=None, summary=GOOD, **kw):
    ch = {'individual': 'd_ticker', 'relay': 'FastStockNewsUSA', 'firm': 'kwusa'}[group]
    return dict({'id': f'{ch}/{i}', 'channel': ch, 'group': group, 'kind': kind, 'firm': None, 'analyst': None,
                 'source': source, 'summary_ko': summary}, **kw)


ITEMS = [
    item(1),                                                                         # usable
    item(2),                                                                         # cited by the brief
    item(3, summary=None, summary_note='분량 벗어남 500자'),                           # no summary
    item(4, summary='죄송하지만 링크만으로는 내용을 확인할 수 없어 요약을 드릴 수 없습니다.'),  # junk (refusal)
    item(5, summary='수출단가가 64.0% 올랐다는 점이 함께 제시됐습니다.'),                # junk (polite)
    item(6, group='relay'),                                                          # relay, no outlet: usable (2026-11-12 — 개수·종류를 한정하지 않는다)
    item(7, group='relay', source={'name': '로이터', 'url': None, 'basis': 'credit'}),  # credited relay: usable
    item(8, summary='젠슨 황 CEO가 임원과 외도 관계를 맺어 왔다는 의혹이 제기됐다는 소식이다.'),  # unsourced allegation
    item(9, source={'name': '뉴욕타임스', 'url': None, 'basis': 'paywalled_link'},
         summary='젠슨 황 CEO의 의혹을 뉴욕타임스가 보도했다는 소식이 전해졌다.'),      # sourced: usable
    item(10, kind='report', group='relay', source={'name': 'CNBC', 'url': 'https://www.cnbc.com/2026/11/11/a.html?utm_source=x', 'basis': 'link'}),
    item(11, kind='report', group='relay', source={'name': '로이터', 'url': 'https://www.reuters.com/markets/b', 'basis': 'link'}),
    item(12, kind='view', group='firm', firm='키움증권', analyst='김승혁'),             # view: usable (source None is normal)
    item(13, summary='경기소비재 업종이 강했고 이외도 반도체가 올랐다는 시각이 제시됐다.'),  # 「기소」「외도」 inside other words
    item(14, group='relay', summary='젠슨 황 CEO가 혼외 관계를 맺었다고 한 매체가 보도했다는 소식이다.'),  # relay, no outlet, allegation
    item(15, kind='report', group='relay', source={'name': None, 'url': 'https://n.news.naver.com/article/001/0012345678', 'basis': 'link'}),
    item(16, kind='report', group='relay', source={'name': None, 'url': 'https://n.news.naver.com/article/001/0012345679', 'basis': 'link'},
         summary='대표의 횡령 의혹이 제기됐다는 소식이 전해졌다.'),
    item(17, kind='view', group='firm', firm='키움증권', analyst='한지영', summary='필자는 CEO 스캔들이 주가에 미치는 영향이 제한적이라고 진단했다.'),
    item(18, group='firm', firm='키움증권', summary='담당자는 횡령 의혹이 실적에 미칠 영향을 따져 봐야 한다는 의견을 냈다.'),  # a firm stands behind it, whatever the kind
]
WANT = {1: None, 2: 'cited', 3: 'no_summary', 4: 'junk', 5: 'junk', 6: None, 7: None,
        8: 'unsourced_allegation', 9: None, 10: 'dup_url', 11: None, 12: None, 13: None, 14: 'unsourced_allegation',
        15: 'no_outlet', 16: 'unsourced_allegation', 17: None, 18: None}
NEWS = {'items': [{'guid': 'https://www.cnbc.com/2026/11/11/a.html', 'url': 'https://www.cnbc.com/2026/11/11/a.html', 'summary_ko': 'x'}]}
BRIEF = '<html><body><p><span data-tg="d_ticker/2">시장 일각에서는 채권 발행 검토라는 의견도 나왔다.</span></p></body></html>'


def git(repo, *a):
    return sp.run(['git', *a], cwd=repo, check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    (r / 'data/telegram').mkdir(parents=True)
    (r / 'posts').mkdir()
    git(r, 'init', '-q'); git(r, 'config', 'user.email', 't@t'); git(r, 'config', 'user.name', 't')
    (r / 'data/telegram' / f'{DAY}.json').write_text(json.dumps({'report_date': DAY, 'market': 'us', 'items': ITEMS}, ensure_ascii=False), encoding='utf-8')
    git(r, 'add', '-A'); git(r, 'commit', '-qm', 'data')
    (r / 'posts' / f'{DAY}.html').write_text(BRIEF, encoding='utf-8')
    git(r, 'add', '-A'); git(r, 'commit', '-qm', 'Add brief')
    # after publication: a re-collection rewrites the file, and a correction edits the brief
    (r / 'data/telegram' / f'{DAY}.json').write_text(json.dumps({'report_date': DAY, 'items': []}), encoding='utf-8')
    (r / 'posts' / f'{DAY}.html').write_text('<html>정정</html>', encoding='utf-8')
    git(r, 'add', '-A'); git(r, 'commit', '-qm', 're-collect')
    return r


def run(repo, tmp_path, news=NEWS, market='us', day=DAY, capsys=None):
    npath = tmp_path / 'news.json'
    if news is not None:
        npath.write_text(news if isinstance(news, str) else json.dumps(news), encoding='utf-8')
    out = tmp_path / 'out' / 'telegram_news.json'
    rc = T.main(['input', '--market', market, '--date', day, '--repo', str(repo), '--ref', 'HEAD',
                 '--news', str(npath), '--out', str(out)])
    return rc, out


def test_input_marks_every_item_from_the_brief_publish_commit(repo, tmp_path, capsys):
    rc, out = run(repo, tmp_path)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    assert rc == 0 and out.exists()
    d = json.loads(out.read_text(encoding='utf-8'))
    assert d['report_date'] == DAY and len(d['items']) == len(ITEMS)          # nothing is removed
    got = {int(it['id'].split('/')[1]): it.get('news_skip') for it in d['items']}
    assert got == WANT
    assert all(it['news_use'] is (it.get('news_skip') is None) for it in d['items'])
    assert d['news_input']['brief_commit'] == git(repo, 'rev-parse', 'HEAD~1').stdout.strip()
    assert d['news_input']['counts'] == {'cited': 1, 'no_summary': 1, 'junk': 2, 'unsourced_allegation': 3, 'no_outlet': 1, 'dup_url': 1}
    assert line.startswith('tg-news: 쓸 수 있는 9건 / 전체 18건') and 'cited 1' in line


def test_missing_news_file_proceeds_without_dup_check_and_says_so(repo, tmp_path, capsys):
    rc, out = run(repo, tmp_path, news=None)
    line = capsys.readouterr().out.strip().splitlines()[-1]
    d = json.loads(out.read_text(encoding='utf-8'))
    assert rc == 0 and 'news: 없음' in line
    assert next(it for it in d['items'] if it['id'].endswith('/10'))['news_use'] is True


def test_broken_news_file_is_an_error_and_leaves_no_output(repo, tmp_path, capsys):
    rc, out = run(repo, tmp_path, news='{not json')
    assert rc == 0 and not out.exists()
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith('tg-news: error 뉴스 파일')


def test_news_argument_is_required(repo, tmp_path):
    with pytest.raises(SystemExit):
        T.main(['input', '--market', 'us', '--date', DAY, '--repo', str(repo), '--out', str(tmp_path / 'o.json')])


@pytest.mark.parametrize('case,needle', [('no-brief', 'none(브리프 없음'), ('bad-ref', 'error'), ('other-date', 'none(')])
def test_failure_removes_a_stale_output_file(repo, tmp_path, capsys, case, needle):
    """codex 설계 검토 1회 #2: 한 번 성공한 뒤 실패하면 옛 파일이 남아 그대로 쓰였다."""
    rc, out = run(repo, tmp_path)
    assert out.exists()
    capsys.readouterr()
    npath = tmp_path / 'news.json'
    if case == 'no-brief':
        argv = ['input', '--market', 'us', '--date', '2026-11-12', '--repo', str(repo), '--ref', 'HEAD']
    elif case == 'bad-ref':
        argv = ['input', '--market', 'us', '--date', DAY, '--repo', str(repo), '--ref', 'no-such-ref']
    else:
        (repo / 'data/telegram/2026-11-10.json').write_text(json.dumps({'report_date': '2026-11-09', 'items': ITEMS}), encoding='utf-8')
        (repo / 'posts/2026-11-10.html').write_text(BRIEF, encoding='utf-8')
        git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'Add brief 11-10')
        argv = ['input', '--market', 'us', '--date', '2026-11-10', '--repo', str(repo), '--ref', 'HEAD']
    assert T.main(argv + ['--news', str(npath), '--out', str(out)]) == 0
    assert not out.exists() and not os.path.exists(str(out) + '.tmp')
    assert needle in capsys.readouterr().out.strip().splitlines()[-1]


def test_an_old_output_that_cannot_be_removed_is_reported_and_exits_1(repo, tmp_path, capsys, monkeypatch):
    """codex 구현 검토 1회 #4: 삭제가 실패하면 옛 파일이 남는데 종료 코드 0 이면 그 파일이 그대로 쓰인다."""
    rc, out = run(repo, tmp_path)
    assert rc == 0 and out.exists()
    capsys.readouterr()
    real = T.os.remove

    def deny(p):
        if str(p) == str(out):
            raise PermissionError(13, 'denied')
        return real(p)
    monkeypatch.setattr(T.os, 'remove', deny)
    rc = T.main(['input', '--market', 'us', '--date', DAY, '--repo', str(repo), '--ref', 'HEAD',
                 '--news', str(tmp_path / 'news.json'), '--out', str(out)])
    assert rc == 1
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith('tg-news: error 옛 출력 파일')


def test_commit_without_a_telegram_file_is_none(repo, tmp_path, capsys):
    (repo / 'posts/2026-11-12.html').write_text(BRIEF, encoding='utf-8')
    git(repo, 'add', '-A'); git(repo, 'commit', '-qm', 'Add brief 11-12')
    rc, out = run(repo, tmp_path, day='2026-11-12')
    assert rc == 0 and not out.exists()
    assert '텔레그램 파일 없음' in capsys.readouterr().out


def test_kr_paths_and_naver_guid_duplicate(tmp_path, capsys):
    """codex 설계 검토 1회 #10: KR 기사는 URL 없이 guid 만 있을 수 있다 — tg_links.pool_key 로 맞춘다."""
    r = tmp_path / 'repo'
    (r / 'kr/data/telegram').mkdir(parents=True); (r / 'kr/posts').mkdir(parents=True)
    git(r, 'init', '-q'); git(r, 'config', 'user.email', 't@t'); git(r, 'config', 'user.name', 't')
    items = [item(1, kind='report', group='relay',
                  source={'name': '서울경제', 'url': 'https://n.news.naver.com/article/011/0004500001?sid=101', 'basis': 'link'}),
             item(2, kind='report', group='relay',
                  source={'name': '이데일리', 'url': 'https://n.news.naver.com/mnews/article/018/0006000002', 'basis': 'link'})]
    (r / 'kr/data/telegram' / f'{DAY}.json').write_text(json.dumps({'report_date': DAY, 'items': items}, ensure_ascii=False), encoding='utf-8')
    (r / 'kr/posts' / f'{DAY}.html').write_text('<html></html>', encoding='utf-8')
    git(r, 'add', '-A'); git(r, 'commit', '-qm', 'Add KR brief')
    rc, out = run(r, tmp_path, news={'items': [{'guid': '011-0004500001', 'summary_ko': 'x'}]}, market='kr')
    d = json.loads(out.read_text(encoding='utf-8'))
    assert [it.get('news_skip') for it in d['items']] == ['dup_url', None]


# ── strip ────────────────────────────────────────────────────────────────

SECTION = ('<section data-tg-section id="read-2"><h2>증권사 견해·시장 의견</h2><div class="card">'
           '<p><span data-tg="d_ticker/1">시장 일각에서는 채권 발행 검토라는 의견도 나왔다.</span></p></div></section>')


def test_strip_removes_the_section_and_nothing_else_and_is_idempotent(tmp_path, capsys):
    before = '<main><section id="read-1"><h2>오늘의 뉴스</h2></section>\n<!--contested-pending-->\n'
    after = '\n<section id="read-3"><h2>메모리/DRAM</h2><section>안쪽</section></section></main>'
    p = tmp_path / 'n.html'
    p.write_text(before + SECTION + after, encoding='utf-8')
    assert T.main(['strip', '--html', str(p)]) == 0
    want = before + after[1:]                 # the section's own line goes with it
    assert p.read_text(encoding='utf-8') == want
    assert 'strip: 1' in capsys.readouterr().out
    assert T.main(['strip', '--html', str(p)]) == 0
    assert p.read_text(encoding='utf-8') == want
    assert 'strip: 0' in capsys.readouterr().out


def test_brief_publish_commit_is_shared_with_routine_due(repo, monkeypatch):
    from ci import routine_due as rd
    monkeypatch.chdir(repo)
    assert rd.brief_publish_commit(f'posts/{DAY}.html', ref='HEAD') == git(repo, 'rev-parse', 'HEAD~1').stdout.strip()
    assert rd.brief_publish_commit('posts/2026-01-01.html', ref='HEAD') is None
    with pytest.raises(rd.GitLookupError):
        rd.brief_publish_commit(f'posts/{DAY}.html', ref='no-such-ref')


def test_strip_also_removes_the_reading_map_link_to_the_section(tmp_path):
    """조판기가 섹션에 id 를 달고 「빠른 이동」에 링크를 넣는다 — 섹션만 빼면 그 링크가 죽는다."""
    nav = ('<nav class="reading-map"><span class="reading-map-label">빠른 이동</span><a href="#read-1">뉴스</a>'
           '<a href="#read-2">증권사 견해·시장 의견</a><a href="#read-3">AI 인프라</a></nav>\n')
    sec = SECTION.replace('id="read-2"', 'id="read-2"')
    rest = '<section id="read-3"><h2>AI 인프라</h2></section>'
    p = tmp_path / 'n.html'
    p.write_text(nav + '<section id="read-1"><h2>오늘의 뉴스</h2></section>\n' + sec + '\n' + rest, encoding='utf-8')
    assert T.main(['strip', '--html', str(p)]) == 0
    out = p.read_text(encoding='utf-8')
    assert '#read-2' not in out and 'data-tg' not in out
    assert '<a href="#read-1">뉴스</a><a href="#read-3">AI 인프라</a>' in out and rest in out
