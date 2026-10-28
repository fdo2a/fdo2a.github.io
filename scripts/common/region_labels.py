"""국내/해외 라벨 정의와 Jev 요청·응답 — 일본·US·KR 이 같이 쓴다 (2026-10-28).

**일본 정의·질문은 섀도·평가(2026-10-27, 359건)에서 쓴 문자열 그대로다** — 바이트가 바뀌면 섀도 설정 지문과
평가가 무효가 된다(`japan/tests/test_region_shadow.py` 가 고정값으로 지킨다). US·KR 정의는 같은 3라벨·같은
우선순위(그 나라 주어 → 그 나라 영향 명시 → 그 밖)를 시장별로 옮겼다. US 는 미국의 대외 정책을, KR 은 한국
투자자의 해외 투자를 국내로 친다. 응답 모델 문자열은 버전 모양만 받는다 — 커밋되는 파일로 간다.

Pure — 네트워크 없음.
"""
import hashlib
import math
import re

LABELS = ('domestic', 'foreign_impact', 'foreign')
JEV_MODEL = 'jev-1.14.0'     # 별칭(jev-latest)은 릴리스마다 움직인다 — 평가한 버전으로 고정(docs.typesafe.ai/models)
QUESTION = 'region'

# 두 모델이 같은 정의를 읽는다(#8). 우선순위: 일본 주어 → 일본 영향 명시 → 그 밖의 해외.
_JP_DEFINITIONS = {
    'domestic': ('The main subject is Japan: the Japanese government or a minister, the Bank of Japan, '
                 'a Japanese company, Japanese markets (Nikkei, TOPIX, JGBs, the yen) or Japanese economic data. '
                 'Choose this even when a foreign factor is also mentioned.'),
    'foreign_impact': ('The main subject is a foreign actor or event, and the headline explicitly states an '
                       'effect on Japan, a Japanese company or Japanese markets.'),
    'foreign': ('The main subject is a foreign actor or event (another government, central bank, company, '
                'market or data release) and the headline does not mention Japan. Regional headlines about '
                'Asia that do not name Japan are foreign.'),
}
_JP_INSTRUCTIONS = ('This is a Japanese financial news headline. Decide whose economy it is about. '
                'Precedence: if the main subject is Japanese, answer domestic; otherwise, if the headline names '
                'an effect on Japan, answer foreign_impact; otherwise answer foreign.')
_US_DEFINITIONS = {
    'domestic': ('The main subject is the United States: the US government, Congress, courts or a US official, '
                 'the Federal Reserve, a US company, US markets (S&P 500, Nasdaq, Treasuries, the dollar) or US '
                 'economic data. US policy toward another country (tariffs, sanctions, deals) is domestic. '
                 'Choose this even when a foreign factor is also mentioned.'),
    'foreign_impact': ('The main subject is a foreign actor or event, and the headline explicitly states an '
                       'effect on the United States, a US company or US markets.'),
    'foreign': ('The main subject is a foreign actor or event (another government, central bank, company, '
                'market or data release) and the headline does not mention the United States.'),
}
_US_INSTRUCTIONS = ('This is a US financial news headline. Decide whose economy it is about. '
                    'Precedence: if the main subject is American, answer domestic; otherwise, if the headline '
                    'names an effect on the United States, answer foreign_impact; otherwise answer foreign.')
_KR_DEFINITIONS = {
    'domestic': ('The main subject is South Korea: the Korean government, National Assembly or a minister, '
                 'the Bank of Korea, a Korean company, Korean markets (KOSPI, KOSDAQ, the won) or Korean economic '
                 'data. Korean investors and their overseas investing are domestic. '
                 'Choose this even when a foreign factor is also mentioned.'),
    'foreign_impact': ('The main subject is a foreign actor or event, and the headline explicitly states an '
                       'effect on South Korea, a Korean company, Korean investors or Korean markets.'),
    'foreign': ('The main subject is a foreign actor or event (another government, central bank, company, '
                'market or data release) and the headline does not mention South Korea or Korean investors.'),
}
_KR_INSTRUCTIONS = ('This is a Korean financial news headline. Decide whose economy it is about. '
                    'Precedence: if the main subject is Korean, answer domestic; otherwise, if the headline names '
                    'an effect on South Korea or Korean investors, answer foreign_impact; otherwise answer foreign.')
MARKETS = {'japan': {'definitions': _JP_DEFINITIONS, 'instructions': _JP_INSTRUCTIONS},
           'us': {'definitions': _US_DEFINITIONS, 'instructions': _US_INSTRUCTIONS},
           'kr': {'definitions': _KR_DEFINITIONS, 'instructions': _KR_INSTRUCTIONS}}
# 버전 모양만 — 응답 문자열이 커밋되는 파일로 간다. 「jev-SECRET」 같은 자유 문자열은 형식 오류(재검토 2차 #1)
_JEV_MODEL_ID = re.compile(r'jev-\d{1,3}\.\d{1,3}\.\d{1,3}')
def safe_claude_model(model, requested):
    """Haiku 응답의 model — **요청한 모델 그 자체이거나 그 날짜 스냅숏(`-YYYYMMDD`)일 때만** 저장, 아니면 'other'.
    모양만 보면 「claude-…」 모양의 자유 문자열이 커밋된다(US·KR 구현 검토 #1)."""
    if isinstance(model, str) and isinstance(requested, str) and (
            model == requested or re.fullmatch(re.escape(requested) + r'-\d{8}', model)):
        return model
    return 'other'


def title_key(title):
    return hashlib.sha256((title or '').encode('utf-8')).hexdigest()[:16]


class SchemaError(ValueError):
    pass



def jev_body(title, market='japan', model=JEV_MODEL):
    m = MARKETS[market]
    return {'model': model, 'state': title,
            'questions': {QUESTION: {'type': 'choice', 'instructions': m['instructions'],
                                     'criteria': dict(m['definitions'])}}}


def parse_jev(resp):
    """→ (label, probabilities, confidence, 응답 모델). 모양이 다르면 SchemaError — 제3자가 아닌 공식 문서
    형식(docs.typesafe.ai/api/system-one)이지만 방어적으로 본다."""
    try:
        ans = resp['answers'][QUESTION]
        label, probs, conf = ans['choice'], ans['probabilities'], ans.get('confidence')
    except (KeyError, TypeError):
        raise SchemaError('shape') from None
    if ans.get('type') != 'choice':
        raise SchemaError('type')
    if label not in LABELS or not isinstance(probs, dict) or set(probs) != set(LABELS):
        raise SchemaError('labels')
    vals = list(probs.values())
    if not all(_unit(v) for v in vals):
        raise SchemaError('prob')
    if abs(sum(vals) - 1) > 0.02:
        raise SchemaError('sum')
    if probs[label] < max(vals) - 1e-9:                 # 고른 것이 최대 확률이어야 한다(동률 허용)
        raise SchemaError('argmax')
    if not _unit(conf):                                 # 문서상 Choice 는 늘 confidence 를 준다
        raise SchemaError('confidence')
    model = resp.get('model')
    # 「jev-…」 모양만 — 응답 문자열이 커밋되는 판정·감사 파일로 간다(재검토 #2)
    if not (isinstance(model, str) and _JEV_MODEL_ID.fullmatch(model)):
        raise SchemaError('model')
    return label, {k: round(float(v), 4) for k, v in probs.items()}, conf, model


def _unit(v):
    """[0, 1] 의 유한한 실수 — bool 은 int 의 하위형이라 따로 뺀다."""
    # 범위를 먼저 — 10**400 같은 int 는 isfinite 에서 OverflowError 다(codex 구현 검토 #3)
    return isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 1 and math.isfinite(v)
