"""ETF 리스크 팩터 분해 — 모니터링 비중을 «역산»한다.

2026-09-01 사용자 지시. 「'미국 상장 ETF를 쓴다'는 이유만으로 독일·영국 금리를 매일
동등한 비중으로 볼 필요는 없다. 중요한 것은 ETF의 상장 국가가 아니라 underlying
exposure다.」

그래서 무엇을 얼마나 볼지를 **선언하지 않고 계산한다.** 각 ETF 의 수익률을 결정하는
팩터로 쪼갠 뒤 벤치마크 비중을 곱하면 모니터링 비중이 나온다. 벤치마크가 바뀌면
모니터링 비중도 따라 바뀌고, 그게 맞다 — 글로벌 ex-US 가 5% 뿐인 책에서 분트를
매일 깊게 파는 것은 시간 배분 오류다.

숫자는 근사다. 정확한 팩터 민감도는 회귀로 추정해야 하지만, 「무엇을 더 봐야 하는가」를
가르는 데에는 이 정도 해상도로 충분하고, **근사라는 사실을 페이지에 밝힌다.**
"""

FACTOR_KO = {
    'us_rates': '미국 금리',
    'credit': '크레딧 스프레드',
    'em': 'EM 국가위험',
    'foreign_rates': '해외 금리',
    'fx': '환율',
    'inflation': '기대인플레',
}

# 만기 구간 — 같은 「미국 금리」라도 커브의 어디를 타느냐가 다르다.
SEGMENT_KO = {'front': '프런트엔드', 'belly': '벨리', 'long': '롱엔드',
              'broad': '전 구간', 'none': '해당 없음'}

# ticker -> (팩터 가중치, 커브 구간). 가중치 합은 1.
# 근거: 각 상품의 듀레이션·기초자산 구성. 예컨대 HYG 는 듀레이션이 2년 안쪽이라
# 금리보다 스프레드가 수익률을 지배하고, IGOV 는 환헤지가 없어 환이 절반 가까이다.
FACTORS = {
    'GOVT': ({'us_rates': 1.00}, 'broad'),
    'SHY':  ({'us_rates': 1.00}, 'front'),
    'IEF':  ({'us_rates': 1.00}, 'belly'),
    'TLT':  ({'us_rates': 1.00}, 'long'),
    'AGG':  ({'us_rates': 0.85, 'credit': 0.15}, 'broad'),
    'TIP':  ({'us_rates': 0.70, 'inflation': 0.30}, 'belly'),
    'STIP': ({'us_rates': 0.40, 'inflation': 0.60}, 'front'),
    'LQD':  ({'us_rates': 0.70, 'credit': 0.30}, 'belly'),
    'IGIB': ({'us_rates': 0.70, 'credit': 0.30}, 'belly'),
    'USIG': ({'us_rates': 0.70, 'credit': 0.30}, 'belly'),
    'HYG':  ({'us_rates': 0.25, 'credit': 0.75}, 'front'),
    'SHYG': ({'us_rates': 0.15, 'credit': 0.85}, 'front'),
    'EMB':  ({'us_rates': 0.45, 'em': 0.55}, 'belly'),
    'EMHY': ({'us_rates': 0.25, 'em': 0.75}, 'belly'),
    'IGOV': ({'foreign_rates': 0.55, 'fx': 0.45}, 'belly'),
    'IAGG': ({'foreign_rates': 0.75, 'credit': 0.10, 'fx': 0.15}, 'belly'),
    'FLOT': ({'credit': 0.60, 'us_rates': 0.40}, 'front'),
}


def factors_of(ticker):
    return FACTORS.get(ticker, ({}, 'none'))[0]


def segment_of(ticker):
    return FACTORS.get(ticker, ({}, 'none'))[1]


def decompose(weights):
    """[(ticker, weight), ...] -> 팩터별 노출.

    weights 는 벤치마크 바스켓이다. 실제 책이 있으면 그걸 넣으면 된다 —
    이 함수는 무엇이 들어오든 같은 방식으로 역산한다.
    """
    out, unknown = {}, []
    for ticker, w in weights:
        f = factors_of(ticker)
        if not f:
            unknown.append(ticker)
            continue
        for name, share in f.items():
            out[name] = out.get(name, 0.0) + w * share
    total = sum(out.values()) or 1.0
    rows = [{'factor': k, 'factor_ko': FACTOR_KO.get(k, k),
             'weight': round(v, 4), 'pct': round(v / total * 100, 1)}
            for k, v in out.items()]
    rows.sort(key=lambda r: -r['weight'])
    return {'factors': rows, 'unknown': unknown, 'covered': round(total, 4)}


def monitor_plan(weights):
    """팩터 노출 -> 그날 아침 무엇을 얼마나 볼지.

    팩터를 감시 대상으로 옮기는 사전이다. 「미국 금리」는 커브·연준 가격책정·MOVE 로,
    「크레딧」은 IG/HY OAS 로 내려간다. 이 사전이 있어야 「분트를 왜 보는가」에
    답할 수 있다 — 해외 금리 노출이 8% 면 8% 만큼만 본다.
    """
    dec = decompose(weights)
    watch = {
        'us_rates': ['미국 국채 2Y·5Y·10Y·30Y', '2s10s·5s30s', '연준 가격책정·SOFR', 'MOVE'],
        'credit': ['미국 IG·HY OAS', '등급별 분산'],
        'em': ['EM 국공채·회사채 OAS'],
        'fx': ['달러지수·주요 통화쌍', '환헤지 비용'],
        'foreign_rates': ['분트 2Y·10Y', 'JGB 10Y', '길트 10Y'],
        'inflation': ['기대인플레·실질금리'],
    }
    for r in dec['factors']:
        r['watch'] = watch.get(r['factor'], [])
        r['depth'] = ('매일 깊게' if r['pct'] >= 25 else
                      '매일' if r['pct'] >= 10 else
                      '방향만 확인')
    return dec


def per_etf(tickers):
    """상품별 분해를 **발행본이 인쇄하는 단위(%)로** 내려보낸다.

    렌더 시점에 0.85 를 85% 로 바꾸면 그 값이 어느 데이터 파일에도 없어서 게이트가
    창작으로 잡는다. 지면에 나갈 형태로 여기서 만든다.
    """
    out = []
    for t in tickers:
        f = factors_of(t)
        if not f:
            continue
        out.append({
            'ticker': t,
            'segment_ko': SEGMENT_KO[segment_of(t)],
            'factors': [{'factor': k, 'factor_ko': FACTOR_KO.get(k, k),
                         'pct': round(v * 100, 1)}
                        for k, v in sorted(f.items(), key=lambda x: -x[1])],
        })
    return out


# --- 동조/이탈 판정 --------------------------------------------------------
# 해외 금리를 매일 보는 **유일한 정당한 이유**가 이것이다. 미국 10년물이 +10bp 인데
# 분트도 +10bp 면 글로벌 듀레이션 매도이고, 미국만 움직였으면 연준·물가·국채 발행 같은
# 미국 고유 요인을 먼저 의심한다. 대응이 갈리므로 판정이 필요하고, 판정은 산술이므로
# 기계가 한다.

CO_MOVE_MIN_BP = 2.0     # 이 안쪽 움직임은 방향으로 읽지 않는다
# 동조로 부르려면 해외가 미국의 절반 이상은 따라가되 두 배를 넘지 않아야 한다.
# 하한만 두면 미국 +2bp / 독일 +100bp 같은 조합도 「동조」가 된다(2026-09-01 codex 지적).
CO_MOVE_RATIO_LO = 0.5
CO_MOVE_RATIO_HI = 2.0


def divergence(us_bp, foreign_bp, label='해외'):
    if us_bp is None or foreign_bp is None:
        return None
    if abs(us_bp) < CO_MOVE_MIN_BP and abs(foreign_bp) < CO_MOVE_MIN_BP:
        return {'verdict': '둘 다 보합', 'us_bp': us_bp, 'foreign_bp': foreign_bp,
                'reading': '어느 쪽도 방향을 말할 만큼 움직이지 않았다',
                'label': label}
    same_way = (us_bp > 0) == (foreign_bp > 0)
    ratio = (abs(foreign_bp) / abs(us_bp)) if us_bp else None

    both_material = abs(us_bp) >= CO_MOVE_MIN_BP and abs(foreign_bp) >= CO_MOVE_MIN_BP
    if (same_way and both_material and ratio is not None
            and CO_MOVE_RATIO_LO <= ratio <= CO_MOVE_RATIO_HI):
        v, reading = '동조', '글로벌 듀레이션이 함께 움직인 날이다'
    elif same_way and both_material and ratio is not None and ratio < CO_MOVE_RATIO_LO:
        v, reading = ('미국 주도',
                      '같은 방향이지만 미국이 훨씬 크게 움직였다 — 미국 고유 재료를 먼저 본다')
    elif same_way and both_material:
        v, reading = (f'{label} 주도',
                      f'같은 방향이지만 {label} 쪽이 훨씬 크게 움직였다 — 그 지역 재료를 먼저 본다')
    elif abs(us_bp) >= CO_MOVE_MIN_BP and abs(foreign_bp) < CO_MOVE_MIN_BP:
        v, reading = ('미국 고유',
                      '미국만 움직였다 — 연준·물가·국채 발행·재정 쪽을 먼저 의심한다')
    elif abs(foreign_bp) >= CO_MOVE_MIN_BP and abs(us_bp) < CO_MOVE_MIN_BP:
        v, reading = (f'{label} 고유',
                      f'{label} 쪽에서만 움직였다 — 그 지역 재료를 본다')
    else:
        v, reading = '반대 방향', '두 시장이 서로 다른 쪽을 봤다'
    return {'verdict': v, 'us_bp': us_bp, 'foreign_bp': foreign_bp,
            'ratio': None if ratio is None else round(ratio, 2),
            'reading': reading, 'label': label}
