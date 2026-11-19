"""직전 발행본 요약 — 작성자가 글 전체(60-110 KB) 대신 복기 절만 읽게 한다(2026-11-19 narrow-fix-agent)."""
import glob
import os
import re
import subprocess

import pytest

from common import prev_post as pp

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

POST = '''<!doctype html><html><head><title>t</title><style>p{}</style></head><body>
<h1><tl-s>제목 앞…</tl-s><tl-s>제목 뒤</tl-s></h1>
<section class="card"><h2>전략 코멘트</h2>
<p data-lede="event">사건 문단 4.2%.</p>
<p data-lede="invalidation">철회 조건 5,208.</p>
<aside data-editor-note><p>편집자 개인 의견.</p></aside>
</section>
<section class="card"><h2>매크로</h2><p>길고 긴 본문.</p><table><tr><td>1</td></tr></table></section>
<section class="card" data-learning="daily" data-research-cycle="us-2026-11-17-daily-cycle" id="read-11">
<h2>시장 판단과 복기</h2>
<p data-lede="review">복기 문단.</p>
<p data-hypothesis="h1">질문과 조건, 기한 11월 24일.</p>
</section>
<section id="read-12"><div class="card"><h2>향후 확인 일정</h2><table><tr><td>11월 19일</td></tr></table></div></section>
<p class="disclaimer">면책.</p>
</body></html>'''


def test_pick_takes_the_latest_post_strictly_before_the_date():
    names = ['posts/2026-11-14.html', 'posts/2026-11-17.html', 'posts/2026-11-18.html', 'posts/index.html',
             'kr/posts/2026-11-18.html']
    assert pp.pick(names, 'us', '2026-11-18') == ('posts/2026-11-17.html', '2026-11-17')
    assert pp.pick(names, 'kr', '2026-11-19') == ('kr/posts/2026-11-18.html', '2026-11-18')
    assert pp.pick(names, 'us', '2026-11-14') is None


def test_ok_keeps_learning_block_ledes_title_and_drops_the_rest():
    state, body = pp.digest(POST, 'us')
    assert state == 'ok'
    assert 'data-learning="daily"' in body and '질문과 조건, 기한 11월 24일.' in body
    assert 'data-research-cycle="us-2026-11-17-daily-cycle"' in body
    assert '사건 문단 4.2%.' in body and '철회 조건 5,208.' in body and '제목 뒤' in body
    assert '길고 긴 본문' not in body and '면책' not in body
    assert '편집자 개인 의견' not in body          # learning block only, not the editor's personal note
    assert body.count('복기 문단.') == 1            # 복기 절 안의 lede 를 두 번 싣지 않는다


def test_slices_are_verbatim():
    _, body = pp.digest(POST, 'us')
    start = POST.index('<section class="card" data-learning')
    end = POST.index('</section>', start) + len('</section>')
    assert POST[start:end] in body


def test_kr_adds_the_schedule_section_and_us_does_not():
    assert '향후 확인 일정' in pp.digest(POST, 'kr')[1]
    assert '향후 확인 일정' not in pp.digest(POST, 'us')[1]


def test_editor_note_inside_a_slice_is_removed():
    html = POST.replace('<p data-lede="review">복기 문단.</p>',
                        '<p data-lede="review">복기 문단.</p><div data-editor-note="1"><p>노트</p></div>')
    state, body = pp.digest(html, 'us')
    assert state == 'ok' and '노트' not in body and '질문과 조건' in body


def test_no_learning_block_is_bootstrap():
    html = POST.replace(' data-learning="daily"', '')
    assert pp.digest(html, 'us') == ('bootstrap', '')


def test_unbalanced_learning_block_hands_over_the_whole_post():
    start = POST.index('<section class="card" data-learning')
    end = POST.index('</section>', start)
    html = POST[:end] + POST[end + len('</section>'):]
    state, body = pp.digest(html, 'us')
    assert state == 'full' and body == html


def _git(repo, *args):
    subprocess.run(['git', '-C', repo, '-c', 'user.name=t', '-c', 'user.email=t@t', *args], check=True,
                   capture_output=True)


@pytest.fixture
def repo(tmp_path):
    r = str(tmp_path / 'r')
    os.makedirs(os.path.join(r, 'posts'))
    _git(r, 'init', '-q')
    for d in ('2026-11-14', '2026-11-17'):
        with open(os.path.join(r, 'posts', d + '.html'), 'w', encoding='utf-8') as fh:
            fh.write(POST.replace('11월 24일', d))
    _git(r, 'add', '-A')
    _git(r, 'commit', '-qm', 'x')
    return r


def test_run_reads_committed_bytes_not_the_working_tree(repo, tmp_path):
    with open(os.path.join(repo, 'posts', '2026-11-17.html'), 'w', encoding='utf-8') as fh:
        fh.write(POST.replace('질문과 조건', '발행된 적 없는 조건'))
    with open(os.path.join(repo, 'posts', '2026-11-18.html'), 'w', encoding='utf-8') as fh:
        fh.write(POST)                                       # 커밋 안 된 글은 고르지 않는다
    out = str(tmp_path / 'prev.html')
    code, line = pp.run('us', '2026-11-19', repo, out)
    text = open(out, encoding='utf-8').read()
    assert code == 0 and line.startswith('prev_post: ok posts/2026-11-17.html 2026-11-17 ')
    assert '발행된 적 없는 조건' not in text and '기한 2026-11-17' in text
    commit = subprocess.run(['git', '-C', repo, 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    assert commit in line and commit in text.split('-->')[0] and 'posts/2026-11-17.html' in text.split('-->')[0]


def test_run_bootstrap_when_no_earlier_post(repo, tmp_path):
    out = str(tmp_path / 'prev.html')
    code, line = pp.run('us', '2026-11-14', repo, out)
    assert code == 0 and line.startswith('prev_post: bootstrap')
    assert 'bootstrap' in open(out, encoding='utf-8').read() and '<section' not in open(out, encoding='utf-8').read()


def test_run_error_when_git_fails_and_never_looks_like_bootstrap(tmp_path):
    out = str(tmp_path / 'prev.html')
    code, line = pp.run('us', '2026-11-19', str(tmp_path), out)     # git 레포가 아니다
    assert code == 2 and line.startswith('prev_post: error') and not os.path.exists(out)


def test_stale_out_is_removed_on_error(tmp_path):
    out = str(tmp_path / 'prev.html')
    open(out, 'w').write('옛 요약')
    assert pp.run('us', '2026-11-19', str(tmp_path), out)[0] == 2 and not os.path.exists(out)


@pytest.mark.parametrize('market,pattern', [('us', 'posts/2026-1[01]-*.html'), ('kr', 'kr/posts/2026-1[01]-*.html')])
def test_real_posts_keep_their_learning_block(market, pattern):
    paths = sorted(glob.glob(os.path.join(REPO, pattern)))[-8:]
    assert paths
    for p in paths:
        html = open(p, encoding='utf-8').read()
        state, body = pp.digest(html, market)
        assert state == 'ok', p
        m = re.search(r'<section\b[^>]*\bdata-learning\b', html)
        end = html.index('</section>', m.start()) + len('</section>')
        section = html[m.start():end]
        # 노트는 중첩 없는 요소 하나다 — 그것만 빠지고 나머지는 글자 그대로여야 한다
        expected = re.sub(r'<(\w+)\b[^>]*\sdata-editor-note\b[^>]*>.*?</\1>', '', section, flags=re.S)
        assert expected in body, p
        assert len(body) < len(html) / 2, p
        if market == 'kr' and '<h2>향후 확인 일정</h2>' in html:
            assert '<h2>향후 확인 일정</h2>' in body, p


def test_undecodable_bytes_are_read_with_replacement_not_an_error(tmp_path):
    r = str(tmp_path / 'r')
    os.makedirs(os.path.join(r, 'posts'))
    _git(r, 'init', '-q')
    with open(os.path.join(r, 'posts', '2026-11-17.html'), 'wb') as fh:
        fh.write(POST.replace('질문과 조건', '질문\x00과 조건').encode('utf-8').replace(b'\x00', b'\xff'))
    _git(r, 'add', '-A')
    _git(r, 'commit', '-qm', 'x')
    out = str(tmp_path / 'prev.html')
    code, line = pp.run('us', '2026-11-18', r, out)
    assert code == 0 and line.startswith('prev_post: ok '), line
    assert '질문\ufffd과 조건' in open(out, encoding='utf-8').read()      # 버리지 않고 대체 문자로 남긴다


def test_cli_exit_code_and_last_line(repo, tmp_path, capsys):
    import prev_post_digest
    out = str(tmp_path / 'p.html')
    assert prev_post_digest.main(['--market', 'us', '--date', '2026-11-19', '--repo', repo, '--out', out]) == 0
    assert capsys.readouterr().out.strip().splitlines()[-1].startswith('prev_post: ok posts/2026-11-17.html')
    assert prev_post_digest.main(['--market', 'us', '--date', '2026-11-19', '--repo', str(tmp_path), '--out', out]) == 2
    assert capsys.readouterr().out.strip().startswith('prev_post: error') and not os.path.exists(out)


def test_digest_file_is_ignored_at_the_workspace_root():
    """워크스페이스 루트가 레포 클론일 때 `git add -A` 가 요약 파일을 공개 레포에 올리면 안 된다."""
    lines = open(os.path.join(REPO, '.gitignore'), encoding='utf-8').read().splitlines()
    assert '/prev_post.html' in lines


@pytest.mark.parametrize('doc,market', [('ORCHESTRATOR.md', 'us'), ('KR_ORCHESTRATOR.md', 'kr')])
def test_orchestrators_hand_over_the_digest_and_keep_todays_fallback(doc, market):
    text = open(os.path.join(REPO, '.claude', doc), encoding='utf-8').read()
    line = next(l for l in text.splitlines() if l.startswith('**리서치 인계:**'))
    assert 'scripts/prev_post_digest.py --market %s ' % market in line
    assert '직전 발행본 경로(없으면 bootstrap)' in line and 'exit 0 이 아니면' in line


@pytest.mark.parametrize('agent', ['brief-report-writer', 'kr-report-writer', 'brief-data-collector'])
def test_agents_read_the_digest_and_read_mandate_files_once(agent):
    text = open(os.path.join(REPO, '.claude', 'agents', agent + '.md'), encoding='utf-8').read()
    assert '`prev_post.html`' in text and '그 글 전체를 열지 않는다' in text
    assert 'Read 도구로 파일마다 한 번만 읽는다' in text and '반드시 읽는다' in text


def test_unclosed_learning_section_inside_a_closed_box_is_not_dropped():
    """느슨한 읽기가 안 닫힌 복기 절을 버린 채 ok 를 내면 질문이 사라진다(codex 구현 검토 1회차)."""
    html = ('<div><section data-learning><p>question</p></div>'
            '<section data-learning><p>other</p></section>')
    assert pp.digest(html, 'us') == ('full', html)


def test_unclosed_lede_hands_over_the_whole_post():
    html = POST.replace('<p data-lede="event">사건 문단 4.2%.</p>', '<p data-lede="event">사건 문단 4.2%.')
    assert pp.digest(html, 'us') == ('full', html)


def test_unclosed_title_or_kr_schedule_hands_over_the_whole_post():
    html = POST.replace('제목 뒤</tl-s></h1>', '제목 뒤</tl-s>')
    assert pp.digest(html, 'us')[0] == 'full'
    html = POST.replace('<h2>향후 확인 일정</h2>', '<h2>향후 확인 일정')
    assert pp.digest(html, 'kr') == ('full', html)
    html = POST.replace('<section id="read-12">', '<div>').replace('</div></section>\n<p class="disclaimer">', '</div></div>\n<p class="disclaimer">')
    assert '향후 확인 일정' in html and pp.digest(html, 'kr') == ('full', html)      # 감싼 section 이 없다


def test_self_closing_syntax_on_an_html_element_is_an_open_tag():
    """`<p data-lede/>` 는 HTML 에서 닫히지 않은 p 다 — 조각이 빠진 채 ok 가 되면 안 된다(codex 구현 검토 2회차)."""
    html = '<section data-learning><p>question</p></section><p data-lede/>lost'
    assert pp.digest(html, 'us') == ('full', html)


def test_unclosed_schedule_heading_with_nested_markup_is_full():
    html = ('<section data-learning><p>question</p></section>\n'
            '<section><h2><span>향후 확인 일정</span><p>deadline</p></section>')
    assert pp.digest(html, 'kr') == ('full', html)


def test_schedule_heading_with_inline_markup_is_still_found():
    html = POST.replace('<h2>향후 확인 일정</h2>', '<h2><span>향후 확인</span> 일정</h2>')
    state, body = pp.digest(html, 'kr')
    assert state == 'ok' and '11월 19일' in body


def test_any_imbalance_anywhere_hands_over_the_whole_post():
    html = POST.replace('<p>길고 긴 본문.</p>', '<p>길고 긴 본문.')
    assert pp.digest(html, 'us') == ('full', html)


def test_svg_self_closing_children_do_not_break_the_balance():
    html = POST.replace('<p>길고 긴 본문.</p>', '<svg viewBox="0 0 1 1"><path d="M0 0"/><g><rect/></g></svg>')
    assert pp.digest(html, 'us')[0] == 'ok'


def test_editor_note_removal_keeps_everything_else_verbatim():
    html = POST.replace('<p data-lede="review">복기 문단.</p>',
                        '<p data-lede="review">복기 문단.</p><div data-editor-note="1"><p>노트</p></div>')
    start = POST.index('<section class="card" data-learning')
    end = POST.index('</section>', start) + len('</section>')
    assert POST[start:end] in pp.digest(html, 'us')[1]          # 노트를 뺀 절 = 노트가 없던 절


def test_script_named_in_comments_does_not_hide_the_title_and_lede():
    """주석 안의 <script> 를 구간으로 읽으면 그 사이의 제목·lede 가 빠진 채 ok 가 된다(codex 구현 검토 3회차)."""
    html = ('<!-- <script> --><h1>Title</h1><p data-lede>Important</p><!-- </script> -->'
            '<section data-learning><p>Question</p></section>')
    state, body = pp.digest(html, 'us')
    assert state == 'ok' and 'Title' in body and 'Important' in body and 'Question' in body


def test_tags_inside_script_and_style_are_text():
    html = POST.replace('<style>p{}</style>', '<style>p{}</style><script>var s = "<p data-lede>가짜</p><div>";'
                        ' // <!-- </section>\n</script>')
    state, body = pp.digest(html, 'us')
    assert state == 'ok' and '가짜' not in body and '질문과 조건' in body


def test_unclosed_script_is_full():
    html = POST.replace('<style>p{}</style>', '<script>var a = 1;')
    assert pp.digest(html, 'us') == ('full', html)
