"""KR 「글로벌」 갈래 (2026-09-26) — 네이버 뉴스 세계 섹션.

사용자 지시: 미국·한국 밖(일본·중국·유럽·중동)의 정책·경제 뉴스. 픽스처는 2026-09-25 섹션
목록의 **모양만** 본뜬 합성 문장이다.
"""
import pytest

import fetch_kr_news as F
from kr import news as N


def li(office, aid, title, lede='앞머리 발췌', press='연합뉴스'):
    url = f'https://n.news.naver.com/mnews/article/{office}/{aid}'
    return (f'<li class="sa_item _LAZY_LOADING_WRAP"><div class="sa_item_inner"><div class="sa_thumb">'
            f'<a href="{url}" class="sa_thumb_link _NLOG_IMPRESSION"><img></a></div>'
            f'<div class="sa_text"><a href="{url}" class="sa_text_title _NLOG_IMPRESSION" data-rank="1">'
            f'<strong class="sa_text_strong">{title}</strong></a>'
            f'<div class="sa_text_lede">{lede}</div><div class="sa_text_info"><div class="sa_text_info_left">'
            f'<div class="sa_text_press">{press}</div><div class="sa_text_datetime"><b>4시간전</b></div>'
            f'</div></div></div></div></li>')


def page(*items):
    return '<html><body><ul class="sa_list">' + ''.join(items) + '</ul></body></html>'


# ── 등록부 ───────────────────────────────────────────────────────────────
def test_the_digest_adds_global_at_the_end():
    assert N.DIGEST_CATEGORIES[-1] == 'global'
    assert N.LABELS['global'] == '글로벌'


def test_world_sections_cover_the_four_regions_the_user_named():
    names = {name for _, _, name in N.WORLD_SECTIONS}
    assert names == {'세계경제', '아시아/호주', '유럽', '중동/아프리카'}
    url = N.SECTION_URL.format(sid1=101, sid2=262, date='20260925')
    assert url == 'https://news.naver.com/breakingnews/section/101/262?date=20260925'


# ── 목록 ─────────────────────────────────────────────────────────────────
def test_parse_section_maps_the_list_shape():
    (it,) = N.parse_section(page(li('001', '0016336526',
                                     '주중美대사 &quot;中 이란 지원 불용&quot;', lede='가' * 400)))
    assert it['guid'] == '001-0016336526'
    assert it['url'] == 'https://n.news.naver.com/mnews/article/001/0016336526'
    assert it['title'] == '주중美대사 "中 이란 지원 불용"'
    assert it['source'] == '연합뉴스'
    assert it['published'] is None                # 목록은 「4시간전」 — 기사면에서 읽는다
    assert len(it['summary']) == N.MAX_SUMMARY
    assert it['feed'] == 'world'


def test_a_page_without_the_list_shape_raises_instead_of_returning_nothing():
    with pytest.raises(ValueError):
        N.parse_section('<html><body>점검 중입니다</body></html>')


def test_an_empty_list_is_an_empty_result_not_an_error():
    assert N.parse_section(page()) == []


# ── 지역 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,want', [
    ('美中, 비민감 품목 우대교역 합의…28일 세부내용 공개', 'china'),
    ('시진핑, 美국빈방문 마치고 귀국길', 'china'),
    ('미 USTR 대표 "미중 무역협상 세부 내용 28일 발표할 것"', 'china'),
    ('미·중 정상, 관세 유예 연장', 'china'),
    ('日銀, 기준금리 동결…12월 인상 시사', 'japan'),
    ('일본은행 총재 "엔저 좌시 않겠다"', 'japan'),
    ('EU, 우크라 군사 지원에 10조원 기금 쓰기로 합의', 'europe'),
    ('러 집권당, 전시 총선서 사상 최다 349석', 'europe'),
    ('이란 고위 관리 "美 호르무즈 재개방 조건 수용해도 핵 양보 안해"', 'mideast'),
    ('후티에 밀리는 예멘 정부, 총동원령', 'mideast'),
    ('中企 수출 바우처 확대', None),              # 中企 = 중소기업
    ('코스피 3000 가자…개인 매수 몰려', None),     # 가자지구가 아니다
    ('주식이란 무엇인가', None),                   # 조사 「이란」
    ('달러 강세에 원화 약세', None),               # 「러」 가 달러 안에 있다
    ('美기업투자 견조한데 소비심리 뚝', None),
])
def test_region_is_read_from_the_korean_title(title, want):
    assert N.region(title) == want


# ── 분류 ─────────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,want', [
    ('美中, 비민감 품목 우대교역 합의…28일 세부내용 공개', 'global'),
    ('EU, 우크라 군사 지원에 10조원 기금 쓰기로 합의', 'global'),
    ('이란 대통령 "전쟁 종결 여부 美가 선택할 문제"', 'global'),
    ('러 집권당, 전시 총선서 사상 최다 349석', 'global'),
    ('[미중정상회담] 트럼프 오토펜 농담에 시진핑 껄껄', None),        # 정책·경제 어휘 없음
    ('AI 훈풍·이란 협상 제안에 뉴욕증시 상승 출발', None),             # 미국 시황은 US 리포트 몫
    ('日증시 급등…닛케이 사상 최고', None),                            # 해외 시황
    ('교황, AI 경고…"기계의 낙원에서 인간성 잃지 말아야"', None),
])
def test_global_needs_a_region_and_a_policy_word(title, want):
    assert N.classify_global(title) == want


def test_categorize_routes_world_rows_to_global_and_main_rows_as_before():
    rows = [{'title': 'EU, 대러 제재 합의', 'feed': 'world'},
            {'title': '기준금리 동결', 'feed': None},
            {'title': '교황 방한', 'feed': 'world'}]
    got = N.categorize(rows)
    assert [(r['title'], r['category']) for r in got] == [
        ('EU, 대러 제재 합의', 'global'), ('기준금리 동결', 'macro')]
    assert got[0]['region'] == 'europe'


def test_a_main_news_duplicate_of_a_world_story_is_kept_once_as_main():
    main = {'guid': '001-1', 'title': '미중 무역협상 진전…28일 발표', 'published': '2026-09-25T10:00:00+09:00'}
    world = {'guid': '001-1', 'title': '미중 무역협상 진전…28일 발표', 'feed': 'world', 'published': None}
    got = N.dedupe([main, world])
    assert len(got) == 1 and not got[0].get('feed')


# ── 선정 ─────────────────────────────────────────────────────────────────
def g(guid, title, region, **kw):
    return dict({'guid': guid, 'title': title, 'category': 'global', 'region': region,
                 'published': None}, **kw)


def test_global_candidates_rotate_regions():
    rows = [g('c1', '中 인민은행 금리 인하', 'china'), g('c2', '中 수출 급감', 'china'),
            g('c3', '中 부동산 부양책', 'china'), g('e1', 'ECB 금리 동결', 'europe'),
            g('m1', '사우디 감산 연장', 'mideast')]
    got = N.select(rows)
    assert {r['region'] for r in got[:3]} == {'china', 'europe', 'mideast'}
    assert len(got) == min(5, N.PRESELECT_GLOBAL)


def test_trim_keeps_same_day_bodied_rows_and_caps_at_four():
    rows = [g(f'x{i}', t, r, body_chars=900, published=f'2026-09-25T0{i}:00:00+09:00')
            for i, (t, r) in enumerate([('中 금리 인하', 'china'), ('ECB 동결', 'europe'),
                                         ('사우디 감산', 'mideast'), ('日銀 인상', 'japan'),
                                         ('中 수출 급감', 'china')])]
    rows.append(g('yday', '英 예산안', 'europe', body_chars=900, published='2026-09-24T23:00:00+09:00'))
    rows.append(g('nobody', '獨 재정', 'europe', body_chars=0, published='2026-09-25T09:00:00+09:00'))
    rows.append({'guid': 'm', 'title': '코스피', 'category': 'market', 'published': '2026-09-25T09:00:00+09:00'})
    got = N.trim(rows, '2026-09-25')
    gl = [r['guid'] for r in got if r['category'] == 'global']
    assert len(gl) == 4 and 'yday' not in gl and 'nobody' not in gl
    assert 'm' in [r['guid'] for r in got]


def test_article_published_reads_the_naver_article_stamp():
    html = '<span class="_ARTICLE_DATE_TIME" data-date-time="2026-09-24 23:45:06">'
    assert N.article_published(html) == '2026-09-24T23:45:06+09:00'
    assert N.article_published('<html/>') is None


# ── 수집 잡 ──────────────────────────────────────────────────────────────
def test_harvest_world_reads_every_section_and_notes_failures():
    seen = []

    def fetch(url, ctx):
        seen.append(url)
        if '/234' in url:
            raise OSError('boom')
        return page(li('001', str(len(seen)), 'EU 제재 합의'))

    rows, notes = F.harvest_world('2026-09-25', None, fetch=fetch, gap=0)
    assert len(seen) == len(N.WORLD_SECTIONS)
    assert all('?date=20260925' in u for u in seen)
    assert len(rows) == len(N.WORLD_SECTIONS) - 1
    assert any('중동/아프리카' in n for n in notes)


def test_fetch_bodies_fills_the_date_from_the_article_page(tmp_path):
    body = '<article id="dic_area">' + '유럽중앙은행이 기준금리를 동결했다. ' * 30 + '</article>'
    html = '<span class="_ARTICLE_DATE_TIME" data-date-time="2026-09-25 08:00:00"></span>' + body
    rows = [{'url': 'https://n.news.naver.com/mnews/article/001/1', 'title': 'ECB 동결',
             'category': 'global', 'published': None}]
    F.fetch_bodies(rows, str(tmp_path), None, fetch=lambda u, c: html)
    assert rows[0]['published'] == '2026-09-25T08:00:00+09:00'
    assert rows[0]['body_chars'] > 0


def test_japan_goes_first_in_the_rotation():
    # 2026-09-26 「일본 관련 뉴스…추가해」 — 후보가 있으면 일본 한 건은 반드시 들어간다
    rows = [g('e1', 'ECB 금리 동결', 'europe'), g('c1', '中 인민은행 금리 인하', 'china'),
            g('j1', '日銀 금리 인상', 'japan')]
    assert N.select(rows)[0]['guid'] == 'j1'
