"""모의 포트폴리오 섹션의 발행 게이트.

막는다: 데이터에 없는 수치, 고지 누락(모의 운용·설정일·벤치마크 정의·하루 시차),
        슬리브 표식 누락, 표본 미달인데 연율·샤프 인쇄, 책의 기준일 어긋남,
        내부 파일명·필드명 노출, 금지 어휘.
못 막는다: 그 수치가 정말 그 문장의 지표에 속하는지. 그럴듯한 값끼리의 뒤바뀜은
        사람이 하는 팩트체크에서 잡힌다 — 채권 게이트가 적어 둔 한계와 같다.

**닫히면서 실패한다.** 책이 없거나 기준일이 시장 데이터와 다르면 그 아래 검사는
전부 의미가 없으므로, 통과가 아니라 위반으로 돌려보낸다.
"""

import re

from common.numbers import (measure_numbers, numbers_split_by_tags,
                            numeric_tokens, text_of)

from .macro_gate import BANNED_LABELS
from .portfolio import SLEEVE_LABEL, SLEEVE_ORDER
from .weight import section_slice

SECTION_TITLE = '모의 포트폴리오'
MARKERS = ('basis', 'lag', 'perf')

# 표본이 모자랄 때 인쇄가 금지되는 말 — 2주짜리 기록을 연율로 부풀리는 것은
# 성적표가 아니라 소음이다.
RISK_WORDS = ('연율', '연환산', '연평균', '샤프', '변동성', '승률', '적중률',
              '표준편차', '정보비율', '트래킹', '하방편차', '위험조정',
              'cagr', 'sharpe', 'sortino', 'calmar', 'annualiz', 'annualis',
              'volatility', 'std dev', 'stdev', 'information ratio',
              'tracking error', 'hit rate')

INTERNAL_TOKENS = ('portfolio.json', 'portfolio_perf.json', 'portfolio_prices.json',
                   'portfolio_state.json', 'stance.json', 'stance_eval.json',
                   'research_notes.md', 'base_nav', 'bench_nav', 'nav_index',
                   'sleeve', 'contrib', 'insufficient', 'allowed_grades',
                   'instrument_weights', 'ret_pct', 'report_date', 'grades_from',
                   'spans_gap', 'units', 'stance_frozen') + SLEEVE_ORDER

EXEMPT_YEARS = {2024.0, 2025.0, 2026.0, 2027.0}

_MARKER = re.compile(r'<p[^>]*data-portfolio="(\w+)"[^>]*>(.*?)</p>', re.S)
_H2 = re.compile(r'<h2\b[^>]*>(.*?)</h2>', re.S)


def _heading_count(html):
    """제목 안의 인라인 태그를 벗겨서 센다.

    `<h2><span>모의 포트폴리오</span></h2>` 는 문자열 비교로는 다른 제목이지만
    `section_slice` 는 같은 것으로 읽는다. 세는 쪽과 자르는 쪽이 다르게 읽으면,
    숨은 사본이 검사를 통과하고 보이는 쪽이 창작을 싣는다(2026-09-01 codex 2차).
    """
    return sum(1 for m in _H2.finditer(html)
               if text_of(m.group(1)).strip() == SECTION_TITLE)

# 단위를 단 수치와 맨 숫자를 **함께** 뜯는다. 맨 숫자를 검사에서 빼면 창작한 정수가
# 그대로 실린다 — 2026-09-01 codex 검토가 「기준가는 777입니다」로 실증했다. 이
# 섹션은 짧고 전부 금융 수치라 좁은 면제로 감당할 수 있다(채권 게이트가 산문 전체를
# 상대하느라 단위 있는 수치만 보는 것과 조건이 다르다).
_NUM = re.compile(r'(-?\d[\d,]*(?:\.\d+)?)\s*'
                  r'(퍼센트\s*포인트|퍼센트|%\s*포인트|%[pP]|[%％]'
                  r'|[bB][pP][sS]?|베이시스\s*포인트)?')
# 읽을 수 없는 표기는 **통과가 아니라 위반**이다. 지수 표기(1e3)는 정규식이 1과 3으로
# 뜯어 읽어 원래 값이 검사에서 사라진다(2026-09-01 codex 3차).
_UNREADABLE = re.compile(r'\d\s*[eE]\s*[+-]?\d')
_BP_UNIT = re.compile(r'^([bB][pP][sS]?|베이시스\s*포인트)$')
# 태그는 텍스트를 뽑을 때 공백이 된다. 그래서 「2.<span>42</span>%」는 「2. 42%」가 되어
# 소수점에서 문장이 갈리고 수치도 둘로 쪼개진다 — 검사를 통째로 피해 가는 길이다
# (2026-09-01 codex 8차). 태그 하나만 보면 두 개를 붙여 빠져나가고, br 을 면제하면
# br 로 쪼갠다(9차). 그래서 **태그의 연속**을 통째로 보고, 그 안에 문단·칸을 끝내는
# 블록 태그가 하나도 없으면 «숫자 안에 낀 것»으로 판정한다.
def _normalise(text):
    """유니코드 음수 부호·전각 기호를 아스키로 되돌린다.

    「−0.02%」(U+2212)는 눈으로는 음수지만 정규식에는 부호가 없는 0.02 다.
    부호가 사라진 채 통과하는 것이 이 함수가 막는 것이다(2026-09-01 codex 3차).
    """
    # 수학 기호 마이너스만 부호로 되살린다. 앞에 공백을 넣어야 이음표 제거 규칙이
    # 「손익은−0.02%」의 부호를 다시 지우지 못한다(2026-09-01 codex 4차).
    text = text.replace('\u2212', ' -')
    # 대시류는 부호로 쓰이지 않는다 — 구간 표기이므로 구분자로 지운다.
    for ch in ('\u2013', '\u2014', '\uff0d'):
        text = text.replace(ch, ' ')
    return text.replace('\uff05', '%')


def _scan(text):
    """-> [(값, 단위 or None)]. 날짜와 이음표 하이픈은 먼저 가린다."""
    text = _normalise(text)
    masked = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', text)
    masked = re.sub(r'\d{4}년|\d{1,2}월|\d{1,2}일', ' ', masked)
    masked = re.sub(r'(?<=[^\s(\[])-', ' ', masked)
    out = []
    for m in _NUM.finditer(masked):
        try:
            out.append((round(float(m.group(1).replace(',', '')), 4), m.group(2)))
        except ValueError:
            continue
    return out


def _label_numbers():
    """슬리브 이름에 박힌 숫자(「채권 장기(7-10Y)」의 7·10)도 데이터에서 온 것이다."""
    out = set()
    for label in SLEEVE_LABEL.values():
        for raw in re.findall(r'\d+(?:\.\d+)?', label):
            out.add(round(float(raw), 4))
    return out


def section(html):
    return section_slice(html, SECTION_TITLE)


def data_tokens(book, perf):
    """발행본이 인용해도 되는 수치 — 책과 성과 파일에서 나온 것뿐이다."""
    return numeric_tokens(book, perf)


def rate_tokens(perf):
    """**퍼센트로 인쇄해도 되는** 수치만.

    전체를 한 집합에 뭉쳐 두면 단위가 세탁된다 — 기준가 988.36 이 「988.36% 올랐다」로
    통과했다(2026-09-01 codex 검토). 비율은 비율 필드에서만 나와야 한다.
    """
    perf = perf or {}
    return numeric_tokens(perf.get('returns'), perf.get('contrib'),
                          perf.get('weights'), perf.get('residual_pct'),
                          perf.get('max_drawdown_pct'))


def _date_forms(iso):
    if not iso:
        return ()
    m = re.match(r'(\d{4})-(\d{2})-(\d{2})$', str(iso))
    if not m:
        return (str(iso),)
    _, mm, dd = m.groups()
    return (str(iso), f'{int(mm)}월 {int(dd)}일')


def check(html, book, perf, market_report_date):
    """-> 위반 목록. 빈 리스트면 발행 가능."""
    errs = []
    if not book or not perf:
        errs.append('포트폴리오 데이터가 없다 — 섹션을 실을 수 없다')
        return errs

    rd = book.get('report_date')
    if not rd:
        errs.append('포트폴리오 책에 기준일이 없다')
    elif market_report_date and rd != market_report_date:
        errs.append(f'포트폴리오 기준일 불일치: {rd} != {market_report_date}')

    if _heading_count(html) > 1:
        errs.append('「모의 포트폴리오」 제목이 두 번 이상 나온다 — 숨은 사본이 '
                    '검사를 통과하고 보이는 쪽이 창작을 실을 수 있다')
    sec = section(html)
    if not sec:
        errs.append(f'「{SECTION_TITLE}」 섹션이 없다')
        return errs
    if len(_MARKER.findall(html)) != len(_MARKER.findall(sec)):
        errs.append('섹션 밖에 data-portfolio 표식이 있다')
    sec_text = text_of(sec)
    doc_text = text_of(html)
    low = sec_text.lower()

    for word in BANNED_LABELS:
        if word.lower() in doc_text.lower():
            errs.append(f'금지 어휘: {word}')
    for tok in INTERNAL_TOKENS:
        if tok.lower() in low:
            errs.append(f'내부 용어 노출: {tok}')

    blocks = {k: text_of(v) for k, v in _MARKER.findall(sec)}
    for name in MARKERS:
        if not (blocks.get(name) or '').strip():
            errs.append(f'표식 없음 또는 비어 있음: data-portfolio="{name}"')

    basis = blocks.get('basis', '')
    if '모의' not in basis:
        errs.append('모의 운용이라는 고지가 없다 — 실계좌로 읽힌다')
    if not any(f in basis for f in _date_forms(perf.get('inception'))):
        errs.append(f'설정일({perf.get("inception")})이 고지 문단에 없다')
    if '중립' not in basis:
        errs.append('벤치마크 정의(중립 책)가 고지 문단에 없다')
    if '다음 거래일' not in blocks.get('lag', ''):
        errs.append('하루 시차 고지가 없다 — 오늘 바뀐 등급이 언제 반영되는지가 빠졌다')

    # 「어느 날 정한 등급인가」를 본문이 다른 날로 말하면 시차 고지가 거짓이 된다.
    # 2026-09-01 실측: 정본은 8월 28일인데 발행본은 8월 31일이라고 썼다.
    applied = book.get('grades_from')
    if applied:
        ok = {f.replace(' ', '') for f in _date_forms(applied)}
        # 첫 주장만 보면 뒤에 붙인 두 번째 주장이 그대로 실린다. 전부 본다.
        # **자수 창은 두지 않는다** — 24자로 잡으면 25자로, 60자로 잡으면 61자로
        # 빠져나간다(2026-09-01 codex 4·5차). 「정한 등급」이 든 문장 안의 날짜는
        # 전부 출처 주장으로 보고, 그래서 그 문장에 적용일 말고 다른 날짜를 쓰지
        # 않는다는 것이 작성 규칙이 된다.
        # 숫자 **사이**의 마침표만 문장 끝이 아니다 — 「-1.16%」의 점에서 문장이
        # 갈리면 그 뒤의 잘못된 출처 주장이 빠져나가고(codex 6차), 반대로 물음표·
        # 느낌표까지 보호하면 「1024.27? 8월 28일에…」가 한 문장으로 붙어 멀쩡한
        # 글을 막는다(codex 7차). 보호는 마침표에만 건다.
        for sentence in re.split(r'(?:\.(?!\d)|[。!?])\s*', sec_text):
            if '정한 등급' not in sentence:
                continue
            for claim in re.findall(
                    r'\d{4}-\d{2}-\d{2}|\d{1,2}\s*월\s*\d{1,2}\s*일', sentence):
                if claim.replace(' ', '') not in ok:
                    errs.append(f'적용한 등급 책의 날짜가 다르다: 본문 {claim} != '
                                f'{applied}')

    # 성과 문단은 **실제 성과 수치를 들고 있어야** 한다. 비어 있지만 않으면 되게
    # 두면 「수치는 다음에 확인하겠습니다」가 통과한다(2026-09-01 codex 검토).
    itd = (perf.get('returns') or {}).get('itd') or {}
    said = {v for v, _ in _scan(blocks.get('perf', ''))}
    for field in ('portfolio', 'active'):
        value = itd.get(field)
        if value is None:
            continue
        if not any(round(value, d) in said for d in (1, 2, 3, 4)):
            errs.append(f'성과 문단(data-portfolio="perf")에 설정 이후 {field} 수치가 '
                        f'없다 — 약속만으로는 성과가 아니다')

    held = {w['sleeve'] for w in (perf.get('weights') or [])
            if (w.get('weight_pct') or 0) > 0}
    marked = set(re.findall(r'data-sleeve="(\w+)"', sec))
    for key in SLEEVE_ORDER:
        if key in held and key not in marked:
            errs.append(f'보유 중인 슬리브에 표식이 없다: {key}')
    for key in sorted(marked - set(SLEEVE_ORDER)):
        errs.append(f'알 수 없는 슬리브 표식: {key}')

    # 성과는 원장에서만 나온다. 스냅샷이 원장과 다른 날을 가리키면 어제 성적에
    # 오늘 날짜가 붙는다(2026-09-01 codex 검토).
    as_of = book.get('as_of')
    if not as_of:
        errs.append('책에 원장 기준일(as_of)이 없다 — 신선도를 검사할 수 없다')
    if not perf.get('sessions'):
        errs.append('원장이 비어 있다 — 성과로 말할 거래일이 없다')
    if perf.get('report_date') and as_of and perf['report_date'] != as_of:
        errs.append(f'성과가 원장의 다른 날을 가리킨다: {perf["report_date"]} != {as_of}')
    if as_of and rd and as_of > rd:
        errs.append(f'원장이 기준일보다 앞선다: {as_of} > {rd}')

    # 원장이 멈췄으면 **멈춘 날짜와 빠진 날짜를 이름으로** 밝힌다. 「결측」 한 단어로
    # 끝나면 독자가 무엇이 빠졌는지 알 수 없다.
    if as_of and rd and as_of != rd:
        if '결측' not in sec_text:
            errs.append(f'원장이 {as_of}에서 멈췄는데 결측 사실이 본문에 없다')
        if not any(f in sec_text for f in _date_forms(as_of)):
            errs.append(f'원장이 멈춘 날({as_of})이 본문에 없다')
    inception = perf.get('inception') or ''
    for gap in (book.get('gaps') or []):
        if gap <= inception or (as_of and gap > as_of):
            continue                       # 운용 구간 밖의 결측은 이 책과 무관하다
        if not any(f in sec_text for f in _date_forms(gap)):
            errs.append(f'원장에서 빠진 날({gap})이 본문에 없다')

    if book.get('stance_frozen') and '동결' not in sec_text:
        errs.append('등급 책을 받지 못해 비중을 동결했는데 그 사실이 본문에 없다')

    if perf.get('insufficient'):
        for word in RISK_WORDS:
            if word in low:
                errs.append(f'표본 부족({perf.get("sessions")}거래일)인데 「{word}」을(를) '
                            f'인쇄했다 — {perf.get("min_sessions")}거래일 전에는 금지')

    # **맨 숫자는 레벨·개수 집합에서만** 나올 수 있다. 전체를 한 집합으로 두면
    # 수익률 -1.16 이 「기준가는 -1.16」으로 되살아난다(2026-09-01 codex 2차).
    levels = numeric_tokens(perf.get('nav'), perf.get('bench_nav'),
                            perf.get('base_nav'), book.get('base_nav'),
                            perf.get('sessions'), perf.get('min_sessions'),
                            perf.get('grades'))
    levels |= _label_numbers() | EXEMPT_YEARS
    rates = rate_tokens(perf)
    invented, laundered, wrong_unit = [], [], []
    for value, unit in _scan(sec_text):
        if abs(value) <= 0.001:
            continue
        if unit and _BP_UNIT.match(unit):
            wrong_unit.append(f'{value}{unit}')
        elif unit and value not in rates:
            laundered.append(f'{value}{unit}')
        elif not unit and value not in levels:
            invented.append(value)
    for run in numbers_split_by_tags(sec)[:4]:
        errs.append(f'수치 사이에 태그가 끼어 있다({run.strip()[:40]}) — '
                    f'검사를 피해 가므로 허용하지 않는다')
    for m in _UNREADABLE.finditer(_normalise(sec_text)):
        errs.append(f'읽을 수 없는 수치 표기: {m.group(0)} — 지수 표기는 쓰지 않는다')
    if wrong_unit:
        errs.append('이 섹션은 bp 로 인쇄하는 값이 없다: ' + ', '.join(sorted(set(wrong_unit))))
    if laundered:
        errs.append('비율로 인쇄됐지만 비율 데이터에 없는 수치: '
                    + ', '.join(sorted(set(laundered))[:12]))
    if invented:
        errs.append('데이터에 없는 수치: '
                    + ', '.join(str(v) for v in sorted(set(invented))[:12]))
    return errs
