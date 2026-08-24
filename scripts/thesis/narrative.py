"""Authored summary of how the memory-investment thesis changed over time.

This is deliberately small and selective.  The monitoring conversation is source
material, not a public transcript: only changes that altered the decision framework
belong here.
"""


# 이 산문이 마지막으로 바뀐 날. 페이지의 dateModified가 여기서 온다 — 시세의 as_of를
# 쓰면 글이 그대로인 날에도 날짜만 바뀌어 매일 새 파일이 된다. PHASES를 고치면 같이 올린다.
UPDATED = '2026-08-24'

PHASES = [
    {
        'period': '출발점 · 2026년 6월',
        'title': '출발은 AI가 메모리 가격을 올린다는 경기상승 논리였다',
        'before': ('출발점은 같았다. 세 회사 모두 DRAM·NAND 가격 상승의 수혜를 받는다는 논리였다. '
                   '삼성전자의 저평가·추격 가능성, SK하이닉스의 HBM 선도력, '
                   'Micron의 미국 공급자 프리미엄에서 차이가 났다.'),
        'after': ('곧 질문이 달라졌다. 가격이 얼마나 더 오르느냐보다 이번 이익의 ‘E’가 '
                  '사이클 꼭대기인지, 계약과 제품 믹스로 오래 유지될 이익인지가 더 중요해졌다.'),
        'sources': [],
    },
    {
        'period': '첫 번째 수정 · 6월 말',
        'title': '낮은 P/E보다 이익의 지속성을 보기 시작했다',
        'before': ('과거 12개월 P/E와 단기 주가 구간으로 세 회사를 비교했다. 문제는 분모였다. '
                   '업황이 급변하는 메모리에서는 이미 지난 침체·회복이 함께 들어갔다.'),
        'after': ('Forward P/E를 중심에 두고 정상화 EPS, P/B, EV/EBITDA와 FCF를 함께 보기로 했다. '
                  '낮은 배수만 보고 싸다고 결론내리지 않기로 했다. 계약이 마진 하단과 현금흐름을 '
                  '얼마나 고정하는지도 확인하기로 했다.'),
        'sources': [],
    },
    {
        'period': '구조적 전환 · 6월 말~7월',
        'title': 'Micron의 장기계약으로 사이클보다 가시성이 중요해졌다',
        'before': ('HBM과 서버 DRAM 수요가 강해도 공급이 늘면 가격과 마진은 다시 무너질 수 있다. '
                   '전형적인 메모리 사이클을 기본값으로 둔 이유다.'),
        'after': ('Micron은 다년 take-or-pay SCA와 가격 하단·상단, 고객 예치금을 공개했다. '
                  '계약이 일부 물량의 이익 하단을 지지한다는 근거가 생겼다. 이후 SK하이닉스의 '
                  '약 10개 고객 LTA도 확인됐다. 장기계약은 한 회사의 예외에 그치지 않았다. '
                  '산업 변화의 가능성으로 커졌다.'),
        'sources': ['micron_10q', 'micron_remarks', 'sk_q2'],
    },
    {
        'period': '회사별 재평가 · 7월 말',
        'title': '싼 추격주였던 삼성전자는 상용화가 확인된 복합 옵션이 됐다',
        'before': ('삼성전자의 낮은 평가에는 이유가 있다고 봤다. HBM 고객 승인과 양산 성과가 '
                   '부족했다. 파운드리 손실 때문에 큰 생산능력도 곧바로 이익으로 연결되지 않았다.'),
        'after': ('상용 HBM4 출하와 HBM4E 샘플, 메모리 실적 신기록, 파운드리 개선이 확인됐다. '
                  '단순 기대에 그치던 HBM 추격에 실행 증거가 붙었다. 다만 HBM4E 고객 '
                  '인증·점유율과 파운드리 수익성은 여전히 따로 증명해야 한다.'),
        'sources': ['samsung_hbm4', 'samsung_q2'],
    },
    {
        'period': '반대 증거 등장 · 7월',
        'title': '중국 공급이 측정 가능한 중기 위험으로 구체화됐다',
        'before': ('CXMT·YMTC는 장기 변수로만 취급했다. 선단 공정과 HBM 격차 때문에 '
                   '당장 3사의 핵심 이익을 훼손하기 어렵다고 봤다.'),
        'after': ('CXMT의 대형 장기계약과 월 60만 장 안팎까지의 DRAM 증설 계획이 보도됐다. '
                  '범용 DRAM의 가격·점유율 압박이 구체적인 위험이 됐다. 판단도 ‘HBM 해자와 '
                  '범용 메모리 마진을 분리해서 보자’로 바뀌었다.'),
        'sources': ['cxmt_tencent', 'cxmt_capacity'],
    },
    {
        'period': '수요 검증 · 7~8월',
        'title': '가격 전가는 확인됐지만 고객의 설계 변경이 상단을 제한한다',
        'before': ('메모리 가격이 오른 배경을 공급자의 가격결정력으로 읽었다. 고객이 서버·기기 가격을 '
                   '올려 비용을 넘길 수 있다면 고마진이 더 오래 간다고 봤다.'),
        'after': ('후속 감시에서는 고객이 가격을 받아들이는 신호가 나왔다. 동시에 메모리 탑재량을 '
                  '낮추거나 제품 구성을 바꿀 가능성도 포착됐다. 이제 ASP와 시스템당 메모리 용량, '
                  '최종 출하량을 함께 봐야 한다.'),
        'sources': ['apple_prices', 'rubin_configs'],
    },
    {
        'period': '현재 프레임 · 8월',
        'title': '주당 FCF도 판단 기준에 들어왔다',
        'before': ('판단 기준은 기술 경쟁력과 가격, 영업이익률이 거의 전부였다. 대규모 증설이나 주식보상은 '
                   '성장을 위한 부수 비용으로 취급했다.'),
        'after': ('이제 설비투자, 자사주 소각, 배당과 주식보상까지 함께 따져 기록적인 이익이 '
                  '주당 가치로 얼마나 남는지 보기 시작했다. SK하이닉스와 삼성전자의 대규모 주주환원 계획은 '
                  '이 축을 강화했지만 증설 규율과 실제 주식 수 변화는 계속 확인해야 한다.'),
        'sources': ['sk_return', 'samsung_return'],
    },
]


COMPANIES = [
    {
        'name': 'SK하이닉스',
        'start': 'HBM 선도력이 가장 뚜렷한 회사',
        'now': 'HBM4 양산과 다수 고객 LTA로 실적 가시성을 확보한 회사',
        'proof': 'HBM4E 인증·수율, 고객 다변화, 증설 뒤 정상 마진과 주당 FCF가 유지되는지',
    },
    {
        'name': 'Micron',
        'start': '미국 시장에서 AI 메모리를 추격하는 회사',
        'now': '계약 구조와 재무 가시성을 가장 구체적으로 밝힌 회사',
        'proof': 'SCA 이행·갱신, RPO 전환, 예치금의 실제 설비투자 효과, FCF가 높아진 평가를 감당하는지',
    },
    {
        'name': '삼성전자',
        'start': '낮은 평가를 받는 생산능력에 HBM 추격 옵션이 더해진 회사',
        'now': 'HBM4 상용화와 대규모 생산능력, 파운드리 회복, 자본환원을 함께 보는 복합 옵션',
        'proof': 'HBM4E 고객 인증과 점유율, 파운드리 이익, 메모리 호황 이익이 주당 가치로 남는지',
    },
]


CORRECTIONS = [
    ('TTM P/E 하나로 비교하지 않는다',
     '업황 전환기에는 과거 이익이 분모에 남는다. Forward P/E는 정상화 EPS, P/B·EV/EBITDA·FCF와 함께 본다.'),
    ('$100B를 곧바로 ‘수주잔고’라고 부르지 않는다',
     'Micron 10-Q의 2026년 5월 28일 기준 RPO는 약 $5B다. 실적 발표 자료에는 분기 말 뒤 체결분까지 포함한 SCA RPO 약 $100B와 관련 약정·예치금 $22B가 담겼다. 기준일과 회계 범위가 다른 숫자를 섞지 않는다.'),
    ('주가 급등락을 thesis 변화로 취급하지 않는다',
     '가격은 기대의 반영 정도에만 영향을 준다. 사업의 사실은 그대로다. 계약·기술·수요·공급·주당 FCF가 움직일 때만 내러티브를 수정한다.'),
]


CURRENT_FRAME = {
    'supports': [
        'HBM4·HBM4E 기술 격차와 패키징 병목은 단기간에 해소되지 않는다.',
        '다년 계약의 물량 의무와 가격 하단이 과거 사이클보다 실적 가시성을 높인다.',
        '최종 고객은 가격을 전가하면서도 시스템당 메모리 용량과 출하량을 유지한다.',
        '기록적인 현금이 무질서한 증설보다 주주환원과 수익률 높은 투자에 배분된다.',
    ],
    'breaks': [
        '계약 취소·재가격이 나타나거나 가격 하단에서도 마진이 빠르게 낮아진다.',
        'HBM 점유율·수율·ASP가 동시에 꺾이거나 고객 집중이 더 커진다.',
        '신규 팹과 중국 DRAM 공급이 수요보다 먼저 늘어 범용 가격을 압박한다.',
        '고객이 메모리 탑재량을 줄여 가격 상승을 상쇄하고 최종 출하량까지 낮춘다.',
    ],
}


BOTTOM_LINE = (
    '현재 thesis는 “메모리 가격이 오른다”가 아니다. '
    '확인할 것은 <b>장기계약이 붙은 생산능력 희소성 + HBM 기술 해자 + 고객의 가격 전가</b>가 '
    '<b>신규 증설 + 중국 공급 + 메모리 절감 설계</b>보다 오래가는지다.'
)


SOURCES = {
    'micron_10q': ('Micron FY2026 Q3 Form 10-Q',
                   'https://s25.q4cdn.com/621799436/files/doc_financials/2026/q3/0000723125-26-000015.pdf'),
    'micron_remarks': ('Micron FY2026 Q3 prepared remarks',
                       'https://s25.q4cdn.com/621799436/files/doc_financials/2026/q3/Q3-FY26-Prepared-Remarks.pdf'),
    'sk_q2': ('SK하이닉스 2Q26 실적 발표',
              'https://news.skhynix.com/en/q2-2026-business-results/'),
    'samsung_hbm4': ('삼성전자 HBM4 상용 출하 발표',
                     'https://news.samsung.com/global/samsung-ships-industry-first-commercial-hbm4-with-ultimate-performance-for-ai-computing'),
    'samsung_q2': ('삼성전자 2Q26 실적 발표',
                   'https://news.samsung.com/global/samsung-electronics-announces-second-quarter-2026-results'),
    'cxmt_tencent': ('Reuters: CXMT–Tencent 장기 공급계약',
                     'https://www.investing.com/news/stock-market-news/exclusivechinas-cxmt-wins-3-billion-memory-supply-deal-with-tencent-sources-say-4764321'),
    'cxmt_capacity': ('Reuters: 중국 메모리 업체의 가격결정력과 증설',
                      'https://www.investing.com/news/stock-market-news/chinas-memory-chip-makers-ride-ai-boom-to-new-power--and-us-scrutiny-4810472'),
    'apple_prices': ('Reuters: Apple의 메모리 비용 전가',
                     'https://www.investing.com/news/stock-market-news/apple-raises-prices-of-macbooks-ipads-as-memory-costs-skyrocket-4760683'),
    'rubin_configs': ('TrendForce: Rubin Ultra 메모리 구성 검토',
                      'https://www.trendforce.com/presscenter/news/20260804-13166.html'),
    'sk_return': ('SK하이닉스 자사주 매입·소각 계획',
                  'https://news.skhynix.com/en/share-buyback-and-retirement/'),
    'samsung_return': ('삼성전자 2026년 주주환원 계획',
                       'https://news.samsung.com/global/samsung-electronics-to-implement-largest-ever-shareholder-return-in-2026-estimated-at-krw-90-to-110-trillion'),
}
