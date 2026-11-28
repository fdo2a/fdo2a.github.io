import json
import subprocess

import pytest

import review_gate as gate
from prepub import bundle


def git(repo, *args):
    return subprocess.run(['git', '-C', str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / 'repo'
    (r / 'data').mkdir(parents=True)
    (r / 'data/market_data.json').write_text('{"spx": 1}')
    git(tmp_path, 'init', '-q', str(r))
    git(r, 'add', '-A')
    git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'x')
    return r


def draft(tmp_path, text='<html><body><p>코스피가 올랐다.</p></body></html>'):
    p = tmp_path / 'draft.html'
    p.write_text(text, encoding='utf-8')
    return p


def test_the_bundle_names_the_commit_its_evidence_comes_from(repo, tmp_path):
    man = bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')
    assert man['data_commit'] == git(repo, 'rev-parse', 'HEAD')
    assert man['post_path'] == 'posts/2026-11-07.html'
    assert set(man['files']) == {'post.html', 'prompt.txt'}
    assert json.loads((tmp_path / 'b/manifest.json').read_text())['request_id'] == man['request_id']


def test_the_prompt_is_the_post_publish_prompt_plus_style_findings(repo, tmp_path):
    bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')
    text = (tmp_path / 'b/prompt.txt').read_text(encoding='utf-8')
    assert 'posts/2026-11-07.html' in text and '`data/`' in text
    assert '=== 문체 지적 ===' in text


def test_edited_evidence_is_refused(repo, tmp_path):
    (repo / 'data/market_data.json').write_text('{"spx": 2}')
    with pytest.raises(bundle.BundleError):
        bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')


def test_a_late_post_names_its_collection_commit(repo, tmp_path):
    """늦은 글(2026-11-27) — 근거는 그날 수집 커밋 C 에서. HEAD 는 다음 날 자료다(11/24 MU 67d749c2 ↔ main)."""
    c = git(repo, 'rev-parse', 'HEAD')
    (repo / 'data/market_data.json').write_text('{"spx": 2}')
    git(repo, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-qam', 'next day')
    man = bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b', data_commit=c[:8])
    assert man['data_commit'] == c
    with pytest.raises(bundle.BundleError):
        bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'c', data_commit='nope')


def test_submit_passes_the_data_commit_only_when_given(monkeypatch, tmp_path):
    import prepub_review as cli
    seen = []

    def build(*a, **k):
        seen.append(k.get('data_commit'))
        raise bundle.BundleError('stop here')
    monkeypatch.setattr(bundle, 'build', build)
    html = draft(tmp_path)
    base = ['submit', '--section', 'us', '--date', '2026-11-07', '--html', str(html)]
    cli.main(base + ['--out', str(tmp_path / 'o1')])
    cli.main(base + ['--out', str(tmp_path / 'o2'), '--data-commit', 'abc123'])
    assert seen == [None, 'abc123']


def test_an_unknown_market_or_date_is_refused(repo, tmp_path):
    for sec, d in (('jp', '2026-11-07'), ('us', '11/07')):
        with pytest.raises(bundle.BundleError):
            bundle.build(str(repo), sec, d, draft(tmp_path), tmp_path / 'b')


def test_request_ids_have_the_shape_the_private_runner_accepts():
    import re
    assert re.fullmatch(r'(us|kr|jp)-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}', bundle.request_id('kr', '2026-11-07'))


def test_the_prepublish_prompt_asks_for_the_fix_kinds_and_the_clarity_kinds(repo, tmp_path):
    """2026-11-07 「번역투만」에서 2026-11-18 사용자 결정으로 넓혔다 — 번역투·확신도 두 분류는 그대로, 명료성 넷을 더한다.
    반복·끊긴 흐름·기타는 여전히 묻지 않는다."""
    bundle.build(str(repo), 'us', '2026-11-07', draft(tmp_path), tmp_path / 'b')
    text = (tmp_path / 'b/prompt.txt').read_text(encoding='utf-8')
    tail = text[text.index('문체 지적(') :]
    for kind in ('「번역투」', '「판단 세기 흐림」', '「원문에 없는 관계」',
                 '「용어」', '「문장 구조」', '「지시 대상 불명확」', '「논리·사실관계 의심」'):
        assert kind in tail
    for kind in ('「반복」', '「끊긴 흐름」', '「기타」'):
        assert kind not in tail
    assert gate.STYLE_FINDINGS_HEAD in tail
    # 사용자가 정한 기준 문장과, 검토자가 지키는 두 가지
    assert '무엇이 발생했으며 작성자가 어떤 판단을 내렸는지' in tail
    assert '짐작' in tail and '고친 문장' in tail
    for mark in ('(가)', '(나)', '(다)'):
        assert mark in tail


def test_every_kind_the_prompt_asks_for_has_a_route():
    from prepub import split
    assert set(bundle.PREPUB_KINDS) == set(split.ROUTES)
    assert bundle.RECORD_ONLY_MAX == split.RECORD_MAX


def test_the_post_publish_prompt_is_unchanged():
    text = gate.STYLE_FINDINGS_PROMPT.format(
        n=8, kinds='·'.join(f'「{k}」' for k in gate.STYLE_KINDS), head=gate.STYLE_FINDINGS_HEAD)
    assert '「반복」' in text
    # 발행 뒤 검토(맥 러너)는 명료성 분류를 묻지도 읽지도 않는다
    assert '용어' not in gate.STYLE_KINDS and '「지시 대상 불명확」' not in text
    assert gate.STYLE_FINDINGS_MAX == 8


# ── US 뉴스·산업 브리프(2026-11-28, 설계 news_prepub v1.3) ─────────────────────────────────────────

D = '2026-11-25'
NEWS = '{"report_date": "2026-11-25", "items": [{"guid": "g1", "summary_ko": "요약"}]}'


@pytest.fixture
def news_repo(tmp_path):
    """브리프 발행 커밋 P 의 꼴 — data/market_data.json·data/news/<D>.json·data/telegram/<D>.json."""
    r = tmp_path / 'nrepo'
    (r / 'data/news').mkdir(parents=True)
    (r / 'data/telegram').mkdir(parents=True)
    (r / 'data/market_data.json').write_text('{"mlcc": 1}\n')
    (r / 'data/news' / f'{D}.json').write_text(NEWS)
    (r / 'data/telegram' / f'{D}.json').write_text('{}')
    git(tmp_path, 'init', '-q', str(r))
    git(r, 'add', '-A')
    git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'brief')
    return r, git(r, 'rev-parse', 'HEAD')


def workspace(tmp_path, market='{"mlcc": 1}\n', news=NEWS):
    ws = tmp_path / 'ws'
    (ws / 'news').mkdir(parents=True, exist_ok=True)
    (ws / 'market_data.json').write_text(market)
    if news is None:
        (ws / 'news' / f'{D}.json').unlink(missing_ok=True)
    else:
        (ws / 'news' / f'{D}.json').write_text(news)
    return ws


def news_draft(tmp_path):
    return draft(tmp_path, '<html><body><div class="news-item" data-news="g1"><p>요약</p></div></body></html>')


def test_a_news_brief_bundle_names_its_post_and_the_brief_commit(news_repo, tmp_path):
    r, p = news_repo
    man = bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'b', data_commit=p,
                       workspace=workspace(tmp_path))
    assert man['post_path'] == f'news/{D}.html' and man['data_commit'] == p and man['section'] == 'us-news'
    assert man['request_id'].startswith(f'us-news-{D}-')
    import re
    assert re.fullmatch(r'(us|kr|jp|us-news)-\d{4}-\d{2}-\d{2}-[0-9a-f]{12}', man['request_id'])


def test_the_news_prompt_asks_only_for_accuracy_and_ends_with_the_empty_style_marker(news_repo, tmp_path):
    r, p = news_repo
    bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'b', data_commit=p,
                 workspace=workspace(tmp_path))
    text = (tmp_path / 'b/prompt.txt').read_text(encoding='utf-8')
    assert f'news/{D}.html' in text and '뉴스·산업 브리프' in text
    for src in (f'data/news/{D}.json', f'data/telegram/{D}.json', 'data/market_data.json', 'summary_ko'):
        assert src in text
    # 문체 분류를 묻지 않는다 — 발행 전 문체 프롬프트가 붙지 않는다
    for kind in bundle.PREPUB_KINDS:
        assert f'「{kind}」' not in text
    assert '지적 없음' in text and '무엇이 맞나' in text
    # 러너가 답에 표식이 없으면 버린다(run_review FINDINGS_HEAD) — 표식 한 줄과 「없음」을 쓰게 한다
    assert gate.STYLE_FINDINGS_HEAD in text and '`없음`' in text.split(gate.STYLE_FINDINGS_HEAD, 1)[1]


def test_the_daily_prompts_are_unchanged():
    import hashlib
    want = {('us', False): 'a6b9372a82596cba36c7f5179c69d96c0b4e0c254f61a10cb1dec58171d5cf31',
            ('us', True): 'af0941221fd0d743caa52792bdcc0284f0df7ac2a9b061ffcc3a9beb7cf93072'}
    for (sec, notes), sha in want.items():
        assert hashlib.sha256(bundle.prompt(sec, 'posts/2026-11-07.html', notes=notes).encode()).hexdigest() == sha
    assert hashlib.sha256(bundle.prompt('kr', 'kr/posts/2026-11-07.html', notes=True).encode()).hexdigest() == \
        'cd36052fc1021308afa30a3b8aab246e4d6677cff863b170eac436d505311549'


@pytest.mark.parametrize('kw', [{'market': '{"mlcc": 2}\n'}, {'news': NEWS + ' '}, {'news': None}])
def test_a_workspace_that_differs_from_the_evidence_commit_is_not_bundled(news_repo, tmp_path, kw):
    """§2.3 — 작업 공간 두 파일이 data_commit 의 판과 바이트가 다르면 묶지 않는다(한쪽만 없어도 다르다)."""
    r, p = news_repo
    with pytest.raises(bundle.BundleError):
        bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'b', data_commit=p,
                     workspace=workspace(tmp_path, **kw))


def test_a_day_without_a_news_file_on_both_sides_is_bundled(tmp_path):
    r = tmp_path / 'nrepo'
    (r / 'data').mkdir(parents=True)
    (r / 'data/market_data.json').write_text('{"mlcc": 1}\n')
    git(tmp_path, 'init', '-q', str(r))
    git(r, 'add', '-A')
    git(r, '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'brief')
    p = git(r, 'rev-parse', 'HEAD')
    man = bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'b', data_commit=p,
                       workspace=workspace(tmp_path, news=None))
    assert man['data_commit'] == p


def test_a_news_bundle_needs_the_evidence_commit_and_the_workspace(news_repo, tmp_path):
    r, p = news_repo
    with pytest.raises(bundle.BundleError):
        bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'b', workspace=workspace(tmp_path))
    with pytest.raises(bundle.BundleError):
        bundle.build(str(r), 'us-news', D, news_draft(tmp_path), tmp_path / 'c', data_commit=p)


def test_submit_passes_the_workspace_for_the_news_brief(monkeypatch, tmp_path):
    import prepub_review as cli
    seen = []

    def build(*a, **k):
        seen.append((a[1], k.get('data_commit'), k.get('workspace')))
        raise bundle.BundleError('stop here')
    monkeypatch.setattr(bundle, 'build', build)
    html = draft(tmp_path)
    assert cli.main(['submit', '--section', 'us-news', '--date', D, '--html', str(html), '--out', str(tmp_path / 'o'),
                     '--data-commit', 'abc123', '--datadir', str(tmp_path / 'ws')]) == cli.FALLBACK
    assert seen == [('us-news', 'abc123', str(tmp_path / 'ws'))]
