"""KR 뉴스 국내/해외 필터 (2026-10-28) — 주요뉴스 행만, dedupe 전, 글로벌 사본 보존."""
import fetch_kr_news as FK
from common import region_labels as L
from kr import news as N


def _ans(label='foreign', conf=1.0):
    probs = {k: 0.0 for k in L.LABELS}
    probs[label] = 1.0
    return {'model': L.JEV_MODEL, 'answers': {'region': {'type': 'choice', 'choice': label, 'confidence': conf,
                                                          'probabilities': probs}}}


def _poster(foreign):
    seen = []

    def post(body, key, timeout=None):
        seen.append(body)
        return _ans('foreign') if body['state'] in foreign else _ans('domestic')
    post.seen = seen
    return post


def _main(guid, title):
    return {'guid': guid, 'url': f'https://n.news.naver.com/mnews/article/{guid}', 'title': title,
            'source': '연합뉴스', 'published': '2026-10-28T15:00:00+09:00'}


IBM = "'7월 악몽'서 깨어난 IBM, 호실적에 반등"
KOSPI = '외국인 1조 팔자에 코스피 2% 하락'
BOJ = '일본은행 금리 인상 시사…엔화 강세에 수출주 긴장'


def test_drops_foreign_main_rows_and_returns_untagged_rows(monkeypatch):
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    rows = [_main('1-1', IBM), _main('1-2', KOSPI)]
    kept, meta = FK.apply_region_filter([dict(r) for r in rows], post=_poster({IBM}))
    assert kept == [rows[1]]                                    # 갈래를 붙이지 않은 원래 행
    assert meta['market'] == 'kr' and [d['guid'] for d in meta['dropped']] == ['1-1']


def test_world_copy_reaches_global_when_main_copy_is_dropped(monkeypatch):
    """설계 검토 #2 — 주요뉴스 사본이 빠져도 세계 섹션 사본이 dedupe 를 지나 글로벌로 간다."""
    monkeypatch.setenv('TYPESAFE_API_KEY', 'k')
    main = _main('9-9', BOJ)
    world = dict(_main('9-9', BOJ), feed='world')
    kept, _ = FK.apply_region_filter([main], post=_poster({BOJ}))
    cats = N.categorize(N.dedupe(kept + [world]))
    assert [(r['guid'], r['category']) for r in cats] == [('9-9', 'global')]


def test_kr_definitions_count_korean_investors_abroad_as_domestic():
    assert 'Korean investors and their overseas investing are domestic' in L.MARKETS['kr']['definitions']['domestic']


def test_no_key_is_todays_result(monkeypatch):
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    rows = [_main('1-1', IBM), _main('1-2', KOSPI)]
    kept, meta = FK.apply_region_filter(rows, post=lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert kept == rows and meta['stopped'] == 'no_key'
