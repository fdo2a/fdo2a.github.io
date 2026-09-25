"""KR 뉴스(네이버증권 주요뉴스) — scripts/kr/news.py · scripts/fetch_kr_news.py.

기사 본문은 저작물이라 픽스처는 실제 응답의 **모양만** 본뜬 합성 문장이다.
"""
import json

import pytest

import fetch_kr_news as F
from kr import news as N
from us import news_gate as G


def row(aid, title, stamp='20260925160500', office='001', name='연합뉴스', body='앞머리 발췌'):
    return {'id': '', 'articleId': aid, 'officeId': office, 'officeName': name,
            'datetime': stamp, 'title': title, 'titleFull': title, 'body': body, 'type': 1}


def payload(*rows):
    return {'isSuccess': True, 'detailCode': '', 'message': '', 'result': list(rows)}


# ── 목록 ─────────────────────────────────────────────────────────────────
def test_parse_list_maps_the_front_api_shape():
    (it,) = N.parse_list(payload(row('0016330001', '코스피 &quot;3000&quot; 회복', body='가' * 500)))
    assert it['guid'] == '001-0016330001'
    assert it['url'] == 'https://n.news.naver.com/mnews/article/001/0016330001'
    assert it['title'] == '코스피 "3000" 회복'
    assert it['published'] == '2026-09-25T16:05:00+09:00'
    assert it['source'] == '연합뉴스'
    assert len(it['summary']) == N.MAX_SUMMARY          # 기사 앞머리를 통째로 커밋하지 않는다


@pytest.mark.parametrize('bad', [
    {'detailCode': '', 'message': 'Request failed with status code 400'},   # pageSize=100 실측
    {'isSuccess': True, 'result': None},
    [],
    None,
])
def test_parse_list_refuses_a_shape_it_does_not_know(bad):
    # KR 규칙: 조용한 [] 를 성공으로 치지 않는다
    with pytest.raises(ValueError):
        N.parse_list(bad)


def test_rows_without_ids_or_dates_are_not_sources():
    got = N.parse_list(payload(row('', '코스피 상승'), row('0001', '코스피 하락', stamp='oops')))
    assert [it['guid'] for it in got] == ['001-0001']
    assert got[0]['published'] is None
    assert N.on_date(got, '2026-09-25') == []            # 날짜를 못 읽은 행은 오늘 것이 아니다


def test_on_date_and_the_page_stop():
    rows = N.parse_list(payload(row('1', '코스피', '20260925090000'),
                                row('2', '코스피', '20260924235900')))
    assert [it['guid'] for it in N.on_date(rows, '2026-09-25')] == ['001-1']
    assert N.older_than(rows, '2026-09-25')
    assert not N.older_than(rows[:1], '2026-09-25')


# ── 갈래 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,cat', [
    ('연휴 뒤 채권시장 변수는…미중 정상회담·유가·10월 발행물량', 'macro'),   # 매크로가 정책보다 앞선다
    ('한은 금통위, 기준금리 동결', 'macro'),
    ('정부, 상법 개정안 국회 통과 추진', 'policy'),
    ('트럼프 관세 유예 연장', 'policy'),
    ('“삼성전자 내년 63만원 vs 27만원”…증권가 전망 극과 극', 'market'),     # 증시가 산업보다 앞선다
    ('외국인 코스피 1조 순매수', 'market'),
    ('"AI 속도 조절론은 기우 … 반도체 중심 상승세 계속"', 'industry'),
    ('HD현대重, 美 해군 MRO 수주', 'industry'),
    ('日증시 엇갈린 마감…반도체주 웃고 은행주 울었다', None),               # 해외 마감은 US 몫
    ('유가↑·금리↑ 3대지수 하락···하워드막스 “미국주식 팔지마라”', None),
    ('中증시 급락에도 코스피 선방', 'market'),                              # 국내를 말하면 남긴다
    ('“엄마, 이번에 1000만원 드릴게”…추석 용돈에도 세금 붙나요', None),      # 생활 기획
    ('알고리즘에 노후 맡겨볼까?… 인간 vs AI 수익률 맞대결 승자는', None),
    ('성과 입증한 제네시스PE의 10년 [하우스리뷰]', None),
    ('美 생산성 상승에도… 노동자 몫은 더 줄었다', None),                     # 어디에도 안 걸린다
])
def test_classify(title, cat):
    assert N.classify(title) == cat


def test_dedupe_folds_the_same_story_from_different_outlets():
    rows = N.parse_list(payload(
        row('1', '“삼전 조정 오면 사라"는데…53만→63만원 vs 35만원 ‘엇갈림’', '20260925161600'),
        row('2', '"삼전 조정은 매수 기회"라는데…53만→63만원 vs 35만원 \'제각각\'', '20260925154000',
            office='215', name='한국경제TV'),
        row('1', '같은 guid 가 두 쪽에 걸친 경우', '20260925150000'),
        row('3', '‘레버리지 민족이라면서요?’ 美 ETF 브랜드 대표들 줄방한', '20260925093000'),
        row('4', '\'서학개미 큰손\' 잡아라…美 ETF 브랜드 대표들 잇단 방한', '20260925070500'),
    ))
    kept = N.dedupe(rows)
    # 실측 0.74 는 합쳐지고, 0.55(다른 각도의 기사)는 둘 다 남는다
    assert [it['guid'] for it in kept] == ['001-1', '001-3', '001-4']


def test_select_caps_each_category_and_does_not_backfill():
    rows = [dict(guid=str(i), category='market', published=f'2026-09-25T1{i}:00:00+09:00')
            for i in range(5)] + [dict(guid='m', category='macro', published='2026-09-25T09:00:00+09:00')]
    got = N.select(rows, per_category=3)
    assert [r['guid'] for r in got] == ['m', '4', '3', '2']


# ── 본문 ─────────────────────────────────────────────────────────────────
PARA = '국내 증시의 변동성이 이어지면서 투자자들이 단기 금융상품으로 자금을 옮기고 있다. ' * 10


def page(inner):
    return (f'<html><head><title>x</title></head><body><div class="media_end_head">헤더</div>'
            f'<article id="dic_area" class="go_trans _article_content">{inner}</article>'
            f'<div class="byline">다른 기사 보기</div></body></html>')


def test_extract_body_keeps_prose_and_drops_photos_bylines_and_notices():
    html = page('<strong>소제목 한 줄</strong><br><br>'
                '<span class="end_photo_org"><div><img src="a.jpg"></div>'
                '<em class="img_desc">사진 설명 캡션</em></span><br>'
                f'{PARA}<br><br>둘째 문단 &amp; 기호<br><br>[홍길동 기자]<br>'
                '홍길동 기자 hong@example.co.kr<br>ⓒ 매체, 무단 전재 및 재배포 금지<br>'
                '<!-- r_start //--><!-- r_end //--><script>var x = "스크립트";</script>')
    body = N.extract_body(html)
    assert body.startswith('소제목 한 줄\n국내 증시의')
    assert '둘째 문단 & 기호' in body
    for gone in ('사진 설명', '홍길동', '무단 전재', '스크립트', '헤더', '다른 기사'):
        assert gone not in body


def test_extract_body_refuses_pages_without_an_article_or_too_short():
    assert N.extract_body('<html><body>오류 페이지</body></html>') == ''
    assert N.body_note('<html></html>') == '본문 영역 없음'
    short = page('짧은 속보 한 줄')
    assert N.extract_body(short) == ''
    assert N.body_note(short) == '짧다'


# ── 수집 스크립트 ─────────────────────────────────────────────────────────
def test_harvest_pages_until_it_reaches_the_day_before(monkeypatch):
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    pages = {1: payload(row('1', '코스피 상승', '20260925170000')),
             2: payload(row('2', '코스피', '20260925080000'), row('3', '코스피', '20260924200000')),
             3: payload(row('4', '안 읽혀야 한다', '20260924100000'))}
    seen = []

    def fetch(url, ctx):
        n = int(url.split('page=')[1].split('&')[0])
        seen.append(n)
        return json.dumps(pages[n])

    rows, notes = F.harvest('2026-09-25', None, fetch=fetch)
    assert seen == [1, 2] and len(rows) == 3 and notes == []


def test_harvest_records_why_the_list_failed(monkeypatch):
    def fetch(url, ctx):
        return json.dumps({'detailCode': '', 'message': 'Request failed with status code 400'})

    rows, notes = F.harvest('2026-09-25', None, fetch=fetch)
    assert rows == [] and '1쪽' in notes[0] and 'ValueError' in notes[0]


def test_main_writes_metadata_and_exits_red_when_the_list_is_dead(tmp_path, monkeypatch):
    monkeypatch.setattr(F, 'harvest', lambda d, ctx: ([], ['주요뉴스 1쪽: HTTP 403']))
    monkeypatch.setattr(F, 'harvest_world', lambda d, ctx: ([], []))     # 네트워크를 타지 않는다
    monkeypatch.setattr(F, 'summarize_items', lambda *a, **k: 0)
    assert F.main(['--datadir', str(tmp_path), '--bodydir', str(tmp_path / 'b'),
                   '--date', '2026-09-25']) == 1
    saved = json.loads((tmp_path / 'news' / '2026-09-25.json').read_text(encoding='utf-8'))
    assert saved['items'] == [] and saved['notes'] == ['주요뉴스 1쪽: HTTP 403']


def test_main_summarizes_with_the_korean_source_prompt(tmp_path, monkeypatch):
    rows = N.parse_list(payload(row('1', '외국인 코스피 순매수', '20260925160000')))
    monkeypatch.setattr(F, 'harvest', lambda d, ctx: (rows, []))
    monkeypatch.setattr(F, 'harvest_world', lambda d, ctx: ([], []))
    monkeypatch.setattr(F.time, 'sleep', lambda s: None)
    monkeypatch.setattr(F, 'get', lambda url, ctx: page(PARA))
    calls = {}

    def summarize(items, bodydir, system=None):
        calls['system'] = system
        items[0]['summary_ko'] = '요약'
        return 1

    monkeypatch.setattr(F, 'summarize_items', summarize)
    assert F.main(['--datadir', str(tmp_path), '--bodydir', str(tmp_path / 'b'),
                   '--date', '2026-09-25']) == 0
    assert calls['system'] is F.SYSTEM_KO_SOURCE
    (it,) = json.loads((tmp_path / 'news' / '2026-09-25.json').read_text(encoding='utf-8'))['items']
    assert it['category'] == 'market' and it['summary_ko'] == '요약' and it['body_chars'] > 0
    assert (tmp_path / 'b' / it['body_file']).exists()


# ── 게이트 — KR 갈래로 섹션 의무를 건다 ───────────────────────────────────
def test_gate_demands_the_section_for_kr_categories_only():
    collected = {'report_date': '2026-09-25',
                 'items': [{'guid': '001-1', 'category': 'policy', 'summary_ko': '가' * 300,
                            'url': 'https://n.news.naver.com/mnews/article/001/1'}]}
    html = '<h2>정책·정치 촉매</h2><p>본문</p>'
    kr = G.check(html, collected, '2026-09-25', categories=N.DIGEST_CATEGORIES)
    assert any('오늘의 뉴스' in v for v in kr)
    # US 갈래(politics·economy…)로 보면 policy 는 의무를 걸지 않는다 — 그래서 --market 이 필요하다
    assert G.check(html, collected, '2026-09-25') == []
