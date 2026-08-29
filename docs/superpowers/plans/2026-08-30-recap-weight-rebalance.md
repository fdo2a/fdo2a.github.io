# 시황·가격 비중 재조정 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 발행본의 무게중심을 포지션(53%)에서 시황·가격으로 옮기고, 각 가격 섹션이 「지금 시장이 어디에 있나」를 먼저 말하게 하며, 전일과 겹치는 날의 매크로 섹션은 접는다.

**Architecture:** 새 게이트 `scripts/check_weight.py`(로직 `scripts/us/weight.py`)가 발행 직전 자수·표식·어휘를 검사한다. 축약일 판정은 writer가 아니라 `macro.evaluate()`가 `macro_eval.json`에 `abbreviated`로 담아 넘긴다(축 점수 z를 writer가 만지지 않는 것과 같은 계약). 기존 게이트 `macro_gate`는 축약일에 경로 블록 검사를 완화한다.

**Tech Stack:** Python 3 표준 라이브러리만(정규식·json·html). pytest. 기존 `scripts/us/` 패키지 관례를 따른다 — 순수 함수 + 위반 문자열 리스트 반환.

**Spec:** `docs/superpowers/specs/2026-08-30-recap-weight-rebalance-design.md`

## Global Constraints

- **자수 계산은 엔티티 디코드 후.** `stance_gate.strip_tags`는 `&amp;`를 5자로 세므로 재사용 금지
- **섹션 찾기는 `<h2>` 제목 완전일치.** 본문 폴백 금지 — 「주식」·「채권」이 헤드라인에 나오면 엉뚱한 구간을 잡는다. 못 찾으면 통과가 아니라 위반
- **세는 것**: `<p>` 텍스트 + `<td>` 중 40자 초과 칸. **빼는 것**: `class="caption"`
- **`data-*` 속성값은 목록 중 하나.** 스펙의 파이프 기호(`a|b|c`)는 문서 표기이지 값이 아니다
- **단독 「중립」은 검사하지 않는다** — 일상 어휘와 구분되지 않는다. 다어절 라벨과 `OW`·`UW`만
- 테스트는 `python3 -m pytest scripts/us/tests/test_weight.py -q`로 돈다(레포 루트에서)
- 커밋 메시지는 한국어 한 줄 요약 + 본문, 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

### Task 1: 섹션 슬라이싱과 자수 계산

**Files:**
- Create: `scripts/us/weight.py`
- Test: `scripts/us/tests/test_weight.py`

**Interfaces:**
- Produces: `section_slice(html, title) -> str | None`, `prose_chars(section_html) -> int`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.weight import section_slice, prose_chars

DOC = '''<h1>주식이 오른 하루</h1>
<section><h2>주식</h2><p>본문 열두 글자입니다</p>
<p class="caption">캡션은 세지 않는다</p>
<table><tr><td>짧은칸</td><td>이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다</td></tr></table>
</section>
<section><h2>채권</h2><p>AT&amp;T</p></section>'''

def test_section_slice_uses_h2_not_headline():
    # <h1>에도 「주식」이 있지만 <h2> 구간을 잡아야 한다
    seg = section_slice(DOC, '주식')
    assert '본문 열두 글자입니다' in seg
    assert '오른 하루' not in seg

def test_section_slice_returns_none_when_absent():
    assert section_slice(DOC, '원자재') is None

def test_prose_chars_counts_paragraphs_and_long_cells_only():
    n = prose_chars(section_slice(DOC, '주식'))
    assert n == len('본문 열두 글자입니다') + len('이것은 마흔 글자를 넘기는 서술형 칸이라서 자수에 포함되어야 마땅한 칸이다')

def test_prose_chars_decodes_entities():
    # &amp; 는 5자가 아니라 1자다
    assert prose_chars(section_slice(DOC, '채권')) == len('AT&T')
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'us.weight'`

- [ ] **Step 3: 최소 구현**

```python
"""발행본의 무게중심을 재는 게이트 — 시황·가격 대 판단·포지션.

자수는 엔티티를 디코드한 뒤 센다. stance_gate.strip_tags는 &amp;를 5자로 세므로
여기서 쓰지 않는다(2026-08-30 codex 검토).
"""
import html as _html
import re

_TAG = re.compile(r'<[^>]+>')
_CELL_MIN = 40


def _text(fragment):
    return _html.unescape(_TAG.sub('', fragment)).strip()


def section_slice(html_doc, title):
    """제목이 정확히 `title`인 <h2>가 여는 구간. 없으면 None.

    본문 폴백을 두지 않는다 — 「주식」·「채권」은 헤드라인에도 나오는 흔한 말이라
    부분일치로 찾으면 엉뚱한 구간을 잡는다.
    """
    heads = [(m.start(), m.end()) for m in re.finditer(r'<h2\b[^>]*>(.*?)</h2>',
                                                       html_doc, re.S)
             if _text(m.group(1)) == title]
    if not heads:
        return None
    start, _ = heads[0]
    nxt = [m.start() for m in re.finditer(r'<h2\b', html_doc) if m.start() > start]
    return html_doc[start:nxt[0] if nxt else len(html_doc)]


def prose_chars(section_html):
    """문단 + 서술형 표 칸(40자 초과)의 글자 수. 캡션은 뺀다."""
    if not section_html:
        return 0
    n = 0
    for attrs, body in re.findall(r'<p([^>]*)>(.*?)</p>', section_html, re.S):
        if 'caption' in attrs:
            continue
        n += len(_text(body))
    for body in re.findall(r'<td[^>]*>(.*?)</td>', section_html, re.S):
        t = _text(body)
        if len(t) > _CELL_MIN:
            n += len(t)
    return n
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: 4 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/weight.py scripts/us/tests/test_weight.py
git commit -m "무게중심 게이트 — 섹션 슬라이싱과 자수 계산"
```

---

### Task 2: 분량 계약 검사

**Files:**
- Modify: `scripts/us/weight.py`
- Test: `scripts/us/tests/test_weight.py`

**Interfaces:**
- Consumes: `section_slice`, `prose_chars`
- Produces: `measure(html, market='us') -> dict`, `check_volume(m, abbreviated=False, market='us') -> list[str]`
  - `measure` 반환: `{'sections': {제목: int}, 'recap': int, 'judgment': int, 'ratio': float|None, 'missing': [제목]}`
  - `ratio`는 `judgment`가 0이면 `None`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.weight import measure, check_volume, THRESHOLDS


def _doc(sizes):
    """{제목: 자수}로 합성 발행본을 만든다."""
    out = []
    for title, n in sizes.items():
        out.append(f'<section><h2>{title}</h2><p>{"가" * n}</p></section>')
    return '\n'.join(out)


US_FULL = {'오늘의 장': 800, '주식': 1900, '채권': 2000, 'FX': 650, '원자재': 750,
           '전략 코멘트': 400, '매크로 논리': 4400, '멀티에셋 매니저 전략': 2200}


def test_measure_groups_and_ratio():
    m = measure(_doc(US_FULL), 'us')
    assert m['recap'] == 800 + 1900 + 2000 + 650 + 750
    assert m['judgment'] == 400 + 4400 + 2200
    assert round(m['ratio'], 3) == round(m['recap'] / m['judgment'], 3)
    assert m['missing'] == []


def test_missing_section_is_a_violation_not_a_pass():
    doc = _doc({k: v for k, v in US_FULL.items() if k != '채권'})
    m = measure(doc, 'us')
    assert '채권' in m['missing']
    assert any('채권' in x for x in check_volume(m, market='us'))


def test_full_day_passes_thresholds():
    assert check_volume(measure(_doc(US_FULL), 'us'), abbreviated=False, market='us') == []


def test_measured_2026_08_27_shape_is_blocked():
    """실측 판(시황 3,676 · 판단 7,424 · 매크로 4,788)은 막혀야 한다."""
    sizes = {'오늘의 장': 0, '주식': 1278, '채권': 1581, 'FX': 360, '원자재': 457,
             '전략 코멘트': 392, '매크로 논리': 4788, '멀티에셋 매니저 전략': 2244}
    v = check_volume(measure(_doc(sizes), 'us'), abbreviated=False, market='us')
    assert any('비율' in x for x in v)
    assert any('매크로 논리' in x for x in v)


def test_abbreviated_day_caps_macro_and_raises_ratio_floor():
    sizes = dict(US_FULL, **{'매크로 논리': 4400})
    v = check_volume(measure(_doc(sizes), 'us'), abbreviated=True, market='us')
    assert any('매크로 논리' in x and '2400' in x for x in v)

    ok = dict(US_FULL, **{'매크로 논리': 2000})
    assert check_volume(measure(_doc(ok), 'us'), abbreviated=True, market='us') == []


def test_deleting_judgment_to_game_the_ratio_is_blocked():
    """§9를 지워 비율을 맞추는 우회 — 판단군 하한이 막는다."""
    sizes = dict(US_FULL, **{'매크로 논리': 500})
    v = check_volume(measure(_doc(sizes), 'us'), abbreviated=False, market='us')
    assert any('매크로 논리' in x and '3000' in x for x in v)


def test_kr_has_floor_but_no_ratio():
    sizes = {'오늘의 장': 700, '지수 & 장중': 900, '환율·금리': 700,
             '전략 코멘트': 700, '기술적 분석 & 트레이딩 전략': 500}
    assert check_volume(measure(_doc(sizes), 'kr'), market='kr') == []
    thin = dict(sizes, **{'지수 & 장중': 300})
    assert any('시황·가격군' in x for x in check_volume(measure(_doc(thin), 'kr'), market='kr'))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: FAIL — `ImportError: cannot import name 'measure'`

- [ ] **Step 3: 최소 구현 — `weight.py`에 이어 붙인다**

```python
SECTION_GROUPS = {
    'us': {
        'recap': ('오늘의 장', '주식', '채권', 'FX', '원자재'),
        'judgment': ('전략 코멘트', '매크로 논리', '멀티에셋 매니저 전략'),
    },
    'kr': {
        'recap': ('오늘의 장', '지수 & 장중', '환율·금리'),
        'judgment': ('전략 코멘트', '기술적 분석 & 트레이딩 전략'),
    },
}

# 「오늘의 장」은 2026-08-28 신설이라 옛 판에는 없다. 없어도 위반으로 치지 않고 0자로 센다.
OPTIONAL_SECTIONS = ('오늘의 장',)

THRESHOLDS = {
    'us': {
        'recap_min': 5500,
        'ratio_min': 0.75, 'ratio_min_abbrev': 1.00,
        'macro_max': 4600, 'macro_min': 3000,
        'macro_max_abbrev': 2400, 'macro_min_abbrev': 1200,
        'stance_min': 1800,
    },
    'kr': {'recap_min': 2200},
}


def measure(html_doc, market='us'):
    groups = SECTION_GROUPS[market]
    sections, missing = {}, []
    for group in ('recap', 'judgment'):
        for title in groups[group]:
            seg = section_slice(html_doc, title)
            if seg is None:
                sections[title] = 0
                if title not in OPTIONAL_SECTIONS:
                    missing.append(title)
            else:
                sections[title] = prose_chars(seg)
    recap = sum(sections[t] for t in groups['recap'])
    judgment = sum(sections[t] for t in groups['judgment'])
    return {'sections': sections, 'recap': recap, 'judgment': judgment,
            'ratio': (recap / judgment) if judgment else None, 'missing': missing}


def check_volume(m, abbreviated=False, market='us'):
    t = THRESHOLDS[market]
    v = []
    for title in m['missing']:
        v.append(f'섹션 「{title}」을 찾지 못했다 — <h2>{title}</h2>가 있어야 분량을 잰다')

    if m['recap'] < t['recap_min']:
        v.append(f'시황·가격군이 {m["recap"]}자로 하한 {t["recap_min"]}자에 못 미친다')

    if market != 'us':
        return v

    floor = t['ratio_min_abbrev'] if abbreviated else t['ratio_min']
    day = '축약일' if abbreviated else '발표일'
    if m['ratio'] is not None and m['ratio'] < floor:
        v.append(f'시황·가격군 ÷ 판단군이 {m["ratio"]:.2f}로 {day} 하한 {floor:.2f}에 못 미친다 '
                 f'(시황 {m["recap"]}자 · 판단 {m["judgment"]}자)')

    macro = m['sections'].get('매크로 논리', 0)
    hi = t['macro_max_abbrev'] if abbreviated else t['macro_max']
    lo = t['macro_min_abbrev'] if abbreviated else t['macro_min']
    if macro > hi:
        v.append(f'매크로 논리가 {macro}자로 {day} 상한 {hi}자를 넘는다')
    if macro < lo:
        v.append(f'매크로 논리가 {macro}자로 {day} 하한 {lo}자에 못 미친다 — '
                 '§9를 지워 비율을 맞추지 말 것')

    stance = m['sections'].get('멀티에셋 매니저 전략', 0)
    if stance < t['stance_min']:
        v.append(f'멀티에셋 매니저 전략이 {stance}자로 하한 {t["stance_min"]}자에 못 미친다')
    return v
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: 11 passed

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/weight.py scripts/us/tests/test_weight.py
git commit -m "분량 계약을 잰다 — 비율·상한·하한과 축약일 분기"
```

---

### Task 3: 축약일 판정을 `macro.evaluate()`가 낸다

**Files:**
- Modify: `scripts/us/macro.py:147-232` (`evaluate`)
- Test: `scripts/us/tests/test_macro.py`

**Interfaces:**
- Produces: `evaluate()` 반환 딕셔너리에 키 셋 추가
  - `abbreviated: bool`
  - `abbreviated_reason: str | None` — 축약이 **아닌** 이유(사람이 읽는 한 줄). 축약이면 `None`
  - `axis_directions: dict[str, str]` — 오늘 4축 방향. 다음날 대조용으로 `macro_next.json`에 실린다

**판정 규칙.** 넷 다 참이어야 축약일이다.

1. `metrics['headline_releases']`에 `tier == 1`이 없다
2. 레짐이 움직이지 않는다 — `allowed_regimes`가 현재 레짐 하나뿐이다
3. 4축 `direction`이 전일과 같다 — 전일 값은 `macro['axis_directions']`. **그 키가 없으면(첫날) 이 조건은 참으로 본다**
4. 정책 경로 시점이 전일과 같다 — `policy['change_allowed']`가 거짓이거나, 참이어도 `timing`이 그대로

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.macro import evaluate

BOOK = {
    'report_date': '2026-08-26',
    'regime': {'growth': -1, 'inflation': 0, 'since': '2026-08-26'},
    'policy_path': {'timing': '2026-12', 'prob_pct': 68.4},
    'transmission': {},
    'axis_directions': {'Labor': '보합', 'Activity': '악화', 'Consumption': '악화',
                        'Inflation': '둔화'},
}
AXES = {'Labor': {'direction': '보합'}, 'Activity': {'direction': '악화'},
        'Consumption': {'direction': '악화'}, 'Inflation': {'direction': '둔화'}}
QUIET = {
    'report_date': '2026-08-27',
    'growth_score': -0.377, 'inflation_score': -0.327,
    'new_releases': ['Initial Jobless Claims'],
    'headline_releases': [{'key': 'claims', 'tier': 2}],
    'axis_summary': AXES,
}


def test_quiet_day_is_abbreviated():
    ev = evaluate(BOOK, QUIET, '2026-08-27')
    assert ev['abbreviated'] is True
    assert ev['abbreviated_reason'] is None
    assert ev['axis_directions']['Activity'] == '악화'


def test_tier1_release_is_not_abbreviated():
    m = dict(QUIET, headline_releases=[{'key': 'cpi', 'tier': 1}])
    ev = evaluate(BOOK, m, '2026-08-27')
    assert ev['abbreviated'] is False
    assert 'tier 1' in ev['abbreviated_reason']


def test_axis_direction_change_is_not_abbreviated():
    m = dict(QUIET, axis_summary=dict(AXES, Labor={'direction': '악화'}))
    ev = evaluate(BOOK, m, '2026-08-27')
    assert ev['abbreviated'] is False
    assert '고용' in ev['abbreviated_reason'] or 'Labor' in ev['abbreviated_reason']


def test_first_day_without_stored_directions_still_abbreviates():
    book = {k: val for k, val in BOOK.items() if k != 'axis_directions'}
    assert evaluate(book, QUIET, '2026-08-27')['abbreviated'] is True
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_macro.py -q -k abbrev`
Expected: FAIL — `KeyError: 'abbreviated'`

- [ ] **Step 3: 최소 구현 — `macro.py`에 헬퍼를 더하고 `evaluate` 반환에 세 키를 넣는다**

```python
AXIS_KO = {'Labor': '고용', 'Activity': '생산·활동',
           'Consumption': '소비', 'Inflation': '물가'}


def _axis_directions(metrics):
    return {k: (v or {}).get('direction')
            for k, v in ((metrics or {}).get('axis_summary') or {}).items()}


def _abbreviated(macro, metrics, allowed, policy, directions):
    """축약일인가, 아니면 왜 아닌가. 반환 (bool, reason|None).

    writer가 판단하면 지켜지지 않는다(§9 매크로가 이미 겪은 실패). 여기서 끝낸다.
    """
    tiers = [r.get('tier') for r in ((metrics or {}).get('headline_releases') or [])]
    if 1 in tiers:
        return False, 'tier 1 발표가 있는 날'
    if len(allowed) > 1:
        return False, '레짐이 움직일 수 있는 날'
    prev = ((macro or {}).get('axis_directions') or {})
    for axis, now in directions.items():
        was = prev.get(axis)
        if was is not None and now is not None and was != now:
            return False, f'{AXIS_KO.get(axis, axis)}축 방향이 {was}에서 {now}로 바뀐 날'
    if policy.get('change_allowed') and policy.get('timing') != \
            ((macro or {}).get('policy_path') or {}).get('timing'):
        return False, '정책 경로 시점이 바뀐 날'
    return True, None
```

`evaluate`의 `return {...}` 직전에 다음을 넣고, 반환 딕셔너리에 세 키를 더한다.

```python
    directions = _axis_directions(m)
    abbreviated, abbrev_reason = _abbreviated(macro, m, allowed, policy, directions)
```

```python
        'abbreviated': abbreviated,
        'abbreviated_reason': abbrev_reason,
        'axis_directions': directions,
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/ -q`
Expected: 전부 통과(기존 macro 테스트 포함 — 반환 키 추가는 기존 단언을 깨지 않는다)

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/macro.py scripts/us/tests/test_macro.py
git commit -m "축약일 판정을 evaluate가 낸다 — writer가 판단하지 않는다"
```

---

### Task 4: 축약일에는 경로 블록 검사를 완화한다

**Files:**
- Modify: `scripts/us/macro_gate.py:213-224` (`_check_groups`), `scripts/us/macro_gate.py:415` (`check`)
- Test: `scripts/us/tests/test_macro_gate.py`

**Interfaces:**
- Consumes: `macro_eval['abbreviated']` (Task 3)
- Produces: `_check_groups(section, v, abbreviated=False)` — 축약일에는 서술 블록 4개와 그 안의 수치를 요구하지 않는다

**이 태스크를 빠뜨리면 축약일마다 발행이 막힌다.** `_check_groups`가 지금 경로 블록 4개와 각 블록의 수치를 강제하는데, 축약일 §9는 방향 스트립만 남기고 서술을 접기 때문이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.macro_gate import _check_groups

STRIP_ONLY = '<section><h2>매크로 논리</h2><p>전달경로 판정은 전일과 같다.</p></section>'


def test_full_day_still_requires_narrated_blocks():
    v = []
    _check_groups(STRIP_ONLY, v, abbreviated=False)
    assert len(v) == 4  # 네 경로 모두 서술 블록이 없다


def test_abbreviated_day_accepts_strip_without_narration():
    v = []
    _check_groups(STRIP_ONLY, v, abbreviated=True)
    assert v == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_macro_gate.py -q -k abbrev`
Expected: FAIL — `TypeError: _check_groups() got an unexpected keyword argument 'abbreviated'`

- [ ] **Step 3: 최소 구현**

`_check_groups` 시그니처와 앞머리를 고친다.

```python
def _check_groups(section, v, abbreviated=False):
    """Every channel gets a narrated block, and every block names a number.

    On an abbreviated day (설계 5) the channels collapse to the direction strip and
    the prose is deliberately absent — requiring it here would block publication
    every quiet day.
    """
    if abbreviated:
        return
    blocks = parse_group_blocks(section)
```

호출부에서 `macro_eval`의 값을 넘긴다. `check(html, prev_macro, macro_eval, next_macro, stance=None)` 안에서 `_check_groups(section, v)`를 부르는 자리를 찾아 이렇게 바꾼다.

```python
    _check_groups(section, v, abbreviated=bool((macro_eval or {}).get('abbreviated')))
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/ -q`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/macro_gate.py scripts/us/tests/test_macro_gate.py
git commit -m "축약일에는 경로 블록 서술을 요구하지 않는다"
```

---

### Task 5: 「지금 어디에 있나」와 원인 문단 검사

**Files:**
- Modify: `scripts/us/weight.py`
- Test: `scripts/us/tests/test_weight.py`

**Interfaces:**
- Produces: `check_standing(html, price_context, market='us') -> list[str]`,
  `check_cause(html, price_context, market='us') -> list[str]`
- `price_context`는 `market_data.json['price_context']` 그대로. 없으면(옛 데이터) 두 함수 다 `[]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.weight import check_standing, check_cause

PC = {
    'levels': {'S&P 500': {'value': 7730.99, 'percentile': 98.6, 'band': '매우 높음',
                           'sessions': 504},
               '30Y': {'value': 5.191, 'percentile': 96.8, 'band': '매우 높음',
                       'sessions': 504}},
    'moves': {'S&P 500': {'change': 0.72, 'multiple': 0.84, 'band': '보통'},
              'Gold': {'change': 3.4, 'multiple': 2.6, 'band': '큼'},
              '30Y': {'change': 0.005, 'multiple': 0.14, 'band': '미미'}},
}

GOOD_STANDING = ('<p data-standing="equities">S&P 500은 7,730으로 최근 2년 가운데 거의 꼭대기'
                 '(98.6번째 자리)에 있습니다. 한 달째 이 언저리에서 옆걸음이고, 오늘 0.72% '
                 '상승은 평소 하루 폭의 0.8배라 특별할 것 없는 하루였습니다.</p>')


def _sec(title, inner):
    return f'<section><h2>{title}</h2>{inner}</section>'


def test_missing_standing_paragraph_is_a_violation():
    doc = _sec('주식', '<p>나스닥은 09:30 저점을 찍었습니다.</p>')
    assert any('주식' in x and 'data-standing' in x for x in check_standing(doc, PC))


def test_standing_paragraph_must_be_substantive():
    doc = _sec('주식', '<p data-standing="equities">주식은 높습니다.</p>')
    v = check_standing(doc, PC)
    assert any('120자' in x for x in v)


def test_good_standing_paragraph_passes():
    doc = _sec('주식', GOOD_STANDING)
    assert check_standing(doc, PC) == []


def test_big_mover_needs_a_cause_paragraph():
    doc = _sec('원자재', '<p>금이 크게 올랐습니다.</p>')
    assert any('Gold' in x or '원자재' in x for x in check_cause(doc, PC))


def test_quiet_asset_is_exempt_from_cause():
    """30년물은 평소의 0.14배 — 미미하므로 원인 문단을 요구하지 않는다."""
    doc = _sec('채권', '<p>커브는 조용했습니다.</p>')
    assert check_cause(doc, PC) == []


def test_no_price_context_skips_both():
    doc = _sec('주식', '<p>본문</p>')
    assert check_standing(doc, {}) == []
    assert check_cause(doc, {}) == []
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q -k "standing or cause"`
Expected: FAIL — `ImportError: cannot import name 'check_standing'`

- [ ] **Step 3: 최소 구현 — `weight.py`에 이어 붙인다**

```python
_MIN_BLOCK = 120
_BIG_BANDS = ('큼', '매우 큼')

# 섹션 ← 그 섹션이 책임지는 price_context 자산
SECTION_ASSETS = {
    'us': {
        '주식': ('S&P 500', 'Nasdaq', 'Russell 2000', 'VIX'),
        '채권': ('10Y', '30Y'),
        'FX': ('DXY', 'USD/JPY', 'USD/KRW'),
        '원자재': ('WTI', 'Gold'),
    },
    'kr': {'지수 & 장중': (), '환율·금리': ()},
}

STANDING_KEYS = {'주식': 'equities', '채권': 'bonds', 'FX': 'fx', '원자재': 'commodities',
                 '지수 & 장중': 'equities', '환율·금리': 'rates'}


def _marked(section_html, attr):
    """`<p data-attr="...">` 문단들의 (값, 텍스트)."""
    out = []
    for attrs, body in re.findall(r'<p([^>]*)>(.*?)</p>', section_html or '', re.S):
        m = re.search(rf'\b{attr}\s*=\s*"([^"]*)"', attrs)
        if m:
            out.append((m.group(1), _text(body)))
    return out


def check_standing(html_doc, price_context, market='us'):
    """가격 섹션마다 「지금 어디에 있나」 문단이 있고 알맹이가 있는가."""
    if not price_context:
        return []
    v = []
    for title in SECTION_ASSETS[market]:
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        blocks = _marked(seg, 'data-standing')
        if not blocks:
            v.append(f'{title}: 「지금 어디에 있나」 문단이 없다 — '
                     f'<p data-standing="{STANDING_KEYS[title]}">로 시작할 것')
            continue
        text = max((t for _, t in blocks), key=len)
        if len(text) < _MIN_BLOCK:
            v.append(f'{title}: 「지금 어디에 있나」 문단이 {len(text)}자로 {_MIN_BLOCK}자에 '
                     '못 미친다 — 위치·경로·오늘의 크기 세 층을 담을 것')
        elif not re.search(r'\d', text):
            v.append(f'{title}: 「지금 어디에 있나」 문단에 수치가 없다')
    return v


def check_cause(html_doc, price_context, market='us'):
    """크게 움직인 자산은 원인 문단을 갖는가. 미미·보통이면 면제."""
    moves = (price_context or {}).get('moves') or {}
    if not moves:
        return []
    v = []
    for title, assets in SECTION_ASSETS[market].items():
        big = [a for a in assets if (moves.get(a) or {}).get('band') in _BIG_BANDS]
        if not big:
            continue
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        blocks = [t for _, t in _marked(seg, 'data-cause') if len(t) >= _MIN_BLOCK
                  and re.search(r'\d', t)]
        if not blocks:
            v.append(f'{title}: {", ".join(big)}이(가) 크게 움직였는데 원인 문단이 없다 — '
                     f'<p data-cause="...">에 {_MIN_BLOCK}자 이상, 수치 하나 이상')
    return v
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/weight.py scripts/us/tests/test_weight.py
git commit -m "가격 섹션이 「지금 어디에 있나」를 말하는지 검사한다"
```

---

### Task 6: §9 경로 블록의 그날 가격 금지, 가격 섹션의 포지션 어휘 금지, §2 순서

**Files:**
- Modify: `scripts/us/weight.py`
- Test: `scripts/us/tests/test_weight.py`

**Interfaces:**
- Produces: `check_macro_prices(html, market_data) -> list[str]`,
  `check_position_vocab(html, market='us') -> list[str]`,
  `check_lede(html) -> list[str]`

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.weight import check_macro_prices, check_position_vocab, check_lede

MD = {'indices': [{'name': 'S&P 500', 'close': 7730.99, 'change_pct': 0.72}],
      'fx': [{'name': 'DXY', 'close': 99.114, 'change_pct': -0.056}]}


def test_macro_group_may_not_quote_todays_price():
    doc = ('<section><h2>매크로 논리</h2><div data-macro-group="dollar">'
           '<p>오늘 DXY는 -0.04% 소폭 내린 99.11로 마감해 이 경로와 결이 같았습니다.</p>'
           '</div></section>')
    assert any('dollar' in x for x in check_macro_prices(doc, MD))


def test_macro_group_may_keep_structural_logic():
    doc = ('<section><h2>매크로 논리</h2><div data-macro-group="dollar">'
           '<p>실질금리 격차가 줄면 달러가 약해지는 경로입니다. 확인 지표는 20일 수익률이 '
           '-3% 아래로 확대되는지입니다.</p></div></section>')
    assert check_macro_prices(doc, MD) == []


def test_price_section_may_not_restate_the_stance():
    doc = '<section><h2>FX</h2><p>달러 소폭 숏을 그대로 유지합니다.</p></section>'
    assert any('FX' in x for x in check_position_vocab(doc))


def test_bare_neutral_is_not_flagged():
    doc = '<section><h2>FX</h2><p>거의 중립적인 하루였습니다.</p></section>'
    assert check_position_vocab(doc) == []


def test_lede_order_and_event_first():
    good = ('<section><h2>전략 코멘트</h2>'
            '<p data-lede="event">엔비디아 실적이 하루를 지배했습니다.</p>'
            '<p data-lede="meaning">이 숫자가 AI 캐펙스 기대를 떠받칩니다.</p>'
            '<p data-lede="action">2~6주 시계에서 메모리를 축소합니다.</p>'
            '<p data-lede="invalidation">20일 초과수익이 +5%p를 넘으면 되돌립니다.</p>'
            '</section>')
    assert check_lede(good) == []

    swapped = good.replace('data-lede="event"', 'data-lede="action"', 1) \
                  .replace('<p data-lede="action">2~6주', '<p data-lede="event">2~6주', 1)
    assert check_lede(swapped) != []

    missing = good.replace('<p data-lede="meaning">이 숫자가 AI 캐펙스 기대를 떠받칩니다.</p>', '')
    assert any('meaning' in x for x in check_lede(missing))
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q -k "macro_prices or vocab or lede"`
Expected: FAIL — `ImportError`

- [ ] **Step 3: 최소 구현 — `weight.py`에 이어 붙인다**

```python
# 등급 통제 어휘. 단독 「중립」은 뺀다 — 일상 어휘와 구분되지 않아 오탐을 매일 만든다.
BANNED_GRADE_WORDS = (
    '비중확대', '소폭확대', '소폭축소', '비중축소',
    '숏 듀레이션', '숏 바이어스', '중립 듀레이션', '롱 바이어스', '롱 듀레이션',
    '달러 숏', '달러 소폭 숏', '달러 중립', '달러 소폭 롱', '달러 롱',
    '플래트너', '커브 중립', '스티프너', '벨리 OW',
)
_OW_UW = re.compile(r'(?<![A-Za-z])(OW|UW)(?![A-Za-z])')

VOCAB_SECTIONS = {'us': ('오늘의 장', '주식', '채권', 'FX', '원자재'),
                  'kr': ('오늘의 장', '지수 & 장중', '환율·금리')}

LEDE_ORDER = ('event', 'meaning', 'action', 'invalidation')

_TODAY_CUE = re.compile(r'오늘|전일 대비|마감|하루 변화')


def _numbers(text):
    """비교용 수치 토큰. 콤마를 걷고 유니코드 마이너스를 통일한다."""
    t = text.replace(',', '').replace('−', '-')
    return {m.group(0).lstrip('+-') for m in re.finditer(r'-?\d+\.?\d*', t)}


def _todays_values(market_data):
    out = set()
    for group in ('indices', 'fx', 'commodities', 'yields'):
        for row in (market_data or {}).get(group) or []:
            for key in ('close', 'change_pct', 'value'):
                x = row.get(key)
                if isinstance(x, (int, float)):
                    out.add(f'{abs(x):.2f}'.rstrip('0').rstrip('.'))
                    out.add(f'{abs(x):.3f}'.rstrip('0').rstrip('.'))
    return out


def check_macro_prices(html_doc, market_data):
    """§9 경로 블록이 그날 가격을 되풀이하지 않는가.

    수치 중복만 본다 — 「달러는 소폭 내렸다」 같은 말바꿈은 잡지 못한다.
    """
    seg = section_slice(html_doc, '매크로 논리')
    if seg is None:
        return []
    today = _todays_values(market_data)
    if not today:
        return []
    v = []
    for m in re.finditer(r'<div[^>]*data-macro-group="([a-z_]+)"[^>]*>(.*?)</div>',
                         seg, re.S):
        key, text = m.group(1), _text(m.group(2))
        for sent in re.split(r'(?<=다)\.\s*', text):
            if not _TODAY_CUE.search(sent):
                continue
            hit = _numbers(sent) & today
            if hit:
                v.append(f'§9 {key}: 그날 가격({", ".join(sorted(hit))})을 되풀이했다 — '
                         '수치는 자산 섹션에 두고 여기에는 경로 논리만 쓸 것')
                break
    return v


def check_position_vocab(html_doc, market='us'):
    """가격 섹션이 스탠스 등급을 되풀이하지 않는가."""
    v = []
    for title in VOCAB_SECTIONS[market]:
        seg = section_slice(html_doc, title)
        if seg is None:
            continue
        text = ' '.join(t for _, t in
                        [(a, _text(b)) for a, b in
                         re.findall(r'<p([^>]*)>(.*?)</p>', seg, re.S)])
        found = [w for w in BANNED_GRADE_WORDS if w in text]
        if _OW_UW.search(text):
            found.append('OW/UW')
        if found:
            v.append(f'{title}: 포지션 등급 어휘({", ".join(sorted(set(found)))})가 나왔다 — '
                     '스탠스는 멀티에셋 섹션에서만 말한다')
    return v


def check_lede(html_doc):
    """§2가 사건 → 의미 → 행동 → 무효화 순인가."""
    seg = section_slice(html_doc, '전략 코멘트')
    if seg is None:
        return ['섹션 「전략 코멘트」를 찾지 못했다']
    got = [k for k, _ in _marked(seg, 'data-lede')]
    v = []
    for key in LEDE_ORDER:
        if key not in got:
            v.append(f'§2: data-lede="{key}" 문단이 없다')
    if not v and got != list(LEDE_ORDER):
        v.append(f'§2: data-lede 순서가 {" → ".join(got)}이다 — '
                 f'{" → ".join(LEDE_ORDER)} 순이어야 한다')
    return v
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q`
Expected: 전부 통과

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/weight.py scripts/us/tests/test_weight.py
git commit -m "경로 블록의 가격 중복·가격 섹션의 포지션 어휘·§2 순서를 막는다"
```

---

### Task 7: `check()` 통합과 CLI

**Files:**
- Modify: `scripts/us/weight.py`
- Create: `scripts/check_weight.py`
- Test: `scripts/us/tests/test_weight.py`

**Interfaces:**
- Produces: `check(html, market='us', market_data=None, macro_eval=None) -> list[str]`
- CLI: `python3 scripts/check_weight.py --html <파일> --datadir <경로> --market us|kr`
  - exit 0 통과, exit 1 위반(한 줄씩), exit 2 파일 못 읽음

- [ ] **Step 1: 실패하는 테스트를 쓴다**

```python
from us.weight import check


def test_check_runs_every_gate_for_us():
    doc = _doc(US_FULL)  # Task 2의 헬퍼
    v = check(doc, market='us', market_data=MD, macro_eval={'abbreviated': False})
    # 합성 문서엔 data-lede도 data-standing도 없으므로 둘 다 걸려야 한다
    assert any('data-lede' in x for x in v)


def test_check_skips_us_only_gates_for_kr():
    doc = _doc({'오늘의 장': 700, '지수 & 장중': 900, '환율·금리': 700,
                '전략 코멘트': 700, '기술적 분석 & 트레이딩 전략': 500})
    v = check(doc, market='kr', market_data=MD, macro_eval=None)
    assert not any('§9' in x for x in v)
```

- [ ] **Step 2: 실패를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q -k check_`
Expected: FAIL — `ImportError: cannot import name 'check'`

- [ ] **Step 3: 최소 구현**

`weight.py`에 이어 붙인다.

```python
def check(html_doc, market='us', market_data=None, macro_eval=None):
    """모든 검사를 돌려 위반 문자열 리스트를 낸다. 빈 리스트면 발행 가능."""
    abbreviated = bool((macro_eval or {}).get('abbreviated'))
    pc = (market_data or {}).get('price_context') or {}
    v = []
    v += check_volume(measure(html_doc, market), abbreviated, market)
    v += check_standing(html_doc, pc, market)
    v += check_cause(html_doc, pc, market)
    v += check_position_vocab(html_doc, market)
    v += check_lede(html_doc)
    if market == 'us':
        v += check_macro_prices(html_doc, market_data)
    return v
```

`scripts/check_weight.py`를 만든다.

```python
#!/usr/bin/env python3
"""무게중심 게이트 — 시황·가격 대 판단·포지션.

  python3 scripts/check_weight.py --html morning_brief_2026-08-30.html --datadir . --market us
  python3 scripts/check_weight.py --html kr_brief_2026-08-30.html --datadir kr/data --market kr

Exit 0 = 발행 가능. Exit 1 = 위반이 한 줄씩 찍힌다 — 그대로 writer에게 돌려주고 다시 돌린다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.weight import check  # noqa: E402

MARKET_FILE = {'us': 'market_data.json', 'kr': 'kr_market_data.json'}


def _load(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--html', required=True)
    ap.add_argument('--datadir', default='data')
    ap.add_argument('--market', choices=('us', 'kr'), default='us')
    args = ap.parse_args()

    try:
        with open(args.html, encoding='utf-8') as fh:
            doc = fh.read()
    except OSError as e:
        print(f'FATAL: cannot read {args.html}: {e}', file=sys.stderr)
        sys.exit(2)

    market_data = _load(os.path.join(args.datadir, MARKET_FILE[args.market]))
    macro_eval = _load(os.path.join(args.datadir, 'macro_eval.json'))

    violations = check(doc, market=args.market, market_data=market_data,
                       macro_eval=macro_eval)
    if violations:
        for x in violations:
            print(x)
        sys.exit(1)
    day = '축약일' if (macro_eval or {}).get('abbreviated') else '발표일'
    print(f'OK — 무게중심 게이트 통과 ({day})')


if __name__ == '__main__':
    main()
```

- [ ] **Step 4: 통과를 확인한다**

Run: `python3 -m pytest scripts/us/tests/test_weight.py -q && python3 scripts/check_weight.py --html posts/2026-08-27.html --datadir data --market us; echo "exit=$?"`
Expected: 테스트 전부 통과. CLI는 **exit=1**이고 실측 판의 위반(비율·매크로 상한·data-standing 없음·data-lede 없음)이 찍힌다 — 이것이 게이트가 도는 증거다

- [ ] **Step 5: 커밋**

```bash
git add scripts/us/weight.py scripts/check_weight.py scripts/us/tests/test_weight.py
git commit -m "무게중심 게이트 CLI — 발행 직전에 돈다"
```

---

### Task 8: 작성 스펙 갱신 (US)

**Files:**
- Modify: `.claude/agents/brief-report-writer.md`

**이 태스크를 빠뜨리면 작성 담당이 서로 반대되는 지시를 동시에 받는다.**

- [ ] **Step 1: 「매크로 섹션을 넘기지는 않는다」를 지운다**

「시황 분량 (2026-08-28 사용자 지시…)」 문단에서 그 한 문장만 삭제하고 다음을 잇는다.

```
**시황이 매크로를 넘어서는 것이 정상이다 (2026-08-30 사용자 지시).** 2026-08-28의
「매크로 섹션을 넘기지는 않는다」는 폐기했다 — 「포지션보다는 시황정리 및 가격변동에
대한 설명 비중을 더 높이자」가 정확히 그 제약을 뒤집는다.
```

- [ ] **Step 2: §2 구조를 네 문단으로 고친다**

구조 목록 2번 항목을 통째로 바꾼다.

```
2. **전략 코멘트** — 헤드라인 바로 다음. 네 문단을 `<p data-lede="event">` → `"meaning"`
   → `"action"` → `"invalidation"` 순으로 쓴다. **첫 문단은 오늘 벌어진 일이고, 행동
   선언은 세 번째다** (2026-08-30 사용자 지시 「무슨 일이 있었나를 앞으로」). `action`
   문단의 첫 문장에서 `확대`·`유지`·`축소` 가운데 무엇인지와 시계(`다음 세션` 또는
   `2~6주`)를 밝힌다 — 이 규칙은 이제 `event`가 아니라 `action`에 걸린다. 라벨을 명사형
   머리말로 못 박지 않는다. 표와 수치는 아래 섹션이 책임지므로 문단당 핵심 수치 둘까지.
```

- [ ] **Step 3: 가격 섹션 사양에 「지금 어디에 있나」를 넣는다**

「가격 맥락 — 전 섹션 공통 사양」 절 앞에 다음을 넣는다.

```
### 가격 섹션은 「지금 어디에 있나」로 시작한다 (2026-08-30 사용자 지시)

기준은 **「이걸 본 사람이 요즘 주식시장·채권시장이 어떠냐는 질문에 대답할 수 있는가」**다.
2026-08-27 발행본은 「백분위」·「최고」·「최저」·「상위」·「하위」·「평소」가 전부 0회였다 —
시장이 어디에 서 있는지를 한 번도 말하지 않았다.

§4 주식 · §6 채권 · §7 FX · §8 원자재는 각각 `<p data-standing="equities|bonds|fx|
commodities">` 문단으로 시작한다(값은 넷 중 하나). 세 층을 담는다.

- **위치** — `price_context.levels`의 `percentile`·`band`. `sessions`가 504 미만이면
  「2년」이라 부르지 말고 그 기간으로 정확히 부른다
- **경로** — 1주·1개월 변화, 어떻게 여기까지 왔나
- **오늘의 크기** — `moves.multiple`·`band`. **「미미」면 미미하다고 쓴다**

그 뒤에 장중 궤적과 원인 서술이 온다 — **「지금 어디 → 오늘 무슨 일 → 왜」** 순서다.

`moves.band`가 `큼`·`매우 큼`인 자산은 `<p data-cause="...">` 문단을 더 갖는다.
`미미`·`보통`이면 면제다 — 조용한 날 분량을 채우려고 쓰지 말 것. 두 문단 모두 120자
이상이고 실제 수치를 하나 이상 인용한다.

**§10 스탠스 논거 칸에 갇힌 국면 서술을 본문으로 되돌린다.** 「30년물이 5.191%로 근
20년래 고점권을 완전히 벗어나지 못했다」가 채권시장의 위치를 말하는 유일한 문장인데
포지션 논거 칸에 들어가 있었다. VIX의 위치(14.51 = 하위 5.5%)도 §4 본문에서 다룬다.

**가격 섹션에서 스탠스 등급을 되풀이하지 않는다.** 「§9 포지션은 달러 소폭 숏을 그대로
유지하며」류 문장은 §10에서만 쓴다. 게이트가 등급 통제 어휘를 §3~§8에서 막는다.
```

- [ ] **Step 4: §9 사양에 축약일과 가격 인용 금지를 넣는다**

「섹션 9. 매크로 논리 — 상세 사양」 절 끝에 붙인다.

```
**경로 블록에 그날 가격을 쓰지 않는다 (2026-08-30).** 「오늘 DXY는 -0.04% 내린 99.13으로
마감해」 같은 문장은 자산 섹션에 이미 같은 수치로 있다 — 실측 중복 218자. `data-macro-group`
블록에는 3~6개월 경로 논리와 확인 지표만 남긴다.

**전일과 겹치는 날은 접는다 (2026-08-30 사용자 지시).** 판정은 `macro_eval.json`의
`abbreviated`가 하고 작성 담당은 그 값을 따른다 — 축 점수 z를 만지지 않는 것과 같은
계약이다. `abbreviated: true`면 §9는 **2,400자 이하**로:

- 레짐 — 유지. 무엇이고 며칠째이며 **무엇이 나와야 움직이나**
- 4축 진단 — **바뀐 축만 서술.** 안 바뀐 축은 배지와 표로만
- 신규 발표 해부 — tier 2 1건까지, 짧게
- 자산별 전달경로 — **방향 스트립만.** 서술은 「전일과 같다」 한 줄
- 정책 경로·시장 해석·다음 발표 일정 — 유지

**축약일에도 남는 의무 둘.** ① §10 스탠스와 부호가 어긋나는 자산군의 `data-reconcile`
해소 문단은 그대로 쓴다 — 경로를 접는 것과 모순을 침묵하는 것은 다르다. ② 「무엇이
나와야 이 판정이 움직이나」는 오히려 더 중요하다. 겹친다는 것은 기다리는 국면이라는
뜻이고, 무엇을 기다리는지가 그날 §9의 알맹이다.
```

- [ ] **Step 5: 커밋**

```bash
git add .claude/agents/brief-report-writer.md
git commit -m "US 작성 스펙 — 「지금 어디에 있나」와 축약일"
```

---

### Task 9: 작성 스펙 갱신 (KR)과 오케스트레이터 배선

**Files:**
- Modify: `.claude/agents/kr-report-writer.md`, `.claude/ORCHESTRATOR.md`, `.claude/KR_ORCHESTRATOR.md`

- [ ] **Step 1: KR §2를 네 문단으로 고친다**

구조 목록 2번의 「세 문단을 `오늘 무엇을 할까 → 왜 지금인가 → 이 판단이 틀렸다고 볼 조건` 순서로 쓴다」를 이렇게 바꾼다.

```
   네 문단을 `<p data-lede="event">`(오늘 벌어진 일) → `"meaning"`(그게 왜 중요한가) →
   `"action"`(그래서 무엇을 할까) → `"invalidation"`(틀렸다고 볼 조건) 순으로 쓴다.
   **행동 선언은 첫 문단이 아니라 세 번째다** (2026-08-30 사용자 지시). 위험 노출을
   `확대`·`유지`·`축소` 중 하나로 밝히고 시계를 붙이는 규칙은 `action` 문단에 걸린다.
```

- [ ] **Step 2: KR 가격 섹션에 `data-standing`을 넣는다**

구조 목록 4번(지수 & 장중)과 10번(환율·금리) 각각에 한 줄씩 더한다.

```
   - **「지금 어디에 있나」로 시작한다** (2026-08-30) — `<p data-standing="equities">`
     (환율·금리는 `"rates"`). 지수가 자기 이력에서 어디인지, 어떻게 여기까지 왔는지,
     오늘 움직임이 평소 대비 얼마나 큰지 세 층. 그 뒤에 장중 궤적이 온다.
```

- [ ] **Step 3: 두 오케스트레이터에 게이트를 건다**

`.claude/ORCHESTRATOR.md`의 스탠스 게이트 문단 뒤에 넣는다.

```
**무게중심 게이트** — run `python3 scripts/check_weight.py --html morning_brief_[DATE].html --datadir <workspace> --market us` from the repo clone. It fails the run when: the recap group (오늘의 장·주식·채권·FX·원자재) falls below its floor or below its ratio to the judgment group (전략 코멘트·매크로 논리·멀티에셋); the macro section breaks its cap or floor for the day's mode (발표일 ≤4,600 / 축약일 ≤2,400, read from macro_eval.json's `abbreviated`); a price section has no substantive `data-standing` paragraph; an asset whose move was 「큼」·「매우 큼」 has no `data-cause` paragraph; a §9 transmission block repeats a price the asset section already printed; a price section restates a stance grade; or §2's `data-lede` paragraphs are missing or out of order. Relaunch the writer with the exact violations.
```

`.claude/KR_ORCHESTRATOR.md`에는 `--datadir kr/data --market kr`로 같은 문단을 넣되 매크로·경로 항목은 뺀다.

- [ ] **Step 4: 두 오케스트레이터의 STEP 2.5 `--gate` 목록에 추가한다**

두 파일의 `--gate "python3 scripts/check_session.py ..."` 줄 뒤에 각각 한 줄 더한다.

```
  --gate "python3 scripts/check_weight.py --html {f} --datadir <workspace> --market us"
```

(KR은 `--datadir kr/data --market kr`)

- [ ] **Step 5: 커밋**

```bash
git add .claude/agents/kr-report-writer.md .claude/ORCHESTRATOR.md .claude/KR_ORCHESTRATOR.md
git commit -m "KR 작성 스펙과 두 오케스트레이터에 무게중심 게이트를 건다"
```

---

### Task 10: 프로젝트 메모리 갱신과 전체 회귀

**Files:**
- Modify: `/Users/daeyoung/Desktop/AI/report/CLAUDE.md`, `/Users/daeyoung/Desktop/AI/report/AGENTS.md`

- [ ] **Step 1: 「지켜야 할 규칙」에 항목을 더한다**

두 파일의 같은 자리(5번 문체 항목 뒤)에 넣는다.

```
6. **무게중심 = 시황·가격 > 판단·포지션** (2026-08-30 사용자 지시 「너무 포지션 위주라
   처음 읽는 사람은 뭔 소린지 모른다」 → 「포지션보다는 시황정리 및 가격변동에 대한 설명
   비중을 더 높이자」): 2026-08-27 실측에서 판단·포지션이 7,424자(53%)·시황·가격이
   3,676자(26%)였다. 세 장치로 되돌린다. ① **가격 섹션은 「지금 어디에 있나」로 시작한다**
   — `<p data-standing>`에 위치(`price_context.levels`의 백분위·밴드)·경로·오늘의 크기
   (`moves.band`) 세 층. 기준은 「이걸 본 사람이 요즘 주식·채권시장 어떠냐는 질문에
   대답할 수 있는가」. 발행본이 「백분위」·「최고」·「최저」·「평소」를 **한 번도** 쓰지
   않았던 것이 진단의 출발점이다. 크게 움직인 자산만 `<p data-cause>`로 원인까지 판다
   (미미·보통이면 면제 — 조용한 날 패딩 금지). ② **전일과 겹치는 날의 §9는 접는다** —
   tier 1 발표 없고 레짐·4축 방향·정책 경로가 전일과 같으면 `macro_eval.json`의
   `abbreviated`가 켜지고 §9는 2,400자 이하(전달경로는 방향 스트립만). 판정은
   `macro.evaluate()`가 하고 writer는 따른다. 레짐 이력상 대부분의 날이 축약일이라
   평균적으로 시황이 판단보다 커진다. ③ **게이트가 잰다** — `scripts/check_weight.py`가
   비율·상한·하한·표식·포지션 어휘·§2 순서(`data-lede` 사건→의미→행동→무효화)를 검사.
   폐기한 규칙 둘: 「매크로 섹션을 넘기지는 않는다」(2026-08-28)와 §2의 「첫 문장은
   확대·유지·축소」(이제 `action` 문단에만 걸린다). 로직 `scripts/us/weight.py`,
   설계 `docs/superpowers/specs/2026-08-30-recap-weight-rebalance-design.md`
```

- [ ] **Step 2: 전체 테스트를 돌린다**

Run: `python3 -m pytest scripts/ -q`
Expected: 기존 테스트 전부 통과 + `test_weight.py` 통과

- [ ] **Step 3: 실측 판으로 게이트를 돌려 본다**

Run: `python3 scripts/check_weight.py --html posts/2026-08-27.html --datadir data --market us; echo "exit=$?"`
Expected: exit=1. 위반 목록이 비율 0.50·매크로 4,788·`data-standing` 부재·`data-lede` 부재를 짚는다

- [ ] **Step 4: KR 실측 판으로도 돌려 본다**

Run: `python3 scripts/check_weight.py --html kr/posts/2026-08-27.html --datadir kr/data --market kr; echo "exit=$?"`
Expected: exit=1. 시황·가격군 하한과 `data-lede` 부재를 짚는다

- [ ] **Step 5: 커밋**

```bash
git add ../CLAUDE.md ../AGENTS.md
git commit -m "프로젝트 메모리 — 무게중심 규칙"
```

---

## 자체 검토

**스펙 커버리지**

| 스펙 절 | 태스크 |
|---|---|
| 설계 1 — 경로 블록 그날 가격 금지 | Task 6 (`check_macro_prices`), Task 8 Step 4 |
| 설계 1-b — 「지금 어디에 있나」·원인 문단 | Task 5, Task 8 Step 3, Task 9 Step 2 |
| 설계 2 — 가격 섹션 포지션 어휘 금지 | Task 6 (`check_position_vocab`) |
| 설계 3 — 분량 계약 | Task 2, Task 7 |
| 설계 4 — §2 순서 | Task 6 (`check_lede`), Task 8 Step 2, Task 9 Step 1 |
| 설계 5 — 축약일 | Task 3, Task 4, Task 8 Step 4 |
| 게이트 CLI·배선 | Task 7, Task 9 Steps 3–4 |
| 구현 주의(엔티티·`locate_section`·수치 정규화) | Task 1, Task 6 |
| 문서 갱신 대상 | Tasks 8–10 |

**미구현으로 남기는 것** — 스펙 「우회 차단」이 스스로 적어 둔 대로, 같은 문장을 표 칸에
복사하거나 형식적 `data-cause` 문단을 다는 길은 게이트가 막지 못한다. 팩트체크 단계에서
사람이 본다.

**타입 일관성** — `check_*` 함수는 전부 `list[str]`을 낸다. `measure`의 반환 키
(`sections`·`recap`·`judgment`·`ratio`·`missing`)는 Task 2에서 정의하고 Task 7에서만 쓴다.
`macro_eval['abbreviated']`는 Task 3이 만들고 Task 4·7이 읽는다.
