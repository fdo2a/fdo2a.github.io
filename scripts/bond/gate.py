"""발행 게이트 — 채권 리포트가 넘어서는 안 되는 선.

게이트가 막는 것과 못 막는 것을 분명히 해 둔다.

  막는다: 데이터에 없는 수치, 통제 어휘 밖의 등급 라벨, 규율이 허용하지 않은 등급,
          내부 파일명·필드명 노출, 금지 어휘, 미완 마커, 기준일 없는 표,
          판단이 시황보다 길어지는 무게중심 역전.
  못 막는다: 분석의 질. 패딩과 형식적인 서술은 사람이 읽어야 잡힌다.

US 브리프의 `macro_gate`·`stance_gate`·`weight` 셋이 하는 일을 채권 쪽 한 파일에 모았다.
"""

import re

from common.numbers import (measure_numbers as _measure_numbers,
                            numbers_split_by_tags as _split_numbers,
                            numeric_tokens as _numeric_tokens,
                            text_of as _text_of)

from .stance import AXES, label_for

BANNED_WORDS = ('buy-side', 'buy side', '바이사이드', '[확인필요]', 'TODO', 'TBD')

# 내부 파일명·필드명이 지면에 새면 안 된다 — US 브리프가 2026-08-17 에 실제로 흘렸다.
INTERNAL_TOKENS = ('bond_metrics.json', 'bond_market.json', 'bond_stance.json',
                   'bond_stance_eval.json', 'research_notes.md', 'allowed_grades',
                   'increase_block', 'trigger_metrics', 'diff_summary',
                   'report_date', 'us10y_dma20_gap_bp', 'signed-z')

SECTION_RE = re.compile(r'<section id="(b-\d+)"[^>]*>(.*?)</section>', re.S)

# 시황 섹션과 판단 섹션 — 무게중심 검사의 기준
MARKET_SECTIONS = ('b-2', 'b-3', 'b-4', 'b-5', 'b-6', 'b-7', 'b-8')
JUDGEMENT_SECTIONS = ('b-9',)

MIN_MARKET_RATIO = 2.0    # 시황이 판단의 2배 이상이어야 한다


def text_of(html):
    """공용 구현에 위임 — 규칙 정본은 `common/numbers.py` 하나뿐이다."""
    return _text_of(html)


def sections(html):
    return {m.group(1): m.group(2) for m in SECTION_RE.finditer(html)}


def _numbers(text):
    return _measure_numbers(text)


def data_tokens(market, metrics, evaluation, econ=None):
    """발행본이 인용해도 되는 수치의 전체 집합 — 규칙은 `common/numbers.py`."""
    return _numeric_tokens(market, metrics, evaluation, econ)


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

    # 「4.<span>47</span>bp」는 화면에 4.47bp 로 보이는데 검사에는 4 와 47bp 로
    # 들어간다 — 허용된 47bp 만 보고 통과한다(2026-09-01 codex 검토).
    for run in _split_numbers(html)[:4]:
        errs.append(f'수치 사이에 태그가 끼어 있다({run.strip()[:40]}) — '
                    f'검사를 피해 가므로 허용하지 않는다')

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

    # --- 지면 배분이 노출과 어긋나면 막는다 --------------------------------
    # 2026-09-01 사용자 지시: 「미국 상장 ETF를 쓴다」는 이유만으로 독일·영국 금리를
    # 매일 동등한 비중으로 볼 필요는 없다. 중요한 건 상장 국가가 아니라 underlying
    # exposure다. 첫 회차는 §3 에서 미국 10행 대 해외 14행이었다 — 산문은 미국
    # 중심인데 표 지면은 정반대였고, 독자 눈에 먼저 들어오는 건 표다.
    # 표의 소속은 **표식으로** 판정한다. 캡션 문자열에 「미국」이 있는지로 가르면
    # 「해외 국채 — 미국과 비교」 같은 캡션 하나로 우회되고, 표가 캡션을 잃으면
    # 검사가 통째로 열린 채 통과한다(2026-09-01 codex 지적).
    rates_sec = secs.get('b-3', '')
    tables = re.findall(r'<table([^>]*)>(.*?)</table>', rates_sec, re.S)
    us_rows = foreign_rows = unscoped = 0
    for attrs, body_html in tables:
        rows = max(len(re.findall(r'<tr>', body_html))
                   - len(re.findall(r'<thead>', body_html)), 0)
        scope = re.search(r'data-scope="(\w+)"', attrs)
        if not scope:
            unscoped += 1
        elif scope.group(1) == 'us':
            us_rows += rows
        else:
            foreign_rows += rows
    if unscoped:
        errs.append(f'금리 섹션에 소속 표식(data-scope) 없는 표가 {unscoped}개 있다')
    if tables and not us_rows:
        errs.append('금리 섹션에 미국 표(data-scope="us")가 없다')
    if us_rows and foreign_rows > us_rows:
        errs.append(f'지면 배분 역전: 금리 섹션의 해외 표 {foreign_rows}행이 '
                    f'미국 {us_rows}행보다 많다')

    # 무엇을 얼마나 볼지의 근거(노출 역산)가 지면에 있어야 한다
    if '노출' not in txt or '역산' not in txt:
        errs.append('모니터링 비중을 무엇에서 역산했는지가 본문에 없다')

    # --- 무게중심 ----------------------------------------------------------
    mk = sum(len(text_of(secs.get(s, ''))) for s in MARKET_SECTIONS)
    jd = sum(len(text_of(secs.get(s, ''))) for s in JUDGEMENT_SECTIONS)
    if jd and mk / jd < MIN_MARKET_RATIO:
        errs.append(f'무게중심 역전: 시황 {mk}자 대 판단 {jd}자 '
                    f'(비율 {mk / jd:.2f}, 최소 {MIN_MARKET_RATIO})')
    if mk < 3000:
        errs.append(f'시황 분량 부족: {mk}자')

    return errs
