"""KR/Asia observations related to US reference indices — a static map.

This is not a lead-lag model. It names, for each reference index, the Korean
industries, stocks and Asian indices whose same-day move is worth reading before the
US open. Whether any of them predicts the US index has not been tested; the page
says so. An alias that is absent from the day's data simply yields no row.
"""

LINKS = (
    # unit_id, industries (Naver 업종명), stocks (KRX 종목명), Asian indices (kr_session peers)
    ('semis', ('반도체와반도체장비',), ('SK하이닉스', '삼성전자'), ('대만가권',)),
    ('grid', ('전기장비', '전기제품'), ('HD현대일렉트릭', 'LS ELECTRIC', '효성중공업'), ()),
    ('defense', ('우주항공과국방',), ('한화에어로스페이스', '현대로템', 'LIG디펜스앤에어로스페이스'), ()),
    ('industrials', ('기계', '조선'), ('HD현대중공업', '한화오션', '삼성중공업'), ()),
    ('metals', ('철강', '비철금속'), ('고려아연', 'POSCO홀딩스'), ()),
    ('financials', ('은행', '증권'), ('KB금융', '신한지주'), ()),
    ('software', ('소프트웨어', 'IT서비스'), ('NAVER', '카카오'), ()),
    ('energy', ('석유와가스',), ('S-Oil', 'SK이노베이션'), ()),
    ('japan', (), (), ('닛케이',)),
    ('china', (), (), ('항셍', '상해종합')),
)
