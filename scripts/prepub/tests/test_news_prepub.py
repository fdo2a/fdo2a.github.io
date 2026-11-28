"""US 뉴스·산업 브리프 발행 전 검토(2026-11-28, 설계 news_prepub v1.3) — 섹션 `us-news`.

막을 것(설계 §6): 세움이 브리프 기록을 건드리지 않는다(4), 요청 ID 를 가진 세움 기록이 다음 런에서 세어진다(5 —
세지 못하면 세는 실패가 곧바로 사람 손이 된다), 받아들인 요약 정정이 글과 요약 두 쪽에 다 들어갔다(6).
"""
import json

import pytest

import prepub_review as cli
from prepub import split as split_mod
from prepub import submit

D = '2026-11-25'
RID = 'us-news-2026-11-25-0123456789ab'


# ── 요청 ID · 세움 기록 ──────────────────────────────────────────────────────────

def test_the_news_request_id_is_a_request_id():
    assert cli.RID_RE.fullmatch(RID) and cli.RID_RE.fullmatch('us-2026-11-25-0123456789ab')
    assert not cli.RID_RE.fullmatch('kr-news-2026-11-25-0123456789ab')


def _hold(tmp_path, monkeypatch, capsys, state, prev):
    (tmp_path / 'status.json').write_text(json.dumps({'state': state, 'request_id': RID}))
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    uploads = []
    monkeypatch.setattr(submit, 'upload', lambda files, *a, **k: uploads.append(sorted(files)) or 'c' * 40)
    raw = None if prev is None else cli._dumps(prev).encode()
    msgs = []

    def fake(root, rel, message, build=None, **k):
        msgs.append((rel, message))
        assert build(raw)
        return 'd' * 40
    monkeypatch.setattr(cli, 'push_record', fake)
    assert cli.main(['hold', '--dir', str(tmp_path), '--section', 'us-news', '--date', D, '--push']) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    rec = json.loads((tmp_path / f'repo/reviews/prepublish/us-news/{D}.json').read_text(encoding='utf-8'))
    return out, rec, msgs, uploads


def test_a_news_hold_writes_only_the_news_record_and_counts_across_runs(tmp_path, monkeypatch, capsys):
    out, rec, msgs, _ = _hold(tmp_path, monkeypatch, capsys, 'timeout', None)
    assert rec['section'] == 'us-news' and rec['request_id'] == RID and rec['attempt'] == 1
    assert out.endswith('lock=release') and msgs[0][0] == f'reviews/prepublish/us-news/{D}.json'
    assert 'news' in msgs[0][1]
    assert not (tmp_path / 'repo/reviews/prepublish/us').exists()          # 브리프 기록은 건드리지 않는다
    # 다음 런의 같은 실패 — 앞 기록(요청 ID 칸이 us-news 꼴)을 세어 2번째 연속 → 사람 손
    out2, rec2, _m, _u = _hold(tmp_path, monkeypatch, capsys, 'timeout', rec)
    assert rec2['attempt'] == 2 and rec2['last_counted'] == 'timeout'
    assert out2.endswith('lock=hold:recovery_needed') and rec2['next'] == 'person'


def test_a_news_hold_after_judging_keeps_materials_under_the_news_section(tmp_path, monkeypatch, capsys):
    out, rec, _m, uploads = _hold(tmp_path, monkeypatch, capsys, 'recovery_needed', None)
    assert out.endswith('lock=hold:recovery_needed')
    assert uploads and all(k.startswith(f'holds/us-news/{D}/{RID}/') for k in uploads[0])


# ── 판정 · 기록 ──────────────────────────────────────────────────────────────────

NEWS_HTML = ('<html><body><section><h2>오늘의 뉴스</h2>'
             '<div class="news-item" data-news="g1"><p class="news-head">제목<span class="sub">CNBC · 11월 4일</span></p>'
             '<p>2026년 11월 4일 중간선거에서 민주당이 이겼다.</p></div></section></body></html>')


def test_a_news_answer_has_no_style_candidates():
    review = '- 오늘의 뉴스 g1 / 선거일 11월 4일 / 11월 3일(data/news)\n\n=== 문체 지적 ===\n없음\n'
    got = split_mod.split(review, NEWS_HTML, None)
    assert got['candidates']['items'] == [] and got['style'] == [] and got['clarity'] == []
    assert '11월 3일' in got['facts']


def test_split_and_record_take_the_news_section(tmp_path, monkeypatch, capsys):
    import hashlib
    html = tmp_path / 'news.html'
    html.write_text(NEWS_HTML, encoding='utf-8')
    sha = hashlib.sha256(html.read_bytes()).hexdigest()
    (tmp_path / 'status.json').write_text(json.dumps({'state': 'reviewed', 'request_id': RID, 'draft_sha': 'a' * 40,
                                                      'source_html_sha256': sha}))
    (tmp_path / 'review.md').write_text('지적 없음\n=== 문체 지적 ===\n없음\n', encoding='utf-8')
    monkeypatch.setattr(cli, 'ROOT', str(tmp_path / 'repo'))
    assert cli.main(['split', '--review', str(tmp_path / 'review.md'), '--html', str(html), '--section', 'us-news',
                     '--date', D, '--out', str(tmp_path)]) == 0
    assert 'style candidates 0' in capsys.readouterr().out
    assert cli.main(['facts-done', '--dir', str(tmp_path), '--html', str(html)]) == 0
    assert cli.main(['record', '--dir', str(tmp_path), '--html', str(html), '--section', 'us-news', '--date', D]) == 0
    rec = json.loads((tmp_path / f'repo/reviews/prepublish/us-news/{D}.json').read_text(encoding='utf-8'))
    assert rec['section'] == 'us-news' and rec['state'] == 'reviewed' and rec['style_candidates'] == 0


# ── 정정 대조(설계 §2.6 v1.3) ─────────────────────────────────────────────────────

def _news(summary='2026년 11월 3일 중간선거에서 민주당이 이겼다.'):
    return {'report_date': D, 'items': [{'guid': 'g1', 'source': 'CNBC', 'summary_ko': summary},
                                        {'guid': 'g2', 'source': 'CNBC', 'summary_ko': '다른 기사'}]}


def _check(tmp_path, capsys, html, news, fixes):
    h = tmp_path / 'news.html'
    h.write_text(html, encoding='utf-8')
    n = tmp_path / 'news.json'
    n.write_text(json.dumps(news, ensure_ascii=False), encoding='utf-8')
    f = tmp_path / 'news_fixes.json'
    if fixes is not None:
        f.write_text(''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in fixes), encoding='utf-8')
    code = cli.main(['check-fixes', '--fixes', str(f), '--news', str(n), '--html', str(h)])
    return code, capsys.readouterr().out


FIX = {'guid': 'g1', 'wrong': '11월 4일 중간선거', 'right': '11월 3일 중간선거'}
FIXED_HTML = NEWS_HTML.replace('11월 4일 중간선거', '11월 3일 중간선거')


def test_a_fix_in_both_the_summary_and_the_post_passes(tmp_path, capsys):
    code, out = _check(tmp_path, capsys, FIXED_HTML, _news(), [FIX])
    assert code == 0 and 'prepub: fixes ok 1' in out


def test_a_fix_only_in_the_post_fails_on_the_summary(tmp_path, capsys):
    """016b1f14(11/04 선거일) 꼴 — 글만 고치고 요약에 틀린 날짜가 남았다."""
    code, out = _check(tmp_path, capsys, FIXED_HTML, _news('2026년 11월 4일 중간선거에서 민주당이 이겼다.'), [FIX])
    assert code == cli.FALLBACK and 'summary' in out


def test_a_fix_only_in_the_summary_fails_on_the_post(tmp_path, capsys):
    code, out = _check(tmp_path, capsys, NEWS_HTML, _news(), [FIX])
    assert code == cli.FALLBACK and 'post' in out


def test_a_dropped_block_checks_the_summary_only(tmp_path, capsys):
    html = NEWS_HTML.split('<div class="news-item"')[0] + '</section></body></html>'
    assert _check(tmp_path, capsys, html, _news(), [FIX])[0] == 0


def test_spacing_does_not_decide(tmp_path, capsys):
    """글의 블록 글자는 공백을 뺀 채 읽는다(news_gate 와 같은 읽기) — 공백 차이로 가르지 않는다."""
    html = FIXED_HTML.replace('11월 3일 중간선거', '11월 3일  중간선거')
    fix = dict(FIX, right='11월3일 중간선거')
    assert _check(tmp_path, capsys, html, _news(), [fix])[0] == 0


def test_no_fixes_file_means_nothing_was_accepted(tmp_path, capsys):
    code, out = _check(tmp_path, capsys, NEWS_HTML, _news(), None)
    assert code == 0 and 'prepub: fixes ok 0' in out


@pytest.mark.parametrize('line', ['{"guid": "g9", "wrong": "가", "right": "나"}', 'not json',
                                  '{"guid": "g1", "wrong": "", "right": "나"}', '{"guid": "g1", "wrong": "같다", "right": "같다"}'])
def test_a_line_that_cannot_be_checked_stops(tmp_path, capsys, line):
    h = tmp_path / 'news.html'
    h.write_text(FIXED_HTML, encoding='utf-8')
    n = tmp_path / 'news.json'
    n.write_text(json.dumps(_news(), ensure_ascii=False), encoding='utf-8')
    f = tmp_path / 'news_fixes.json'
    f.write_text(line + '\n', encoding='utf-8')
    assert cli.main(['check-fixes', '--fixes', str(f), '--news', str(n), '--html', str(h)]) == cli.FALLBACK
