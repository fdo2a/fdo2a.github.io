"""Publication gate for §8 — verifies the report's stance against the rules.

This is the half of the discipline a prompt cannot enforce. The writer can be told to
respect `allowed_grades`; only a gate can prove it did. Every check here fails the run
loudly rather than degrading, because a §8 that silently drifts is exactly the failure
this whole mechanism exists to end.

Pure — `check()` takes strings and dicts and returns a list of violation messages.
"""

import re

from .stance import ASSETS, CURVE_LABELS, label_for
from common.numbers import TAG_RE

# The stance cell carries machine-readable markers so the gate reads grades exactly
# instead of guessing from prose: <span data-asset="equities" data-grade="0">중립</span>
_SPAN = re.compile(
    r'<span\b(?P<attrs>[^>]*\bdata-asset\s*=\s*"(?P<asset>[a-z_]+)"[^>]*)>'
    r'(?P<text>.*?)</span>',
    re.S)
_GRADE = re.compile(r'\bdata-grade\s*=\s*"(-?\d+)"')
# 주석·속성값 안의 `>` 까지 한 토큰으로 읽는다 — 정본은 common/numbers.py
# (2026-09-01 codex 검토: 트리거 근거를 주석 안에 숨기면 검사를 비껴갔다).
_TAG = TAG_RE


def locate_section(html, keyword):
    """The <section> whose heading names `keyword`, or None.

    Headings first, body text only as a fallback: the macro section reconciles itself
    against the stance section by name, so the word legitimately appears in prose
    upstream of the section it labels.
    """
    heads = [m.start() for m in re.finditer(r'<h[1-4]\b[^>]*>(?:(?!</h[1-4]>).)*?'
                                            + re.escape(keyword), html, re.S)]
    i = heads[0] if heads else html.find(keyword)
    if i < 0:
        return None
    start = html.rfind('<section', 0, i)
    start = start if start >= 0 else i
    end = html.find('<section', i)
    return html[start:end if end > 0 else len(html)]


def section8(html):
    """The §8 slice of the report, or None if it isn't there."""
    return locate_section(html, '멀티에셋')


def strip_tags(html):
    return re.sub(r'\s+', ' ', _TAG.sub(' ', html))


def _rows(section):
    return re.findall(r'<tr\b(?P<attrs>[^>]*)>(?P<body>.*?)</tr>', section, re.S)


def parse_stance_cells(section):
    """-> {asset: {'grade': int|None, 'text': str, 'row': str, 'row_attrs': str}}"""
    found = {}
    for attrs, body in _rows(section):
        for m in _SPAN.finditer(body):
            g = _GRADE.search(m.group('attrs'))
            found[m.group('asset')] = {
                'grade': int(g.group(1)) if g else None,
                'text': strip_tags(m.group('text')).strip(),
                'row': body,
                'row_attrs': attrs,
            }
    return found


def number_forms(value):
    """String spellings of a metric value a writer might reasonably use."""
    if value is None:
        return []
    forms = {f'{value}', f'{value:.1f}', f'{value:.2f}', f'{abs(value)}',
             f'{abs(value):.1f}', f'{abs(value):.2f}'}
    if float(value) == int(value):
        forms.add(str(int(value)))
        forms.add(str(abs(int(value))))
    return [f for f in forms if f]


def check(html, prev_stance, stance_eval, next_stance, metric_names=()):
    v = []
    section = section8(html)
    if section is None:
        return ['§8(멀티에셋 매니저 전략) 섹션을 찾을 수 없다']
    text = strip_tags(section)

    cells = parse_stance_cells(section)
    prev_assets = (prev_stance or {}).get('assets') or {}
    eval_assets = (stance_eval or {}).get('assets') or {}
    next_assets = (next_stance or {}).get('assets') or {}
    bootstrap = bool((stance_eval or {}).get('bootstrap'))

    missing = [k for k in ASSETS if k not in cells]
    if missing:
        v.append(f"§8 표에 data-asset 표식이 없는 자산군: {', '.join(missing)}")

    for key, cell in cells.items():
        if key not in ASSETS:
            v.append(f'§8: 알 수 없는 자산군 표식 "{key}"')
            continue
        grade = cell['grade']
        if grade is None:
            v.append(f'§8 {key}: data-grade 속성이 없다')
            continue
        try:
            want = label_for(key, grade)
        except ValueError as e:
            v.append(f'§8 {key}: {e}')
            continue
        if want not in cell['text']:
            v.append(f'§8 {key}: 등급 {grade}의 통제 어휘는 "{want}"인데 '
                     f'"{cell["text"]}"로 적혀 있다')

        allowed = (eval_assets.get(key) or {}).get('allowed_grades')
        if allowed and grade not in allowed:
            v.append(f'§8 {key}: 등급 {grade}는 허용 범위 {allowed} 밖이다 '
                     f'(이동 규율 위반)')

        row_text = strip_tags(cell['row'])
        if not re.search(r'\d+\s*영업일', row_text):
            v.append(f'§8 {key}: 유지 일수(N영업일)가 없다')
        if not re.search(r'\d', row_text.split('영업일')[-1]):
            v.append(f'§8 {key}: 다음 분기점에 수치가 없다 — '
                     '「추이 확인 필요」류 무판정 문구는 금지')

        # Adding risk needs the trigger that licensed it quoted in the section.
        prev_grade = (prev_assets.get(key) or {}).get('grade')
        if prev_grade is None or bootstrap or grade == prev_grade:
            continue
        if abs(grade) <= abs(prev_grade):
            continue  # de-risking is permissive by design
        met = [t for t in (eval_assets.get(key) or {}).get('increase', [])
               if t.get('status') == 'MET']
        if met:
            if not any(any(f in text for f in number_forms(t.get('actual'))) for t in met):
                shown = ', '.join(str(t.get('actual')) for t in met)
                v.append(f'§8 {key}: 등급을 {prev_grade}→{grade}로 확대했는데 '
                         f'충족된 트리거의 실측값({shown})이 본문에 인용되지 않았다')
        elif 'data-evidence="event"' not in cell['row_attrs']:
            v.append(f'§8 {key}: 등급을 {prev_grade}→{grade}로 확대했는데 충족된 수치 '
                     '트리거가 없다 — 이벤트 근거라면 <tr>에 data-evidence="event"를 달고 '
                     '출처를 인용할 것')

    v += _check_next_stance(next_stance, next_assets, cells, prev_assets,
                            (stance_eval or {}).get('report_date'), metric_names)
    return v


def _check_next_stance(next_stance, next_assets, cells, prev_assets, report_date, metric_names):
    v = []
    if not next_stance:
        return ['stance_next.json이 없다 — 내일 책이 얼어붙는다']
    if report_date and next_stance.get('report_date') != report_date:
        v.append(f'stance_next.json report_date가 {next_stance.get("report_date")}로 '
                 f'오늘({report_date})과 다르다')

    for key in ASSETS:
        st = next_assets.get(key)
        if not st:
            v.append(f'stance_next.json에 {key}가 없다')
            continue
        grade = st.get('grade')
        try:
            want = label_for(key, grade)
        except (ValueError, TypeError):
            v.append(f'stance_next.json {key}: 등급 {grade}가 범위 밖이다')
            continue
        if st.get('label') != want:
            v.append(f'stance_next.json {key}: label은 "{want}"여야 하는데 '
                     f'"{st.get("label")}"이다')
        if key in cells and cells[key]['grade'] is not None and cells[key]['grade'] != grade:
            v.append(f'stance_next.json {key}: 등급 {grade}가 §8 표의 '
                     f'{cells[key]["grade"]}와 다르다')
        if key == 'bonds' and st.get('curve') and st['curve'] not in CURVE_LABELS:
            v.append(f'stance_next.json bonds: curve "{st["curve"]}"는 통제 어휘 '
                     f'{list(CURVE_LABELS)} 밖이다')

        increase = (st.get('triggers') or {}).get('increase') or []
        for t in increase + ((st.get('triggers') or {}).get('decrease') or []):
            name = t.get('metric')
            if t.get('kind') != 'event' and metric_names and name not in metric_names:
                v.append(f'stance_next.json {key}: 트리거 지표 "{name}"가 '
                         'stance_metrics.json에 없다 — 영영 UNKNOWN으로 남는다')
        if grade == 0 and increase and not any(t.get('toward') in ('+', '-') for t in increase):
            v.append(f'stance_next.json {key}: 중립 등급의 increase 트리거에 '
                     'toward(+/-)가 없어 어느 쪽으로도 열 수 없다')

        prev_grade = (prev_assets.get(key) or {}).get('grade')
        if prev_grade is None or grade == prev_grade:
            continue
        if report_date and st.get('since') != report_date:
            v.append(f'stance_next.json {key}: 등급이 바뀌었는데 since가 '
                     f'{st.get("since")}로 오늘이 아니다')
        hist = [h for h in (next_stance.get('history') or [])
                if h.get('asset') == key and h.get('date') == report_date]
        if not hist:
            v.append(f'stance_next.json {key}: 등급이 {prev_grade}→{grade}로 바뀌었는데 '
                     'history에 오늘 기록이 없다')
    return v
