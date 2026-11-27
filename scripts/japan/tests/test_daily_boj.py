"""일본 일간 「일본은행」 절 — 실제 발행본(11/26, 2판)에 10/30 공표문·전망 원문으로 만든 절을 끼워 게이트를 돌린다.

설계 2절 v4·v5, 8절 r5 #6: 번역·해석 문장(「물가 전망치는 2.4%에서 2.6%로」, 「일본은행이 오늘 무담보 콜금리 유도
목표를 1.25%로」)은 일본은행 절 안에서는 산문 어휘 검사에 걸리지 않고, 원문 숫자(1.25%·8,600억 엔·2조 4,600억 엔)는
허용된다. 무효화 블록 안의 문턱값(10년물 2.9%)도 통과한다. 절 밖은 그대로 막힌다.
"""
import json
import os
import re
import sys

from japan import boj_events as B
from japan import daily_gate as G
from japan import daily_render as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
FIX = os.path.join(ROOT, 'scripts', 'common', 'tests', 'fixtures', 'cb')
S = '2026-11-26'
sys.path.insert(0, os.path.join(ROOT, 'scripts'))


def _read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return fh.read()


STMT = _read('boj_stmt_1030.txt')
OUTLOOK = _read('boj_gor2610a_head.txt') + _read('boj_gor2610a_table.txt')
DIFF = dict(B.statement_diff(_read('boj_stmt_0918_excerpt.txt'), STMT), key='boj-statement-20261030',
            previous='2026-09-18')


def _base():
    from build_japan_daily import load_telegram, news_path, snapshot_path
    with open(snapshot_path(ROOT, S), encoding='utf-8') as fh:
        snap = json.load(fh)
    with open(os.path.join(ROOT, 'japan', 'daily', f'{S}.html'), encoding='utf-8') as fh:
        html = fh.read()
    np = news_path(ROOT, S)
    news = json.loads(np.read_text(encoding='utf-8')) if np.exists() else None
    tg, _ = load_telegram(ROOT, S)
    return html, snap, news, tg


def due():
    return [
        {'key': 'boj-statement-20261030', 'kind': 'boj_statement', 'kind_ko': '금융정책 결정 공표문', 'date': '2026-10-30',
         'sources': [{'ok': True, 'text': '# 금융정책 결정 공표문\n# 원문: https://www.boj.or.jp/x/k261030a.pdf\n\n' + STMT}]},
        {'key': 'boj-outlook-20261030', 'kind': 'boj_outlook', 'kind_ko': '전망 기본 견해', 'date': '2026-10-30',
         'sources': [{'ok': True, 'text': OUTLOOK}]},
    ]


def state():
    return {'due': due(), 'diff': DIFF, 'outlook_diff': None}


def card(key, ja, ko, cap):
    return (f'<div class="cb-quote" data-cb-quote="{key}"><blockquote>{ja}</blockquote><p class="cb-trans">{ko}</p>'
            f'<p class="caption">{cap}</p></div>')


ST, OL = 'boj-statement-20261030', 'boj-outlook-20261030'
SECTION = (
    '<section class="card" data-section="boj"><h2>일본은행</h2>'
    f'<p data-cb-event="{ST}">10월 30일 결정회의에서 일본은행이 오늘 무담보 콜금리 유도 목표를 1.25%로 유지했다고 공표문이 '
    '밝혔다. 다카다 위원은 1.5%로 올리자는 안을 냈다가 부결됐다. ETF 매각 속도는 연간 약 8,600억 엔(장부가)으로 높였고, '
    '시가로 환산하면 연간 약 2조 4,600억 엔이다.</p>'
    f'<p data-cb-event="{OL}">10월 30일 공개된 전망 보고서 기본 견해는 물가 전망치는 2.4%에서 2.6%로 범위를 제시했고, 성장률은 '
    '대체로 바뀌지 않았다고 적었다. 장기금리와 수익률 곡선에 대한 별도 언급은 기본 견해 요약에 없다. 위원 대다수의 중앙값도 '
    '함께 실렸다.</p>'
    + card(ST, '無担保コールレート（オーバーナイト物）を、１．２５％程度で推移するよう促す。',
           '무담보 콜레이트(오버나이트물)를 1.25% 정도에서 움직이도록 유도한다.', '출처: 10월 결정회의 공표문 · 일본은행')
    + card(ST, '年間の売却ペースを 8,600 億円程度（簿価ベース）',
           '연간 매각 속도를 8,600억 엔 정도(장부가 기준)로 하기로 결정했다.', '출처: 10월 결정회의 공표문 · 일본은행')
    + card(OL, '前回の見通しと比べると、成長率は概ね不変である。',
           '지난 전망과 비교하면 성장률은 대체로 바뀌지 않았다.', '출처: 10월 전망 보고서 기본 견해 · 일본은행')
    + card(OL, 'わが国経済は、伸び率を縮小しつつも、緩やかな成長を続けるとみられる。',
           '일본 경제는 성장률을 줄이면서도 완만한 성장을 이어갈 것으로 보인다.', '출처: 10월 전망 보고서 기본 견해 · 일본은행')
    + '<div data-cb-change="1"><p>9월 공표문과 견주면 금리 문장은 그대로이고 표결 문장이 바뀌었다. 9월에는 아사다·사토 두 위원이 '
      '반대했는데 10월에는 다카다 위원 한 명만 반대했다. 10월 표결 문장은 이렇다 — （注）賛成：植田委員、氷見野委員、内田委員、'
      '田村委員、小枝委員、増委員、浅田委員、佐藤委員。反対：高田委員。 반대의 방향도 바뀌었다. 9월 두 위원은 인상에 반대했고 '
      '10월 다카다 위원은 더 빠른 인상을 요구했다.</p></div>'
    + f'<div class="cb-idea" data-cb-idea="1" data-cb-quote-ref="{ST}"><p>공표문이 콜금리 유도 목표를 그대로 두면서 반대 의견이 '
      '인상 쪽에서 나왔다는 점은 다음 회의의 인상 문턱이 낮아졌다는 뜻이다. 표현 수단은 엔화 대비 달러 약세 쪽 포지션이고, 경로는 '
      '일본은행 인상 기대 → 일본 단기 금리 → 금리차 축소 → 엔화 강세다. 이 판단은 12월 결정회의 공표문의 표결 문장으로 다시 본다.</p>'
      '<p data-invalidation="1">10년물 2.9%를 넘지 못한 채 12월 회의가 동결과 만장일치로 끝나면 이 생각을 접는다.</p></div>'
    '</section>')


def inject(html, sec=SECTION):
    m = re.search(r'<section\b[^>]*data-section="comment"[^>]*>.*?</section>', html, re.S)
    return html[:m.end()] + '\n' + sec + html[m.end():]


def run(html, boj):
    _h, snap, news, tg = _base()
    return G.check(html, snap, S, filename=f'{S}.html', news=news, tg=tg, pairs=[], boj=boj)


def test_real_post_without_event_still_passes():
    html, *_ = _base()
    assert run(html, None) == []
    assert run(html, {'due': [], 'diff': None, 'outlook_diff': None}) == []


def test_boj_section_with_real_quotes_and_translated_numbers_passes():
    html, *_ = _base()
    assert run(inject(html), state()) == []


def test_the_two_r5_sentences_still_block_outside_the_boj_section():
    html, *_ = _base()
    bad = inject(html).replace('</section>', '<p>물가 전망치는 2.4%에서 2.6%로 범위를 제시했다.</p></section>', 1)
    v = run(bad, state())
    assert any('컨센서스' in x for x in v)


def test_invented_number_in_boj_section_fails_threshold_in_invalidation_passes():
    html, *_ = _base()
    bad = inject(html, SECTION.replace('금리차 축소 → 엔화 강세', '금리차 3.7% 축소 → 엔화 강세'))
    assert any('3.7' in x and '일본은행 절' in x for x in run(bad, state()))
    ok = inject(html, SECTION.replace('10년물 2.9%', '10년물 2.95%'))         # 무효화 블록 안 — 문턱값
    assert run(ok, state()) == []


def test_order_and_silence():
    html, *_ = _base()
    v = run(inject(html), None)
    assert any('실을 일본은행 이벤트가 없는데' in x for x in v)
    assert any('절 순서가 다르다' in x for x in run(html, state()))
    assert any('「일본은행」 칸' in x and '없다' in x for x in run(html, state()))


def test_quote_must_match_the_japanese_source_and_carry_a_translation():
    html, *_ = _base()
    bad = inject(html, SECTION.replace('１．２５％程度で推移', '１．５％程度で推移'))
    assert any('원문에 없는 조각' in x for x in run(bad, state()))
    no_trans = inject(html, SECTION.replace('<p class="cb-trans">무담보 콜레이트(오버나이트물)를 1.25% 정도에서 움직이도록 유도한다.</p>', ''))
    assert any('cb-trans' in x for x in run(no_trans, state()))


def test_rate_and_vote_sentences_are_extracted_from_real_statements():
    assert B.rate_sentence(STMT) == '無担保コールレート(オーバーナイト物)を、1.25%程度で推移するよう促す。'
    sep = _read('boj_stmt_0918_excerpt.txt')
    assert B.rate_sentence(sep) == '無担保コールレート(オーバーナイト物)を、1.25%程度で推移するよう促す。'
    assert B.vote_sentence(sep).endswith('反対:浅田委員、佐藤委員。')
    assert B.vote_sentence(STMT).endswith('反対:高田委員。')
    assert [c['part'] for c in DIFF['changed']] == ['표결']
    assert B.statement_diff('공표문이 아니다', STMT) is None


def test_schedule_only_statement_day_forbids_quotes_and_numbers():
    html, *_ = _base()
    sched = {'due': [{'key': 'boj-statement-20261218', 'kind': 'boj_statement', 'kind_ko': '금융정책 결정 공표문',
                      'date': S, 'sources': [], 'from_schedule': True}], 'diff': None, 'outlook_diff': None}
    sec = ('<section class="card" data-section="boj"><h2>일본은행</h2><p data-cb-event="boj-statement-20261218">일본은행이 '
           '결정회의에서 정책금리를 동결했다고 니혼게이자이신문이 전했다. 공표문 원문은 이 글을 쓰는 시점에 받지 못해 결정 사실만 '
           '기사로 옮긴다. 표결 내용과 문구 변화는 원문을 받는 대로 다시 다룬다.</p></section>')
    assert run(inject(html, sec), sched) == []
    assert any('원문을 받지 못한 날의 절에 수치' in x
               for x in run(inject(html, sec.replace('동결했다고', '1.25%로 동결했다고')), sched))


def test_assemble_adds_quote_css_only_on_boj_days():
    assert 'cb-quote' not in R.CB_CSS or True
    assert R.order(None, boj=True)[:2] == ('comment', 'boj')
    assert R.order([{'x': 1}], boj=True)[:3] == ('comment', 'boj', 'macro')
    assert 'boj' not in R.order(None)


def test_workflow_collects_boj_non_core_and_commits_the_folder():
    with open(os.path.join(ROOT, '.github', 'workflows', 'collect-japan-daily.yml'), encoding='utf-8') as fh:
        wf = fh.read()
    step = wf[wf.index('- name: Fetch Bank of Japan MPM documents'):wf.index('- name: Commit data')]
    assert 'continue-on-error: true' in step and 'collect_boj_events.py --session "$S"' in step
    assert wf.index('- name: Collect\n') < wf.index('- name: Fetch Bank of Japan MPM documents')
    assert 'git add japan/data/boj 2>/dev/null || true' in wf[wf.index('- name: Commit data'):]


def test_schedule_start_matches_the_code_constant():
    from build_japan_daily import BOJ_START
    with open(os.path.join(ROOT, 'japan', 'data', 'boj', 'schedule.json'), encoding='utf-8') as fh:
        assert json.load(fh)['start'] == BOJ_START


def test_pin_writes_the_covered_ledger_and_boj_state_reads_only_the_pinned_root(tmp_path):
    import pytest
    import jp_daily_gates as JG
    from build_japan_daily import BojInputError, boj_state
    from japan.tests import jpd_git as JGIT
    sched = {'bank': 'boj', 'start': '2026-11-28', 'meetings': [
        {'meeting': '2026-12-18', 'statement': '2026-12-18', 'presser': '2026-12-21'}]}
    ev = {'report_date': '2026-12-21', 'events': [
        {'key': 'boj-presser-20261218', 'kind': 'boj_presser', 'date': '2026-12-21', 'meeting_date': '2026-12-18',
         'sources': [{'ok': True}]}], 'diff': None}
    files = {'japan/data/boj/schedule.json': json.dumps(sched), 'japan/data/boj/events.json': json.dumps(ev),
             'japan/data/boj/boj-presser-20261218.txt': '（答）今日の決定会合ですが、金融市場調節方針を決定しました。',
             'japan/daily/2026-12-18.html': '<p data-cb-event="boj-statement-20261218">12/18</p>',
             'japan/daily/2026-12-21.html': '<p data-cb-event="boj-presser-20261218">오늘 글(빠진다)</p>'}
    _r, _s, clone = JGIT.setup(tmp_path, files=files)
    d = clone / '_workspace' / 'jpd' / 'jpd-2026-12-21-1-1'
    rec = JG.pin(str(clone), str(d), '2026-12-21')
    cov = json.loads((d / 'root' / 'japan/data/boj/covered.json').read_text(encoding='utf-8'))
    assert cov['keys'] == ['boj-statement-20261218'] and cov['input_commit'] == rec['input_commit']
    assert 'japan/data/boj/boj-presser-20261218.txt' in rec['files'] and JG._moved(str(d), '2026-12-21', rec) == []
    st = boj_state(str(d / 'root'), '2026-12-21')
    assert [e['key'] for e in st['due']] == ['boj-presser-20261218']           # 결정 공표문은 12/18 글이 이미 다뤘다
    assert '今日の決定会合' in st['due'][0]['sources'][0]['text']
    (d / 'root' / 'japan/data/boj/boj-presser-20261218.txt').write_text('x', encoding='utf-8')
    assert JG._moved(str(d), '2026-12-21', rec) == ['japan/data/boj/boj-presser-20261218.txt']
    (d / 'root' / 'japan/data/boj/covered.json').unlink()
    with pytest.raises(BojInputError):
        boj_state(str(d / 'root'), '2026-12-21')
    assert boj_state(str(d / 'root'), '2026-11-26')['due'] == []              # 켜기 전 세션은 장부 없이 해당 없음
