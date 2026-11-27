"""한국은행 금통위 문서 읽기 — 실제 원문 픽스처(2026-11-26 결정문·listYear 행·자막, 10/22 결정문)."""
import os

from kr import bok_events as B

FIX = os.path.join(os.path.dirname(__file__), '..', '..', 'common', 'tests', 'fixtures', 'cb')


def _read(name):
    with open(os.path.join(FIX, name), encoding='utf-8') as fh:
        return fh.read()


def test_decision_paragraph_diff_october_to_november():
    d = B.paragraph_diff(_read('bok_decision_2610_heads.txt'), _read('bok_decision_2611_heads.txt'))
    assert d is not None
    by = {c['para']: c for c in d['changed']}
    # 결정 문단: 「유지」 → 「3.25% 로 상향 조정」, 표결: 「7 명 모두 찬성」 → 「5 명은 찬성 … 3.00% 로 유지」
    assert '3.25%' in by[1]['after'] and '유지하여' in by[1]['before']
    assert by[7]['name'] == '표결' and '황건일 위원과 이수형 위원' in by[7]['sentences'][0]
    # 금융·외환시장·향후 운용 방향의 첫 문장은 두 달이 같다
    assert 5 not in by and 6 not in by and d['kept'] == 2


def test_diff_gives_up_unless_seven_paragraphs():
    six = '\n'.join(_read('bok_decision_2611_heads.txt').split('\n')[:7])     # 제목 + □ 6개
    assert B.paragraphs(six) is None
    assert B.paragraph_diff(six, _read('bok_decision_2611_heads.txt')) is None


def test_listyear_row_picks_opening_pdf_and_subtitle_view():
    view, pdf = B.presser_row(_read('bok_listyear_2611_row.html'), '2026-11-26')
    assert view == ('https://www.bok.or.kr/portal/bbs/B0000169/view.do?nttId=11067131&menuNo=201295'
                    '&programType=multiCont')
    # 같은 칸의 첫 PDF 는 「참고자료(2611).pdf」(fileSn=8) — 모두발언(fileSn=6)을 고른다, &amp; 는 푼다
    assert pdf.endswith('atchFileId=bde596c45643494c8fe83fd493680a12&fileSn=6')
    assert '/fileSrc/' not in pdf and '/static/' not in pdf
    assert B.presser_row(_read('bok_listyear_2611_row.html'), '2026-10-22') == (None, None)


def test_subtitle_text_keeps_turns_on_lines():
    t = B.subtitle_text(_read('bok_subtitle_1126_head.html'))
    lines = t.split('\n')
    assert lines[0].startswith('공 보 관 - 지금부터 2026년 11월 통화정책방향')
    assert lines[1].startswith('총 재 - 오늘 금융통화위원회는 한국은행 기준금리를 현재의 3.00%에서 3.25%로')


def test_minutes_date_rule_matches_six_published_minutes():
    pairs = [('2026-10-22', '2026-11-10'), ('2026-09-22', '2026-10-13'), ('2026-09-10', '2026-09-29'),
             ('2026-08-27', '2026-09-15'), ('2026-07-23', '2026-08-11'), ('2026-07-16', '2026-08-04')]
    assert [B.minutes_date(a) for a, _ in pairs] == [b for _, b in pairs]
    assert B.minutes_date('2026-11-26') == '2026-12-15'


RSS = '''<rss><channel>
<item><title>통화정책방향(2026.11.26)</title><link><![CDATA[https://www.bok.or.kr/portal/bbs/P0000559/view.do?nttId=11067084&menuNo=200690]]></link>
<description><![CDATA[&lt;p&gt;통화정책방향&lt;/p&gt;&lt;p&gt;□ 금융통화위원회는 &lt;span&gt;3.25%&lt;/span&gt;로&lt;/p&gt;]]></description>
<pubDate>Thu, 26 Nov 2026 10:30:00 +0900</pubDate></item>
<item><title>금융통화위원회 의사록(2026년 제20차)(2026.10.22)</title><link><![CDATA[https://www.bok.or.kr/portal/bbs/B0000245/view.do?nttId=11066448&menuNo=200789]]></link>
<description><![CDATA[x]]></description><pubDate>Tue, 10 Nov 2026 16:00:00 +0900</pubDate></item>
</channel></rss>'''


def test_rss_items_split_decisions_and_minutes():
    dec = B.decision_items(RSS)
    assert [(x['meeting_date'], x['published']) for x in dec] == [('2026-11-26', '2026-11-26')]
    assert dec[0]['text'] == '통화정책방향 □ 금융통화위원회는 3.25% 로'
    mins = B.minutes_items(RSS)
    assert [(x['meeting_date'], x['published']) for x in mins] == [('2026-10-22', '2026-11-10')]


def test_minutes_pdf_uses_the_robots_allowed_path():
    page = ('<a href="/fileSrc/portal/7b6dc372c33643a18fad643fd0ddbca0/2/0aea53cfe86c41f6ab711d0b91a58df0.pdf" '
            'title="O_2026년도 제20차 금통위 의사록.pdf">x</a>')
    assert B.minutes_pdf(page) == ('https://www.bok.or.kr/portal/cmmn/file/fileDown.do?menuNo=200789'
                                   '&atchFileId=7b6dc372c33643a18fad643fd0ddbca0&fileSn=2')
