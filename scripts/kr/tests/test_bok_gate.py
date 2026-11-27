"""KR 「한국은행 금통위」 칸 게이트 — 실제 11/26 기자간담회 자막·결정문으로 만든 칸."""
import json
import os
import shutil
import subprocess
import sys

from common import cb_events as CE
from kr import bok_events as B
from kr import bok_gate as BG

HERE = os.path.dirname(__file__)
FIX = os.path.join(HERE, '..', '..', 'common', 'tests', 'fixtures', 'cb')
ROOT = os.path.abspath(os.path.join(HERE, '..', '..', '..'))


def _read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return fh.read()


PRESSER = _read('bok_presser_1126_excerpt.txt')
DEC_NOV = _read('bok_decision_2611_heads.txt')
DIFF = dict(B.paragraph_diff(_read('bok_decision_2610_heads.txt'), DEC_NOV), key='bok-decision-20261126',
            previous='2026-10-22')

Q1 = '그만큼 맞게 운영을 하기 때문에 물가가 그렇게 우리 목표치에서 크게 이탈하지 않고 내년에는 근원물가가 2.6% 정도로 관리될 것이다'
Q2 = '짧게 답변드리면 그것은 우리가 통화정책을 적절히 사용한다는 그런 가정이 있기 때문에 그렇습니다'
INTRO = ('11월 26일 금융통화위원회는 기준금리를 3.00%에서 3.25%로 올렸고, 신현송 총재는 같은 날 기자간담회에서 '
         '성장 전망을 높이고도 물가 전망을 크게 올리지 않은 이유를 통화정책 가정에서 찾았다. 소수의견 두 명이 동결을 주장했다.')
CHANGE = ('<div data-cb-change="1"><p>10월 결정문과 문단별로 맞대면 결정 문단이 「유지」에서 「상향 조정」으로 바뀌었고 표결 문단에 '
          '동결 의견을 낸 위원 두 명의 이름이 새로 들어갔다. 새 표결 문장은 이렇다 — 금번 기준금리 인상 결정에 대해 '
          '금융통화위원 5 명은 찬성하였으며 , 황건일 위원과 이수형 위원은 기준금리를 3.00% 로 유지하는 것이 바람직하다는 '
          '의견을 나타냈다. 결정 문단 밖에서는 세계경제 진단의 첫 문장이 「긴장이 확대되었으나」에서 「긴장이 이어지고 있지만」으로 '
          '바뀌었다.</p></div>')
IDEA = ('<div class="cb-idea" data-cb-idea="1" data-cb-quote-ref="bok-presser-20261126"><p>총재가 물가 전망을 성장만큼 올리지 '
        '않은 이유로 통화정책 가정을 들었다는 점은 추가 인상이 전망에 이미 들어 있다는 뜻이다. 국고채 3년물은 기준금리 '
        '경로를 따라 움직이므로 단기물 비중을 낮게 두는 쪽이 이 발언과 맞는다. 표현 수단은 국고채 3년 선물 매도이고, 경로는 '
        '기준금리 기대 → 단기 금리 → 3년물이다. 이 해석은 다음 결정문의 향후 방향 문단이 같은 표현을 유지하는지로 다시 본다.</p>'
        '<p data-invalidation="1">국고채 3년물 금리가 2.80% 아래로 내려가 5거래일 머물면 이 생각을 접는다.</p></div>')


def card(q, key='bok-presser-20261126', cap='출처: 11월 금통위 총재 기자간담회 · 한국은행'):
    return (f'<div class="cb-quote" data-cb-quote="{key}"><blockquote>{q}</blockquote>'
            f'<p class="caption">{cap}</p></div>')


def section(*inner):
    return ('<section data-section="bok"><h2>한국은행 금통위</h2>'
            f'<p data-cb-event="bok-decision-20261126">{INTRO}</p>'
            f'<p data-cb-event="bok-presser-20261126">{INTRO}</p>' + ''.join(inner) + '</section>')


def post(sec):
    return f'<html><body data-register="da"><section><h2>전략 코멘트</h2><p>x</p></section>{sec}' \
           '<section><h2>오늘의 장</h2><p>y</p></section></body></html>'


def due():
    return [
        {'key': 'bok-decision-20261126', 'kind': 'bok_decision', 'kind_ko': '통화정책방향 결정문', 'date': '2026-11-26',
         'sources': [{'ok': True, 'text': DEC_NOV}]},
        {'key': 'bok-presser-20261126', 'kind': 'bok_presser', 'kind_ko': '총재 기자간담회', 'date': '2026-11-26',
         'sources': [{'ok': True, 'text': PRESSER}]},
    ]


def _full():
    return post(section(card(Q1), card(Q2),
                        card('금융통화위원회는 다음 통화정책방향 결정시까지 한국은행 기준금리를 현재의 3.00% 수준에서 3.25% 로 '
                             '상향 조정하여', key='bok-decision-20261126', cap='출처: 11월 통화정책방향 결정문 · 한국은행'),
                        card('세계경제는 중동지역의 긴장이 이어지고 있지만 견조한 AI 투자에 힘입어 양호한 성장세를 지속하고',
                             key='bok-decision-20261126', cap='출처: 11월 통화정책방향 결정문 · 한국은행'),
                        CHANGE, IDEA))


def test_full_section_from_real_documents_passes():
    assert BG.check(_full(), due(), '2026-11-26', diff=DIFF) == []


def test_tag_inside_blockquote_fails():
    bad = _full().replace(Q1, Q1.replace('않고', '<span hidden>않고</span>'))
    assert any('태그' in x for x in BG.check(bad, due(), '2026-11-26', diff=DIFF))


def test_blockquote_outside_marker_fails():
    bad = _full().replace(CHANGE, CHANGE + '<blockquote>총재는 인하도 검토했다고 말했다 이 문장은 원문에 없다</blockquote>')
    assert any('표식 없는 <blockquote>' in x for x in BG.check(bad, due(), '2026-11-26', diff=DIFF))


def test_silence_both_ways():
    assert any('실을 BOK 금통위 이벤트가 없는데' in x for x in BG.check(_full(), [], '2026-11-27'))
    assert any('칸(<section data-section="bok">)이 없다' in x
               for x in BG.check(post(''), due(), '2026-11-26', diff=DIFF))
    assert BG.check(post(''), [], '2026-11-27') == []


def test_schedule_only_day_forbids_quotes_and_numbers():
    sched = [{'key': 'bok-decision-20270114', 'kind': 'bok_decision', 'kind_ko': '통화정책방향 결정문',
              'date': '2027-01-14', 'sources': [], 'from_schedule': True}]
    intro = ('1월 14일 금융통화위원회가 기준금리를 동결했다고 연합뉴스가 전했다. 결정문 원문은 이 글을 쓰는 시점에 받지 못해 '
             '결정 사실만 기사로 옮긴다. 소수의견 여부와 향후 방향 문단은 원문을 받는 대로 다시 다룬다.')
    ok = post(f'<section data-section="bok"><h2>한국은행 금통위</h2><p data-cb-event="bok-decision-20270114">{intro}</p></section>')
    assert BG.check(ok, sched, '2027-01-14') == []
    with_num = ok.replace('동결했다고', '3.25%로 동결했다고')
    assert any('원문을 받지 못한 날의 칸에 수치' in x for x in BG.check(with_num, sched, '2027-01-14'))
    with_q = ok.replace('</section>', card(Q1, key='bok-decision-20270114') + '</section>')
    assert any('원문을 받아 두지 못한' in x for x in BG.check(with_q, sched, '2027-01-14'))


def test_invented_number_fails_but_threshold_in_invalidation_passes():
    bad = _full().replace('기준금리 기대 → 단기 금리', '기준금리 3.75% 기대 → 단기 금리')
    assert any('3.75' in x for x in BG.check(bad, due(), '2026-11-26', diff=DIFF))
    assert BG.check(_full(), due(), '2026-11-26', diff=DIFF) == []      # 2.80% 는 무효화 블록 안


def test_change_block_must_copy_a_changed_sentence():
    bad = _full().replace('금번 기준금리 인상 결정에 대해 금융통화위원 5 명은', '이번 결정에 대해 위원 5명은')
    assert any('바뀐 문장을 하나도' in x for x in BG.check(bad, due(), '2026-11-26', diff=DIFF))


def test_anonymous_minutes_caption_cannot_name_the_governor():
    minutes = [{'key': 'bok-minutes-20261126', 'kind': 'bok_minutes', 'kind_ko': '금통위 의사록', 'date': '2026-12-15',
                'sources': [{'ok': True, 'text': PRESSER}]}]
    intro = ('12월 15일 공개된 11월 26일 금통위 의사록은 위원 일부가 성장 전망 상향에도 물가 경로를 낙관하지 않았다는 점을 '
             '보여 준다. 위원 견해는 이름 없이 적혀 있다. 아래 두 문장은 의사록 원문에서 옮겼다. 해석은 그 아래에 붙였다.')
    sec = (f'<section data-section="bok"><h2>한국은행 금통위</h2><p data-cb-event="bok-minutes-20261126">{intro}</p>'
           + card(Q1, key='bok-minutes-20261126', cap='출처: 11월 금통위 의사록 · 총재 발언') + card(Q2, key='bok-minutes-20261126',
                                                                                     cap='출처: 11월 금통위 의사록 · 한 위원')
           + '</section>')
    v = BG.check(post(sec), minutes, '2026-12-16')
    assert any('「총재」를 화자로' in x for x in v)
    assert not any('날짜를 밝히지' in x for x in v)          # 12월 15일을 밝혔다


def _git(repo, *args):
    subprocess.run(['git', '-C', repo, *args], check=True, capture_output=True)


def _run(*args):
    return subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'check_bok.py'), *args],
                          capture_output=True, text=True)


def test_cli_uses_committed_posts_and_the_real_schedule_start(tmp_path):
    repo = str(tmp_path / 'repo')
    os.makedirs(os.path.join(repo, 'kr', 'posts'))
    os.makedirs(os.path.join(repo, 'kr', 'data', 'bok'))
    shutil.copy(os.path.join(ROOT, 'kr', 'data', 'bok', 'schedule.json'), os.path.join(repo, 'kr', 'data', 'bok'))
    rows = [{**e, 'meeting_date': '2026-11-26', 'sources': [{'role': 'x', 'ok': True}]} for e in due()]
    with open(os.path.join(repo, 'kr', 'data', 'bok', 'events.json'), 'w', encoding='utf-8') as fh:
        json.dump({'report_date': '2026-11-26', 'events': rows, 'diff': DIFF}, fh, ensure_ascii=False)
    for e, text in zip(rows, (DEC_NOV, PRESSER)):
        with open(os.path.join(repo, 'kr', 'data', 'bok', f'{e["key"]}.txt'), 'w', encoding='utf-8') as fh:
            fh.write(text)
    _git(repo, 'init', '-q')
    _git(repo, 'config', 'user.email', 't@t')
    _git(repo, 'config', 'user.name', 't')
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'x')
    html = str(tmp_path / 'p.html')
    with open(html, 'w', encoding='utf-8') as fh:
        fh.write(post(''))
    dd = os.path.join(repo, 'kr', 'data')
    # 실제 일정 파일(start 2026-11-28): 11/26 결정은 켜기 전 — 11/27·11/30 글은 칸 없이 통과
    for d in ('2026-11-27', '2026-11-30'):
        r = _run('--html', html, '--date', d, '--datadir', dd, '--repo', repo)
        assert r.returncode == 0, r.stdout + r.stderr
        assert '이벤트 없음' in r.stdout
    r = _run('--diag', '--date', '2026-12-15', '--datadir', dd, '--repo', repo)
    assert r.returncode == 0 and '실을 이벤트 없음' in r.stdout and '예정된 금통위 의사록(2026-12-15) 원문을 못 받았다' in r.stdout
    # start 를 앞당기면 11/26 결정·기자간담회가 의무가 된다 — 칸 없는 글은 막힌다
    s = json.load(open(os.path.join(dd, 'bok', 'schedule.json'), encoding='utf-8'))
    s['start'] = '2026-11-20'
    json.dump(s, open(os.path.join(dd, 'bok', 'schedule.json'), 'w', encoding='utf-8'), ensure_ascii=False)
    r = _run('--html', html, '--date', '2026-11-26', '--datadir', dd, '--repo', repo)
    assert r.returncode == 1 and '칸(<section data-section="bok">)이 없다' in r.stdout
    with open(html, 'w', encoding='utf-8') as fh:
        fh.write(_full())
    r = _run('--html', html, '--date', '2026-11-26', '--datadir', dd, '--repo', repo)
    assert r.returncode == 0, r.stdout + r.stderr
    # 11/26 글이 커밋되면 다음 날은 장부가 막는다(같은 KEY 를 다시 열지 않는다)
    shutil.copy(html, os.path.join(repo, 'kr', 'posts', '2026-11-26.html'))
    _git(repo, 'add', '-A')
    _git(repo, 'commit', '-qm', 'post')
    r = _run('--diag', '--date', '2026-11-27', '--datadir', dd, '--repo', repo)
    assert '실을 이벤트 없음' in r.stdout
    # 켠 뒤 날짜에 일정 파일이 없으면 멈춘다(빈 의무로 읽지 않는다). 켜기 전 날짜(옛 발행 커밋 재연)는 해당 없음
    os.remove(os.path.join(dd, 'bok', 'schedule.json'))
    assert _run('--diag', '--date', '2026-12-01', '--datadir', dd, '--repo', repo).returncode == 2
    assert _run('--html', html, '--date', '2026-11-26', '--datadir', dd, '--repo', repo).returncode == 1   # 칸이 있다
    with open(html, 'w', encoding='utf-8') as fh:
        fh.write(post(''))
    assert _run('--html', html, '--date', '2026-11-26', '--datadir', dd, '--repo', repo).returncode == 0


def test_key_names_match_between_schedule_and_collector():
    with open(os.path.join(ROOT, 'kr', 'data', 'bok', 'schedule.json'), encoding='utf-8') as fh:
        sched = json.load(fh)
    assert sched['start'] == BG.START
    keys = {d['key'] for d in CE.schedule_docs(sched)}
    assert {'bok-decision-20261126', 'bok-presser-20261126', 'bok-minutes-20261126'} <= keys
