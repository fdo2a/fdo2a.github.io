"""일본 일간 움직인 종목 — 고정 대형주 표본의 등락률만 (2026-10-27).

닛케이 225 는 주가 가중, TOPIX 는 유동주식 시총 가중이라 표본의 「시총 × 등락률」 을 지수 기여로
부르면 틀린다(codex 설계 검토 #12). 그래서 기여 개념을 쓰지 않는다 — 등락률 상위 2·하위 2 와
|등락| ≥ 5% 를 뽑아 (TOPIX-17 업종, 방향)으로 묶는다. 묶음은 `common.movers.group_movers` 를
그대로 쓰고(US/KR 경로는 바꾸지 않는다), 출력 모양은 `common.movers.check` 가 읽는 그대로다.
원인은 일간 뉴스 근거가 있을 때만 쓰고, 없으면 본문이 「확인된 재료 없음」 이라고 쓴다.

표본·업종은 상수다. 업종은 TOPIX-17(NEXT FUNDS 1617-1633 과 같은 분류)의 한국어 이름.
Pure — 네트워크 없음.
"""
from common import movers as CM

THRESHOLD_PCT = CM.THRESHOLD_PCT
TOP_N = 2
UP, DOWN, OUTLIER = '등락 상위', '등락 하위', '이상 등락'
UNIVERSE_NAME = '일본 대형주 고정 표본'

SECTOR17 = {
    '1617': '식품', '1618': '에너지자원', '1619': '건설·자재', '1620': '소재·화학',
    '1621': '의약품', '1622': '자동차·수송기', '1623': '철강·비철', '1624': '기계',
    '1625': '전기·정밀', '1626': '정보통신·서비스', '1627': '전력·가스', '1628': '운수·물류',
    '1629': '상사·도매', '1630': '소매', '1631': '은행', '1632': '금융(은행 제외)', '1633': '부동산',
}
_S = SECTOR17

UNIVERSE = (
    ('7203', '도요타', _S['1622']), ('7267', '혼다', _S['1622']), ('6902', '덴소', _S['1622']),
    ('6758', '소니그룹', _S['1625']), ('6501', '히타치', _S['1625']), ('6861', '키엔스', _S['1625']),
    ('8035', '도쿄일렉트론', _S['1625']), ('6857', '어드밴테스트', _S['1625']),
    ('6981', '무라타제작소', _S['1625']), ('6503', '미쓰비시전기', _S['1625']), ('7741', 'HOYA', _S['1625']),
    ('8306', '미쓰비시UFJ', _S['1631']), ('8316', '스미토모미쓰이FG', _S['1631']), ('8411', '미즈호FG', _S['1631']),
    ('8766', '도쿄해상', _S['1632']),
    ('9983', '패스트리테일링', _S['1630']),
    ('9984', '소프트뱅크그룹', _S['1626']), ('9432', 'NTT', _S['1626']), ('9433', 'KDDI', _S['1626']),
    ('9434', '소프트뱅크', _S['1626']), ('7974', '닌텐도', _S['1626']), ('6098', '리쿠르트', _S['1626']),
    ('4661', '오리엔탈랜드', _S['1626']),
    ('8058', '미쓰비시상사', _S['1629']), ('8031', '미쓰이물산', _S['1629']), ('8001', '이토추상사', _S['1629']),
    ('4063', '신에쓰화학', _S['1620']), ('4452', '가오', _S['1620']),
    ('4568', '다이이치산쿄', _S['1621']), ('4502', '다케다약품', _S['1621']), ('4519', '주가이제약', _S['1621']),
    ('6954', '화낙', _S['1624']), ('6367', '다이킨공업', _S['1624']), ('7011', '미쓰비시중공업', _S['1624']),
    ('6146', '디스코', _S['1624']),
    ('8801', '미쓰이부동산', _S['1633']), ('8802', '미쓰비시지쇼', _S['1633']),
    ('5401', '일본제철', _S['1623']), ('1605', 'INPEX', _S['1618']), ('9020', 'JR동일본', _S['1628']),
    ('9501', '도쿄전력', _S['1627']), ('2914', 'JT', _S['1617']), ('1925', '다이와하우스', _S['1619']),
)
_SECTOR_OF = {code: sector for code, _, sector in UNIVERSE}


def _candidates(rows, threshold):
    rows = [r for r in rows or [] if isinstance(r.get('change_pct'), (int, float))]
    ups = sorted((r for r in rows if r['change_pct'] > 0), key=lambda r: -r['change_pct'])[:TOP_N]
    downs = sorted((r for r in rows if r['change_pct'] < 0), key=lambda r: r['change_pct'])[:TOP_N]
    reasons = {}
    for r in ups:
        reasons.setdefault(r['code'], []).append(UP)
    for r in downs:
        reasons.setdefault(r['code'], []).append(DOWN)
    for r in rows:
        if abs(r['change_pct']) >= threshold:
            reasons.setdefault(r['code'], []).append(OUTLIER)
    # group_movers 는 기여가 없으면 `value` 순으로 줄 세운다 — 여기선 |등락률| 을 넣는다.
    return [{'name': r['name'], 'change_pct': r['change_pct'], 'close': r.get('close'),
             'value': abs(r['change_pct']), 'industry': _SECTOR_OF.get(r['code']),
             'reasons': reasons[r['code']], 'score': None}
            for r in rows if r['code'] in reasons]


def build(session, rows, threshold=THRESHOLD_PCT, max_groups=CM.MAX_GROUPS):
    groups = CM.group_movers(_candidates(rows, threshold), max_groups)
    for g in groups:
        for m in g['members']:
            m.pop('value', None)
    return {'report_date': session, 'universe': UNIVERSE_NAME, 'threshold_pct': threshold,
            'groups': groups}
