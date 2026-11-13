# Ported from fdo2a/telegram-shadow shadow/market.py (2026-11-06). Diverged 2026-11-12: KR_NAMES below
# exists only here (the shadow repo was not updated).
"""Which market a post speaks to. Code rules only; misclassification is measured in the sample."""
import re

# Full corporate names only (2026-11-12). A bare group prefix (현대, 삼성, 한화, SK, LG) matches
# 「현대화」「한화로 3조 원」「SK온라인」 and would pull a US post out of the US candidates. 두산 alone is
# allowed with a boundary on both sides (a particle or punctuation may follow).
KR_NAMES = (r'SK실트론|SK이노베이션|SK텔레콤|삼성SDI|삼성전기|삼성바이오로직스|LG전자|LG화학|LG디스플레이|LG이노텍|'
            r'현대모비스|현대중공업|HD현대|한화에어로스페이스|한화솔루션|한화오션|두산에너빌리티|두산밥캣|두산로보틱스|'
            r'포스코홀딩스|POSCO|한국전력|한미반도체|(?<![가-힣])두산(?=[은는이가을를의와과도,·\s]|$)')
KR_RE = re.compile(r'(?<!\d)\d{6}(?!\d)|코스피|코스닥|KOSPI|KOSDAQ|원/달러|원·달러|원화|국장|'
                   r'한국은행|금통위|금융위|금감원|기재부|국민연금|외국인 순매|삼성전자|SK하이닉스|하이닉스|'
                   r'현대차|LG에너지|셀트리온|카카오|네이버|NAVER|KRX|국내 증시|국내증시|' + KR_NAMES)
US_RE = re.compile(r'\$[A-Z]{1,5}\b|S&P|나스닥|NASDAQ|Nasdaq|다우|러셀|연준|Fed\b|FOMC|파월|'
                   r'미 국채|미국채|미 10년|뉴욕증시|미국 증시|미국증시|월가|엔비디아|Nvidia|NVIDIA|'
                   r'애플|마이크로소프트|아마존|알파벳|구글|메타|테슬라|AMD|마이크론|브로드컴|오픈AI|OpenAI|'
                   r'앤스로픽|Anthropic|트럼프|백악관|재무부|SEC\b')


def market_of(text, default):
    """default is the channel's market. 'both' channels are decided per post."""
    if default in ('kr', 'us'):
        return default
    kr, us = bool(KR_RE.search(text or '')), bool(US_RE.search(text or ''))
    if kr and us:
        return 'both'
    if kr:
        return 'kr'
    if us:
        return 'us'
    return 'unknown'


def in_market(post_market, market):
    return post_market == market or post_market == 'both'
