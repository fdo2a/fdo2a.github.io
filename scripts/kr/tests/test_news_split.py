"""KR 뉴스 글 분리(2026-11-05) — 갈래 정치·정책·매크로·산업·글로벌, 필수 갈래 하한 3.

사용자 지시 「한국 레포트 칸에도 미국처럼 뉴스탭을 새로 만들어 분리해서 발행하자. 미국처럼 정치,
매크로, 특정 이슈가 있는 산업으로 각각 최소 3개씩」, 역인터뷰 답 「정치와 정책 따로」.
제목은 2026-11-03~05 네이버증권 주요뉴스·네이버 뉴스 정치 섹션 실측이다(제목만, 본문 없음).
"""
import pytest

from kr import news as N


def test_digest_categories_and_labels():
    assert N.DIGEST_CATEGORIES == ('politics', 'policy', 'macro', 'industry', 'global')
    assert [N.LABELS[c] for c in N.DIGEST_CATEGORIES] == ['정치', '정책', '매크로', '산업', '글로벌']
    assert N.REQUIRED == ('politics', 'policy', 'macro', 'industry')
    assert 'market' not in N.DIGEST_CATEGORIES


# ── 주요뉴스 갈래 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,cat', [
    # 증시 마감·전망은 마감브리프 몫 — 「트럼프·선거·민주당」이 있어도 정책으로 새지 않는다(11/04 실측)
    ("美선거 후폭풍에 코스피 5380선 '털썩'…코스닥도 5% 급락 마감", 'market'),
    ("블루웨이브 'AI 규제' 겁먹은 韓증시...\"삼전닉스 급락\" 매도 사이드카", 'market'),
    ("'레임덕' 트럼프의 분노…증시 방향성 결정짓나[미 중간선거]", 'market'),
    ('美 역대 중간선거…1년 뒤 주가 10% 이상 상승', 'market'),
    # 기업 실적·계약은 「유가·수출」 단어가 있어도 산업이다
    ('LG화학 3분기 영업익 17%↓…고유가 부담에 석유화학 적자(종합2보)', 'industry'),
    ('오스코텍, 기술수출 2건에 계약금 928억원…수익성 목표 조기 달성', 'industry'),
    ('SK바이오팜, 3분기 영업익 전년比 66% ↑…분기 최대 실적 경신', 'industry'),
    ('반도체·AI가 바꾼 전력 수요…호남 전력 해법은', 'industry'),
    # 나라 단위 지표의 「실적」 은 매크로다
    ('10월 수출 실적 역대 최대…반도체 견인', 'macro'),
    ("'삼전닉스' 연말 배당 역송금 최대 126억달러…원화 강세에 복병되나", 'macro'),
    ('블루웨이브에 美 국채 강세…韓 채권시장 영향 주목', 'macro'),
    ('한은 금통위, 기준금리 동결', 'macro'),
    # 정책 — 정부·당국·제도
    ('정부 표창도 받았는데 주가로 퇴출…기특·상폐 제도 엇박자', 'policy'),
    ('중복상장 규제 후폭풍…기업 고심 깊어진다 [투자360]', 'policy'),
    ('美 의회 지형 바뀌어도 투자 압박 여전…韓 통상전략 시험대', 'policy'),
    ('트럼프 관세 유예 연장', 'policy'),
    ('정부, 상법 개정안 국회 통과 추진', 'policy'),          # 제도 내용이 있으면 정책이 정치보다 앞선다
    # 정치 — 국내 정치 주체. 美 민주당은 국내 정치가 아니다
    ("'투자 실패하면 대표가 갚아라' 신기사 연대책임 논란...국회선 금지법 추진", 'politics'),
    ('여야, 미래대응기금 두고 충돌', 'politics'),
    ("“美 중간선거 패배자는 머스크, 텍사스와 새로운 관계 설정해야”", None),
    # 그대로 버리는 것
    ('日증시 엇갈린 마감…반도체주 웃고 은행주 울었다', None),
    ('“엄마, 이번에 1000만원 드릴게”…추석 용돈에도 세금 붙나요', None),
])
def test_classify_main_rows(title, cat):
    assert N.classify(title) == cat


# ── 정치 섹션 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize('title,keep', [
    ("韓-튀르키예 ‘원전 금융협력 MOU’...李 “우리 기업 참여 선제적 지원”", True),
    ('미래대응기금 두고 맞붙은 여야…민주당 "성장동력 투자" 국민의힘 "총선용 사금고"', True),
    ('이 대통령 "아파트 주요 지역 실거래가 하락…통계 제대로"', True),
    ('북, 이번에는 순항미사일에 집속탄…순항에서 수직 타격도 시험', True),
    ("與, '관행적 농지 임대·불법 전용 양성화' 특별법 발의…연내 입법 추진", True),
    # 정쟁·의전·사진·여론조사는 시장 데스크 기사가 아니다
    ("'친명' 김남희, '친청' 문정복 꺾고 민주당 전국여성위원장 당선", False),
    ('김민석 "신천지 3자 연합 증거 없다" 사과…정청래 "김민석 유죄"', False),
    ("민주당, ‘조작기소 특검법’ 5일 본회의 상정 추진", False),
    ('[포토] 튀르키예 대통령 방한', False),
    ('빨간 저고리 입은 김혜경 여사, 튀르키예 영부인과 친교...“피 나눈 형제애”', False),
    ('차기 대통령감은?…오세훈 18.4%·장동혁 13.6%·한동훈 12.6%', False),
    ("[투나잇이슈] 李 예산안 시정연설…극심한 여야 온도차", False),            # 묶음 기사
])
def test_politics_section_keeps_only_market_relevant_titles(title, keep):
    assert (N.classify_politics(title) == 'politics') is keep


def test_categorize_routes_politics_rows():
    rows = [{'guid': 'p1', 'title': '이 대통령 "아파트 주요 지역 실거래가 하락…통계 제대로"', 'feed': 'politics'},
            {'guid': 'p2', 'title': '[포토] 튀르키예 대통령 방한', 'feed': 'politics'},
            {'guid': 'm1', 'title': '한은 금통위, 기준금리 동결'}]
    got = N.categorize(rows)
    assert [(r['guid'], r['category']) for r in got] == [('p1', 'politics'), ('m1', 'macro')]


def test_same_topic_titles_count_once():
    a = "韓-튀르키예 ‘원전 금융협력 MOU’...李 “우리 기업 참여 선제적 지원”"
    b = "李대통령, 튀르키예와 '원전·방산' 협력 밀착…\"피를 나눈 형제\"(종합)"
    c = '미래대응기금 두고 맞붙은 여야…민주당 "성장동력 투자" 국민의힘 "총선용 사금고"'
    assert N.same_topic(a, b)
    assert not N.same_topic(a, c)
    # 11/05 실측 — 「대미투자는」·「대미투자도」처럼 조사만 다른 꼴
    assert N.same_topic("靑, '美 블루쓰나미'에 “한미동맹 영향 없을 것…대미투자는 국익 최우선”",
                        '[속보] 靑 “한미관계, 美 선거결과 영향 미치지 않을 것…대미투자도 지속 추진”')
    assert not N.same_topic('코인 과세 또 2년 미룬다…네 번째 유예',
                            '李 “3차 부동산 투기 단속 곧 시작…범법으로 돈 벌던 시대 끝”')


# ── 2단 선정 — 후보를 넉넉히, 본문을 받은 뒤 확정 ───────────────────────────
def _rows(cat, n, feed=None, prefix=''):
    titles = ['반도체 수출 규제', '조선 수주 랠리', '바이오 임상 결과', '2차전지 공장 증설', '원전 MOU 체결',
              '방산 계약 확대', '철강 관세 부담', '전력망 투자 계획']
    out = []
    for i in range(n):
        r = {'guid': f'{prefix}{cat}{i}', 'title': f'{titles[i % len(titles)]} {cat} {i}', 'category': cat,
             'published': f'2026-11-04T1{i}:00:00+09:00'}
        if feed:
            r['feed'] = feed
        out.append(r)
    return out


def test_select_preselects_required_categories_and_drops_market():
    rows = _rows('macro', 9) + _rows('market', 5) + _rows('industry', 2)
    got = N.select(rows)
    cats = [r['category'] for r in got]
    assert cats.count('macro') == N.PRESELECT == 6
    assert cats.count('industry') == 2          # 얇으면 채우지 않는다
    assert 'market' not in cats


def test_trim_keeps_up_to_final_with_body_and_the_right_date():
    rows = _rows('policy', 6)
    rows[0]['body_chars'] = 0                    # 본문 실패
    for r in rows[1:]:
        r['body_chars'] = 900
    rows[2]['published'] = '2026-11-03T23:00:00+09:00'   # 기사면 날짜가 전날
    got = N.trim(rows, '2026-11-04')
    assert [r['guid'] for r in got] == ['policy5', 'policy4', 'policy3', 'policy1']
    assert len(got) == N.FINAL == 4


def test_politics_spreads_topics_before_repeating():
    base = {'category': 'politics', 'feed': 'politics', 'body_chars': 900,
            'published': '2026-11-04T10:00:00+09:00'}
    rows = [dict(base, guid='a', title="韓-튀르키예 ‘원전 금융협력 MOU’...李 “우리 기업 참여 선제적 지원”"),
            dict(base, guid='b', title="李대통령, 튀르키예와 '원전·방산' 협력 밀착…\"피를 나눈 형제\"(종합)"),
            dict(base, guid='c', title='미래대응기금 두고 맞붙은 여야…민주당 "성장동력 투자" 국민의힘 "총선용 사금고"'),
            dict(base, guid='d', title='북, 이번에는 순항미사일에 집속탄…순항에서 수직 타격도 시험')]
    got = [r['guid'] for r in N.trim(rows, '2026-11-04')]
    assert got[:3] == ['a', 'c', 'd'] and 'b' not in got[:3]


# ── 게이트 — 필수 갈래 하한 ─────────────────────────────────────────────────
from us import news_gate as G  # noqa: E402

S300 = '국내 정책 당국이 제도 개편 방향을 내놓았고 시장은 그 일정과 범위를 따져 보고 있다. ' * 6


def _collected(spec):
    items = []
    for cat, n in spec.items():
        for i in range(n):
            items.append({'guid': f'001-{cat}{i}', 'category': cat, 'summary_ko': S300.strip(),
                          'url': f'https://n.news.naver.com/mnews/article/001/{cat}{i}',
                          'title': f'{cat} {i}', 'source': '연합뉴스'})
    return {'report_date': '2026-11-05', 'items': items}


def _html(collected, take):
    blocks = []
    for it in collected['items']:
        if take.get(it['category'], 0) > 0:
            take[it['category']] -= 1
            blocks.append(f'<div class="news-item" data-news="{it["guid"]}"><p class="news-head">{it["title"]}'
                          f'<span class="sub">연합뉴스 · 11월 5일</span></p>'
                          f'<p data-summary="{it["guid"]}">{it["summary_ko"]}</p></div>')
    return f'<section><h2>오늘의 뉴스</h2><div class="card">{"".join(blocks)}</div></section>'


FLOOR = (N.REQUIRED, N.MIN)


def test_floor_blocks_a_thin_category_when_the_data_had_enough():
    col = _collected({'politics': 4, 'policy': 3, 'macro': 3, 'industry': 3})
    html = _html(col, {'politics': 2, 'policy': 3, 'macro': 3, 'industry': 3})
    v = G.check(html, col, '2026-11-05', categories=N.DIGEST_CATEGORIES, floor=FLOOR)
    assert any('「politics」 갈래가 2건' in x for x in v), v


def test_floor_accepts_what_the_data_had_when_it_was_short():
    col = _collected({'politics': 2, 'policy': 3, 'macro': 3, 'industry': 3})
    html = _html(col, {'politics': 2, 'policy': 3, 'macro': 3, 'industry': 3})
    assert not [x for x in G.check(html, col, '2026-11-05', categories=N.DIGEST_CATEGORIES, floor=FLOOR)
                if '갈래가' in x]


def test_no_floor_for_the_old_kr_market():
    col = _collected({'politics': 4})
    html = _html(col, {'politics': 1})
    assert not [x for x in G.check(html, col, '2026-11-05', categories=N.DIGEST_CATEGORIES)
                if '갈래가' in x]


# ── 컷오버 — 마감브리프에서 빠진다 ─────────────────────────────────────────
def test_split_dates_agree_everywhere():
    from common import contested as C
    from review import corrector
    from ci import routine_due
    assert N.SPLIT_FROM == C.KR_NEWS_FROM == corrector.KR_NEWS_FROM == routine_due.KR_NEWS_FROM
    assert set(routine_due.KR_NEWS_CATEGORIES) == set(N.DIGEST_CATEGORIES)
    assert N.brief_carries_news('2026-11-05') and not N.brief_carries_news('2026-11-06')


def test_contested_moves_to_the_news_post_from_the_split_date():
    from common import contested as C
    assert C.cfg_for('kr', '2026-11-05')['page'] == 'kr/posts/{d}.html'
    assert C.cfg_for('kr', '2026-11-06')['page'] == 'kr/news/{d}.html'
    assert C.cfg_for('kr', '2026-11-06')['shell'] == 'kr-news'
    assert C.cfg_for('kr', '2026-11-06')['result'] == 'data/contested/kr/{d}.json'   # 결과 자리는 그대로
    assert C.cfg_for('us', '2026-11-06')['page'] == 'news/{d}.html'
    assert C.pages_dirs('kr') == ('kr/posts', 'kr/news')
    assert C.is_news_page('kr', '2026-11-06') and not C.is_news_page('kr', '2026-11-05')


def test_stance_gate_refuses_news_left_in_the_brief_after_the_split():
    from kr import stance_gate as SG
    brief = ('<section><h2>오늘의 뉴스</h2><div class="card"><div class="news-item" data-news="001-1">'
             '<p>x</p></div></div></section><!--CONTESTED-->')
    after = SG.news_split_violations(brief, '2026-11-06')
    assert any('data-news' in v for v in after) and any('쟁점 분석 표식' in v for v in after)
    assert any('섹션이 있다' in v for v in after)
    assert SG.news_split_violations(brief, '2026-11-05') == []          # 옛 글은 예전 계약
    assert SG.news_split_violations('<section><h2>시장 판단과 복기</h2></section>', '2026-11-06') == []


def test_echo_check_ignores_collected_summaries_on_news_posts_only():
    from us import readability as R
    summ = ''.join(f'<p data-summary="00{i}-1">지수가 장중 4% 밀렸다가 회복한 날이다 매체 {i} 의 기사다.</p>'
                   for i in range(5))
    news = '<link rel="canonical" href="https://fdo2a.github.io/kr/news/2026-11-06.html">'
    brief = '<link rel="canonical" href="https://fdo2a.github.io/kr/posts/2026-11-06.html">'
    assert R.echoed_figures(f'{news}<section>{summ}</section>') == []
    assert R.echoed_figures(f'{brief}<section>{summ}</section>')       # 브리프에서 data-summary 로 피하지 못한다 (codex #6)
    mine = ''.join(f'<p>작성자가 쓴 문장 {i} 에서 지수가 4% 밀렸다고 다시 말한다.</p>' for i in range(5))
    assert R.echoed_figures(f'<section>{mine}</section>')


# ── codex 구현 검토 2026-11-06 재현 ─────────────────────────────────────────
def test_market_rows_do_not_dedupe_away_a_kept_category():                 # #4
    rows = [{'guid': 'm', 'title': '코스피 하락 정부 경제 성장 대책 발표', 'published': '2026-11-06T10:00:00+09:00'},
            {'guid': 'p', 'title': '정부 경제 성장 대책 발표', 'feed': 'politics'}]
    got = N.dedupe(N.digestible(N.categorize(rows)))
    assert [r['guid'] for r in got] == ['p']


def test_politics_preselect_keeps_same_topic_spares_behind():             # #5
    base = {'category': 'politics', 'feed': 'politics'}
    a = "韓-튀르키예 ‘원전 금융협력 MOU’...李 “우리 기업 참여 선제적 지원”"
    rows = [dict(base, guid='a', title=a),
            dict(base, guid='b', title="李대통령, 튀르키예와 '원전·방산' 협력 밀착…\"피를 나눈 형제\"(종합)"),
            dict(base, guid='c', title='미래대응기금 두고 맞붙은 여야…민주당 "성장동력 투자" 국민의힘 "총선용 사금고"'),
            dict(base, guid='d', title='북, 이번에는 순항미사일에 집속탄…순항에서 수직 타격도 시험')]
    got = [r['guid'] for r in N.select(rows)]
    assert set(got) == {'a', 'b', 'c', 'd'} and got.index('b') == 3        # 대체 후보는 맨 뒤에 남는다


def test_split_gate_sees_spaced_attributes_and_summaries():               # #7
    from kr import stance_gate as SG
    v = SG.news_split_violations('<section><h2>정책 동향</h2><div DATA-NEWS = "001-1"><p data-summary ="x">y</p>'
                                 '</div></section><!-- CONTESTED -->', '2026-11-06')
    assert len(v) == 3, v


def test_legacy_kr_market_keeps_the_old_categories():                    # #8
    import check_news
    assert 'market' in check_news.CATEGORIES['kr'] and 'politics' not in check_news.CATEGORIES['kr']
    assert check_news.CATEGORIES['kr-news'] == N.DIGEST_CATEGORIES


def test_spare_replaces_a_failed_original_and_is_dropped_otherwise():     # codex 재확인 #1
    base = {'category': 'policy', 'published': '2026-11-06T10:00:00+09:00'}
    rows = [dict(base, guid='a', title='금융위, 공매도 전산시스템 내년 3월 가동'),
            dict(base, guid='a2', title='금융위 공매도 전산시스템 내년 3월부터 가동'),
            dict(base, guid='b', title='기재부 세법 개정안 국무회의 통과'),
            dict(base, guid='c', title='공정위 플랫폼 규제 시행령 입법예고')]
    chosen = N.select(N.dedupe(rows))
    assert 'a2' not in [r['guid'] for r in chosen]
    spares = N.with_spares(rows, chosen)
    assert [(r['guid'], r['spare_for']) for r in spares] == [('a2', 'a')]
    pool = chosen + spares
    for r in pool:
        r['body_chars'] = 900
    assert 'a2' not in [r['guid'] for r in N.trim([dict(r) for r in pool], '2026-11-06')]
    failed = [dict(r, body_chars=0) if r['guid'] == 'a' else dict(r) for r in pool]
    assert sorted(r['guid'] for r in N.trim(failed, '2026-11-06')) == ['a2', 'b', 'c']
