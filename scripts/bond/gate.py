"""발행 게이트 — 채권 리포트가 넘어서는 안 되는 선.

게이트가 막는 것과 못 막는 것을 분명히 해 둔다.

  막는다: 데이터에 없는 수치, 통제 어휘 밖의 등급 라벨, 규율이 허용하지 않은 등급,
          내부 파일명·필드명 노출, 금지 어휘, 미완 마커, 기준일 없는 표,
          판단이 시황보다 길어지는 무게중심 역전.
  못 막는다: 분석의 질. 패딩과 형식적인 서술은 사람이 읽어야 잡힌다.

US 브리프의 `macro_gate`·`stance_gate`·`weight` 셋이 하는 일을 채권 쪽 한 파일에 모았다.
"""

import re

from .stance import AXES, label_for

BANNED_WORDS = ('buy-side', 'buy side', '바이사이드', '[확인필요]', 'TODO', 'TBD')

# 내부 파일명·필드명이 지면에 새면 안 된다 — US 브리프가 2026-08-17 에 실제로 흘렸다.
INTERNAL_TOKENS = ('bond_metrics.json', 'bond_market.json', 'bond_stance.json',
                   'bond_stance_eval.json', 'research_notes.md', 'allowed_grades',
                   'increase_block', 'trigger_metrics', 'diff_summary',
                   'report_date', 'us10y_dma20_gap_bp', 'signed-z')

SECTION_RE = re.compile(r'<section id="(b-\d+)"[^>]*>(.*?)</section>', re.S)
TAG_RE = re.compile(r'<[^>]+>')

# 시황 섹션과 판단 섹션 — 무게중심 검사의 기준
MARKET_SECTIONS = ('b-2', 'b-3', 'b-4', 'b-5', 'b-6', 'b-7', 'b-8')
JUDGEMENT_SECTIONS = ('b-9',)

MIN_MARKET_RATIO = 2.0    # 시황이 판단의 2배 이상이어야 한다


def text_of(html):
    """본문 + 메타 설명. 메타를 빼면 SEO 설명에 실린 수치 주장이 검사를 통째로
    피해 간다 — 태그를 지우면 content="..." 속 문장도 같이 사라진다."""
    t = re.sub(r'<style.*?</style>', ' ', html, flags=re.S)
    t = re.sub(r'<script.*?</script>', ' ', t, flags=re.S)
    metas = ' '.join(re.findall(r'<meta[^>]+content="([^"]*)"', t))
    titles = ' '.join(re.findall(r'<title>(.*?)</title>', t, re.S))
    return re.sub(r'\s+', ' ', TAG_RE.sub(' ', t) + ' ' + metas + ' ' + titles)


def sections(html):
    return {m.group(1): m.group(2) for m in SECTION_RE.finditer(html)}


MEASURE_RE = re.compile(
    r'(-?\d[\d,]*(?:\.\d+)?)\s*(?:bp|%p|%|십억|배)'        # 단위를 단 수치
    r'|(-?\d[\d,]*\.\d{2,})'                              # 소수 2자리 이상
    r'|(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?)')                 # 천 단위 구분자


def _numbers(text):
    """비교 가능한 수치 토큰.

    하이픈을 음수 부호로 잘못 읽는 사고가 두 종류 있다. 하나는 날짜
    (「2026-08-27」에서 -27 을 뜯어내는 것, 주간 게이트가 2026-08-30 에 겪은 실패)이고,
    다른 하나는 만기 구간 표기(「5년-30년」에서 -30 을 뜯어내는 것)다.
    그래서 날짜를 먼저 가리고, **앞에 공백이나 여는 괄호가 오지 않는 하이픈은
    부호가 아니라 이음표**로 처리한다.
    """
    masked = re.sub(r'\d{4}-\d{2}-\d{2}', ' ', text)
    masked = re.sub(r'\d{4}년|\d{1,2}월|\d{1,2}일', ' ', masked)
    masked = re.sub(r'(?<=[^\s(\[])-', ' ', masked)

    # **단위를 단 수치만 검사한다.** 예전에는 모든 숫자를 뜯어냈고, 그러면 산문의
    # 「세 가지」·「3개월물」까지 걸리므로 0~100 정수를 통째로 면제해야 했다.
    # 그 면제가 게이트를 갉아먹었다 — 지어낸 bp 값이 0~100 범위면 무조건 통과했다.
    # 검사 대상을 좁히는 쪽이 면제를 넓히는 쪽보다 낫다.
    out = set()
    for m in MEASURE_RE.finditer(masked):
        raw = next(g for g in m.groups() if g)
        try:
            out.add(round(float(raw.replace(',', '')), 4))
        except ValueError:
            continue
    return out


def data_tokens(market, metrics, evaluation, econ=None):
    """발행본이 인용해도 되는 수치의 전체 집합."""
    out = set()

    def add(v, extra_scales=True):
        if isinstance(v, bool) or v is None:
            return
        if isinstance(v, (int, float)):
            f = float(v)
            out.add(round(f, 4))
            if extra_scales:
                # **단위 변환은 허용하지 않는다.** 예전에는 ×100(% -> bp)과
                # ÷10억(USD -> 십억)과 절댓값을 전부 허용했는데, 그러면 무관한 값이
                # 남의 단위로 세탁된다 — 10년물 4.67 이 ×100 되어 「하이일드 스프레드
                # 467bp」라는 거짓 문장을 통과시켰다(2026-08-31 codex 검토에서 실증).
                # 발행본이 인쇄하는 단위는 metrics 가 그 단위로 직접 내려보낸다
                # (credit 의 `bp`, etf 의 `aum_bn`). 여기서는 **같은 값을 다른
                # 자릿수로 인쇄하는 것**만 허용한다.
                # 정수 반올림(0자리)은 넣지 않는다. 달러지수 99.16 이 99 가 되어
                # 「금리차 99bp」를 통과시킨다. 발행본이 정수로 인쇄해야 하는 값은
                # metrics 가 그 자릿수로 내려보낸다.
                for d in (1, 2, 3):
                    out.add(round(f, d))
        elif isinstance(v, dict):
            for x in v.values():
                add(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                add(x)

    for blob in (market, metrics, evaluation, econ):
        add(blob)
    return out


def check(html, market, metrics, evaluation, book, econ=None):
    """-> 위반 목록. 빈 리스트면 발행 가능."""
    errs = []
    txt = text_of(html)
    secs = sections(html)

    # --- 통제 입력 자체가 성립하는가 (fail closed) --------------------------
    # 게이트가 «열린 채로 실패»하면 게이트가 아니다. 데이터가 불완전하거나 파일마다
    # 기준일이 다르면 그 아래 검사는 전부 의미가 없다.
    if not market.get('complete', False):
        errs.append(f'수집이 불완전하다: missing={market.get("missing")}')
    rd = market.get('report_date')
    if not rd:
        errs.append('기준일이 없다')
    for name, blob in (('metrics', metrics), ('stance_eval', evaluation),
                       ('stance', book)):
        other = blob.get('report_date')
        if other and rd and other != rd:
            errs.append(f'{name} 기준일 불일치: {other} != {rd}')

    for w in BANNED_WORDS:
        if w.lower() in txt.lower():
            errs.append(f'금지 어휘: {w}')
    for tok in INTERNAL_TOKENS:
        if tok in txt:
            errs.append(f'내부 용어 노출: {tok}')

    # --- 뷰 3축 표식 -------------------------------------------------------
    marks = re.findall(r'data-axis-key="(\w+)" data-grade="(-?\d+)"[^>]*>([^<]+)<',
                       html)
    found = {k for k, _, _ in marks}
    for key in AXES:
        if key not in found:
            errs.append(f'뷰 3축 표식 없음: {key}')
    for key, grade, label in marks:
        if key not in AXES:
            errs.append(f'알 수 없는 축: {key}')
            continue
        g = int(grade)
        want = label_for(key, g)
        if label.strip() != want:
            errs.append(f'{key}: 등급 {g} 의 라벨은 「{want}」여야 하는데 '
                        f'「{label.strip()}」이다')
        axis_eval = (evaluation.get('assets', {}) or {}).get(key) or {}
        allowed = axis_eval.get('allowed_grades')
        if allowed is None:
            # 허용 등급이 없으면 «검사할 수 없음»이지 «아무거나 됨»이 아니다.
            errs.append(f'{key}: 허용 등급을 알 수 없다 — 규율 판정 없이는 발행 불가')
        elif g not in allowed:
            errs.append(f'{key}: 등급 {g} 는 오늘 허용되지 않는다 (허용 {allowed})')
        prev = (book.get('assets', {}).get(key) or {}).get('grade')
        if prev is not None and abs(g - prev) > 1:
            errs.append(f'{key}: 하루에 두 칸 이동 ({prev} -> {g})')

    # --- 「지금 어디에 있나」 ------------------------------------------------
    for axis in ('rates', 'credit', 'fx'):
        if f'data-standing="{axis}"' not in html:
            errs.append(f'위치 서술 표식 없음: data-standing="{axis}"')
    if not re.search(r'백분위', txt):
        errs.append('백분위를 한 번도 쓰지 않았다 — 시장이 어디에 서 있는지가 없다')

    # --- 기준일 노출 -------------------------------------------------------
    if txt.count(metrics.get('report_date', '\x00')) < 2:
        errs.append('기준일이 본문에 충분히 노출되지 않았다')

    # --- 수치 창작 ---------------------------------------------------------
    allowed_nums = data_tokens(market, metrics, evaluation, econ)
    # 남는 면제는 연도뿐이다. 단위를 단 수치만 검사하므로 산문의 작은 정수는
    # 애초에 후보에 오르지 않는다.
    exempt = {2024.0, 2025.0, 2026.0, 2027.0}
    used = _numbers(txt)
    invented = sorted(v for v in used
                      if v not in allowed_nums and v not in exempt
                      and abs(v) > 0.001)
    if invented:
        errs.append('데이터에 없는 수치: ' + ', '.join(str(v) for v in invented[:12]))
    # 이 검사의 한계 — 2026-08-31 실측. 허용 집합이 1,000개 남짓이고 발행본이 쓰는
    # 수치 범위가 좁아서, 그럴듯하게 «지어낸» 값도 3분의 1 정도는 통과한다.
    # 이건 크기·자릿수가 어긋난 창작을 잡는 그물이지 정확성의 증명이 아니다.
    # 진짜 방어선은 렌더러가 숫자를 데이터에서만 찍는다는 것이고, 이 검사는 그 뒤를
    # 받치는 보조 장치다. 정확성은 사람이 하는 팩트체크에서 잡힌다.

    # --- 무게중심 ----------------------------------------------------------
    mk = sum(len(text_of(secs.get(s, ''))) for s in MARKET_SECTIONS)
    jd = sum(len(text_of(secs.get(s, ''))) for s in JUDGEMENT_SECTIONS)
    if jd and mk / jd < MIN_MARKET_RATIO:
        errs.append(f'무게중심 역전: 시황 {mk}자 대 판단 {jd}자 '
                    f'(비율 {mk / jd:.2f}, 최소 {MIN_MARKET_RATIO})')
    if mk < 3000:
        errs.append(f'시황 분량 부족: {mk}자')

    return errs
