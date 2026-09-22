"""Publication gate for §8 (매크로).

The writer can be told that a regime only moves on a new release; only a gate can
prove the published page obeyed it. Same division of labour as the other gates, and the
same bluntness — a macro read that quietly drifts is the failure this exists to end.

2026-09-19 에 스탠스 책이 없어지면서 **해소(reconciliation) 검사가 짝을 잃었다.** 그
검사는 매크로 방향과 스탠스 등급의 부호가 어긋날 때 해소 문단을 강제했다. 그 자리를
`check_falsifier` 가 대신한다 — 매크로가 「무엇이 나오면 이 판단이 틀린 것인가」를
지면에 밝히게 한다. 성적표가 채점하는 대상이 이제 이 판정이므로, 독자도 그 탈출
조건을 볼 수 있어야 한다.

Pure — `check()` takes strings and dicts and returns a list of violation messages.
"""

import re

from .macro import (REGIME_NAMES, TRANSMISSION_ASSETS, TRANSMISSION_GROUPS,
                    TRANSMISSION_LABELS, conflicts, regime_name)
from .section import locate_section, number_forms, strip_tags
from . import moomoo_forward as _MF

_REGIME = re.compile(
    r'<span\b(?P<attrs>[^>]*\bdata-macro\s*=\s*"regime"[^>]*)>(?P<text>.*?)</span>', re.S)
_TRANS = re.compile(
    r'<span\b(?P<attrs>[^>]*\bdata-macro-asset\s*=\s*"(?P<asset>[a-z_]+)"[^>]*)>'
    r'(?P<text>.*?)</span>', re.S)
_GROWTH = re.compile(r'\bdata-growth\s*=\s*"(-?\d+)"')
_INFLATION = re.compile(r'\bdata-inflation\s*=\s*"(-?\d+)"')
_DIRECTION = re.compile(r'\bdata-direction\s*=\s*"(-?\d+)"')

# A policy call may re-time without a fresh print only when the market itself repriced
# hard — anything smaller is the writer redecorating yesterday's view.
PROB_JUMP_PP = 15.0


MACRO_TITLE = '매크로'


def section_macro(html):
    """제목이 **정확히** 「매크로」인 섹션. 옛 「매크로 논리」는 통과하지 못한다."""
    return locate_section(html, MACRO_TITLE, exact=True)


def section_econ(html):
    """Where the indicator tables live, and so where the dissection of a new print
    belongs (2026-08-18 사용자 지시: 수치가 있는 곳에 해설을 붙인다).

    Since 2026-08-20 the tables sit inside §8, one under each axis diagnosis, so there
    is usually no separate 경제지표 section to find; older briefs kept one at the back.
    """
    return locate_section(html, '경제지표')


def parse_regime_cell(section):
    m = _REGIME.search(section or '')
    if not m:
        return None
    g = _GROWTH.search(m.group('attrs'))
    i = _INFLATION.search(m.group('attrs'))
    return {
        'growth': int(g.group(1)) if g else None,
        'inflation': int(i.group(1)) if i else None,
        'text': strip_tags(m.group('text')).strip(),
    }


_GROUP = re.compile(r'\bdata-macro-group\s*=\s*"([a-z_]+)"')
_RELEASE = re.compile(r'\bdata-release\s*=\s*"([a-z0-9-]+)"')
_SECTION = re.compile(r'<(section)\b')
_AXIS = re.compile(r'\bdata-axis\s*=\s*"([A-Za-z]+)"')
_NUM = re.compile(r'\d+(?:\.\d+)?')
_YEAR = re.compile(r'^(?:19|20)\d{2}$')

# Known statistical agencies — naming one (or linking the release) is how the block
# shows it went to the source rather than paraphrasing the dashboard row.
AGENCIES = ('BLS', 'BEA', 'Census', 'DOL', 'NAR', 'Federal Reserve', 'U. Michigan',
            '노동통계국', '경제분석국', '센서스국', '노동부', '연준')

# Headline + at least two component figures. A block that names one number has not
# taken anything apart; it has restated the dashboard.
MIN_RELEASE_FIGURES = 3

# When macro_metrics.json carried a breakdown, name at least this many of its lines.
MIN_CITED_COMPONENTS = 2

# Names of things that exist only inside the pipeline. A reader seeing "research_notes.md"
# learns nothing and loses trust in everything around it — the 2026-08-17 brief shipped
# "(8월 중순 기준 67~69% 범위로 보도, research_notes.md)".
INTERNAL_ARTIFACTS = (
    'research_notes.md', 'market_data.json', 'intraday.json', 'econ_indicators.json',
    'macro.json', 'macro_eval.json', 'macro_metrics.json', 'macro_next.json',
    'sector_performance.html', 'releases/index.json',
)

# Instrument jargon. The score belongs to the machinery; the page gets 방향과 강도.
INTERNAL_JARGON = ('signed-z', 'signed_z', 'z스코어', 'z-스코어', 'z-score',
                   '모멘텀 z', 'momentum_z', 'allowed_grades', 'allowed_regimes',
                   'headline_releases', 'new_releases', 'last_seen')

# 2026-08-22 사용자 지시: 발행본에서 「buy-side」를 쓰지 않는다. 같은 자리를
# 전략·리포트·시황 정리로 부른다 (§2 헤더는 「전략 코멘트」, 섹션 박스는 「전략 해석」).
BANNED_LABELS = ('buy-side', 'buy side', 'buyside', '바이사이드')


def _blocks(section, wanted):
    """{key: prose} for markers of one kind, each sliced to the next marker of ANY kind.

    Slicing on markers rather than on a matching close tag keeps this indifferent to how
    the writer nests things. The boundary has to span every marker kind, though —
    otherwise a release block runs on into the channel blocks below it and inherits
    their figures, which would let a bare headline number pass the anatomy check.
    """
    section = section or ''
    hits = sorted((m.start(), kind, m.group(1))
                  for kind, pat in (('release', _RELEASE), ('group', _GROUP),
                                    ('__section__', _SECTION))
                  for m in pat.finditer(section))
    out = {}
    for n, (at, kind, key) in enumerate(hits):
        if kind != wanted:
            continue
        end = hits[n + 1][0] if n + 1 < len(hits) else len(section)
        out[key] = strip_tags(section[at:end])
    return out


def parse_group_blocks(section):
    return _blocks(section, 'group')


def parse_release_blocks(section):
    return _blocks(section, 'release')


def _figures(text):
    """Distinct numeric tokens, with bare years dropped — a date is not a data point."""
    return {t for t in _NUM.findall(text or '') if not _YEAR.match(t)}


def parse_transmission_cells(section):
    out = {}
    for m in _TRANS.finditer(section or ''):
        d = _DIRECTION.search(m.group('attrs'))
        out[m.group('asset')] = {
            'direction': int(d.group(1)) if d else None,
            'text': strip_tags(m.group('text')).strip(),
        }
    return out


def _cited(text, value):
    return any(f in text for f in number_forms(value))


def _check_regime(section, text, macro_eval, v):
    cell = parse_regime_cell(section)
    if not cell:
        v.append('§8: data-macro="regime" 표식이 없다 — 게이트가 국면을 읽을 수 없다')
        return None
    g, i = cell['growth'], cell['inflation']
    if g is None or i is None:
        v.append('§8: 레짐 표식에 data-growth / data-inflation이 없다')
        return None
    if (g, i) not in REGIME_NAMES:
        v.append(f'§8: 레짐 좌표 ({g}, {i})는 3×3 격자 밖이다')
        return cell
    want = regime_name(g, i)
    # Exact, not containment: "중립~우호" contains "우호" and would otherwise sail
    # through, which is precisely the hedged-wording drift the vocabulary exists to
    # stop. The marker span holds the label alone — nuance goes outside it.
    if cell['text'] != want:
        v.append(f'§8: ({g}, {i})의 통제 어휘는 "{want}"인데 "{cell["text"]}"로 적혀 있다')

    allowed = (macro_eval or {}).get('allowed_regimes')
    if allowed and [g, i] not in allowed:
        v.append(f'§8: 레짐 [{g}, {i}]는 허용 범위 {allowed} 밖이다 (승계 규율 위반)')

    scores = (macro_eval or {}).get('scores') or {}
    for key, ko in (('growth_score', '성장'), ('inflation_score', '인플레')):
        val = scores.get(key)
        if val is not None and not _cited(text, val):
            v.append(f'§8: {ko}축 점수 {val}가 본문에 없다 — '
                     '축 점수를 밝히지 않으면 레짐 라벨을 검증할 수 없다')
    return cell


def _check_transmission(section, macro_eval, v):
    cells = parse_transmission_cells(section)
    missing = [k for k in TRANSMISSION_ASSETS if k not in cells]
    if missing:
        v.append(f"§8 방향 스트립에 표식이 없는 자산군: {', '.join(missing)}")

    ev_trans = (macro_eval or {}).get('transmission') or {}
    for key, cell in cells.items():
        if key not in TRANSMISSION_ASSETS:
            v.append(f'§8: 알 수 없는 전달경로 표식 "{key}"')
            continue
        d = cell['direction']
        if d is None:
            v.append(f'§8 {key}: data-direction 속성이 없다')
            continue
        if d not in TRANSMISSION_LABELS:
            v.append(f'§8 {key}: 방향 {d}는 범위 밖이다')
            continue
        want = TRANSMISSION_LABELS[d]
        if cell['text'] != want:
            v.append(f'§8 {key}: 방향 {d}의 통제 어휘는 "{want}"인데 '
                     f'"{cell["text"]}"로 적혀 있다')
        allowed = (ev_trans.get(key) or {}).get('allowed_directions')
        if allowed and d not in allowed:
            v.append(f'§8 {key}: 방향 {d}는 허용 범위 {allowed} 밖이다')

    _check_groups(section, v, abbreviated=bool((macro_eval or {}).get('abbreviated')))
    return cells


def _check_groups(section, v, abbreviated=False):
    """Every channel gets a narrated block, and every block names a number.

    The strip alone would say what the macro likes without ever saying why, and a
    block with no figure in it is the 「추이 확인 필요」 non-answer wearing a heading.

    On an abbreviated day (설계 5, 2026-08-30) the channels collapse to the direction
    strip on purpose — yesterday's reading still stands, so restating it is the
    duplication we set out to remove. Demanding the prose here would block
    publication every quiet day, and most days are quiet.
    """
    if abbreviated:
        return
    blocks = parse_group_blocks(section)
    for key, label, _ in TRANSMISSION_GROUPS:
        text = blocks.get(key)
        if text is None:
            v.append(f'§8: {label} 서술 블록이 없다 — <div data-macro-group="{key}">로 감쌀 것')
        elif not re.search(r'\d', text):
            v.append(f'§8 {key}({label}): 확인 지표가 수치로 없다 — '
                     '「추이 확인 필요」류 무판정 문구는 금지')


def _check_releases(html, macro_eval, v):
    """A new print must be taken apart, not just quoted.

    The dashboard already prints the headline number; this section exists to say what
    moved underneath it and what to make of that. So the block has to reach the issuing
    agency's release and carry the components, or it is adding nothing.
    """
    wanted = (macro_eval or {}).get('headline_releases') or []
    if not wanted:
        return
    scope = section_econ(html) or html
    blocks = parse_release_blocks(scope)
    for rel in wanted:
        key = rel.get('key')
        label = rel.get('label') or key
        text = blocks.get(key)
        if text is None:
            v.append(f'§8: 신규 발표 「{label}」 해부 블록이 없다 — 해당 축 지표 표 아래에 '
                     f'<div data-release="{key}">로 감쌀 것')
            continue

        primary = next((i for i in rel.get('indicators') or []
                        if i.get('name') == rel.get('primary')), None)
        if primary and primary.get('actual') is not None \
                and not _cited(text, primary['actual']):
            v.append(f'§8 {key}: 「{label}」 블록에 {primary["name"]} 실제값 '
                     f'{primary["actual"]}이 없다')

        has_source = (any(a in text for a in AGENCIES) or 'http' in text
                      or (rel.get('agency') and rel['agency'] in text))
        if not has_source:
            agency = rel.get('agency') or '발표 기관'
            v.append(f'§8 {key}: 「{label}」 블록에 원본 발표 출처가 없다 — '
                     f'{agency}의 릴리스를 근거로 밝힐 것')

        # When the breakdown was collected deterministically we can ask the precise
        # question — did the writer actually name the lines that moved? — instead of
        # settling for "are there enough numbers in here".
        comps = [c for c in (rel.get('components') or []) if c.get('actual') is not None]
        if comps:
            cited = [c for c in comps if _cited(text, c['actual'])]
            if len(cited) < MIN_CITED_COMPONENTS:
                names = ', '.join(f'{c["label"]} {c["actual"]}' for c in comps[:5])
                v.append(f'§8 {key}: 「{label}」 블록이 구성 항목을 {len(cited)}개만 인용했다 '
                         f'— {MIN_CITED_COMPONENTS}개 이상 필요. '
                         f'macro_metrics.json에 있는 것: {names}')
        elif len(_figures(text)) < MIN_RELEASE_FIGURES:
            v.append(f'§8 {key}: 「{label}」 블록이 헤드라인 수치에서 멈췄다 — '
                     '무엇이 그 숫자를 만들었는지 세부 항목을 수치로 분해할 것')


_COMMENT_CARD = re.compile(r'<h4[^>]*>\s*시장 해석\s*</h4>')


def _check_quiet_day(section, macro_eval, v):
    """No new print, no commentary (2026-08-20 사용자 지시).

    The card exists to say how the market took today's number. On a day without one it
    has nothing to be about, and the 08-19 brief proved it: 「오늘은 새로 발표된 헤드라인
    경제지표가 없는 날이었다」 followed by a paragraph the 시황 sections had already run.
    The tables and the next-release calendar stay; the comment goes.
    """
    if (macro_eval or {}).get('headline_releases'):
        return
    if _COMMENT_CARD.search(section or ''):
        v.append('§8: 오늘은 신규 발표가 없는데 「시장 해석」 카드가 있다 — '
                 '발표 없는 날은 축 표까지만 두고 코멘트를 달지 않는다')


AXES = ('Labor', 'Activity', 'Consumption', 'Inflation')


def _check_axis_strip(section, v):
    """Four badges before the prose, so the diagnosis is scannable before it is read.

    The same lever that fixed the transmission block: a reader who wants the verdict
    should not have to parse four paragraphs to assemble it.
    """
    found = set(_AXIS.findall(section or ''))
    missing = [a for a in AXES if a not in found]
    if missing:
        v.append(f"§8 4축 진단 스트립에 표식이 없는 축: {', '.join(missing)} — "
                 '문단 앞에 <span data-axis="AXIS">방향</span> 배지를 둘 것')


def _check_hygiene(html, v):
    """Nothing that only exists inside the pipeline may appear on the published page."""
    text = strip_tags(html)
    for name in INTERNAL_ARTIFACTS:
        if name in text:
            v.append(f'발행본에 내부 파일명 "{name}"이 노출됐다 — '
                     '출처는 발표 기관·매체 이름으로 쓸 것')
    for word in INTERNAL_JARGON:
        if word in text:
            v.append(f'발행본에 내부 지표 용어 "{word}"가 노출됐다 — '
                     '방향(개선/악화/보합)과 강도(뚜렷/완만)로 바꿔 쓸 것')
    low = text.lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'발행본에 buy-side 표기("{word}")가 남았다 — '
                     '전략·리포트·시황 정리로 부를 것 (§2 헤더는 「전략 코멘트」)')
            break


def check_falsifier(html, next_macro):
    """정책 경로의 반증조건이 **지면에 실렸는지**.

    2026-09-19 에 스탠스 책이 없어지면서 `_check_reconciliation` 이 짝을 잃었다 —
    그 검사는 매크로 방향과 스탠스 등급의 부호가 어긋날 때 해소 문단을 강제했다.
    대신 스탠스가 지던 **「무엇이 나오면 이 판단이 바뀌나」**를 매크로가 넘겨받는다.
    `falsifier` 는 지금까지 JSON 에만 있고 지면에 나올 의무가 없었는데, 성적표가
    채점하는 대상이 이 판정이 된 이상 독자도 그 조건을 볼 수 있어야 한다.
    """
    want = ((next_macro or {}).get('policy_path') or {}).get('falsifier')
    if not want:
        return []
    section = locate_section(html, MACRO_TITLE, exact=True) or html
    for m in re.finditer(r'<p\b[^>]*\bdata-falsifier\s*=\s*"[^"]*"[^>]*>(.*?)</p>',
                         section, re.S):
        if len(strip_tags(m.group(1)).strip()) >= 20:
            return []
    return ['정책 경로의 반증조건이 지면에 없다 — 그 문단에 `data-falsifier="1"` 을 '
            '달고 무엇이 나오면 이 판단이 바뀌는지 쓸 것']

def _check_policy(text, prev_macro, macro_eval, next_macro, v, fedwatch=None,
                  fedwatch_present=False):
    prev = (prev_macro or {}).get('policy_path') or {}
    nxt = (next_macro or {}).get('policy_path') or {}
    if not nxt:
        v.append('macro_next.json에 policy_path가 없다')
        return

    prob = nxt.get('prob_pct')
    if prob is None:
        # 원천이 둘 다 없는 날까지 숫자를 요구하면 지어내라는 말이 된다.
        # **면제는 명시적일 때만** — 사유를 적고 비워야 통과한다(2026-09-22
        # codex 검토 P1-8). 전일 확률을 복사하거나 0으로 채우면 여전히 실패다.
        if nxt.get('prob_status') in ('unavailable', 'unverified') and nxt.get('prob_note'):
            pass
        else:
            v.append('macro_next.json policy_path에 prob_pct가 없다 — '
                     'FedWatch 수치 없이는 정책 경로를 검증할 수 없다. 원천이 '
                     '없는 날이면 prob_status 와 prob_note 를 적을 것')

    elif not _cited(text, prob):
        v.append(f'§8: 정책 경로 확률 {prob}%가 본문에 인용되지 않았다')

    _check_prob_source(prob, nxt, fedwatch, v, fedwatch_present)

    _check_axis_directions(macro_eval, next_macro, v)

    if not prev.get('timing') or nxt.get('timing') == prev.get('timing'):
        return
    # 축약일은 「전일과 겹쳐 새로 쓸 것이 없는 날」이다. 그런 날 시점을 옮겼다면
    # 확률이 아무리 움직였어도 축약 판정 자체를 다시 봐야 한다 — macro.py의
    # 「축약일 정책 변경은 게이트가 따로 막는다」는 주석이 여기 없으면 거짓말이 된다
    # (2026-09-06 codex 검토: 축약일 + timing 변경 + 50→70이 통과했다).
    if (macro_eval or {}).get('abbreviated'):
        v.append(f'§8: 축약일인데 정책 경로를 "{prev.get("timing")}"에서 '
                 f'"{nxt.get("timing")}"으로 옮겼다 — 새로 쓸 것이 없는 날로 판정해 놓고 '
                 f'시점을 바꿀 수는 없다. 축약 판정을 다시 볼 것')
        return
    if (macro_eval or {}).get('new_releases'):
        return
    old = prev.get('prob_pct')
    if prev.get('prob_meeting') is not None and not _MF.same_event(prev, nxt):
        # 회의나 구간을 갈아탄 뒤의 확률 차이는 시장의 이동이 아니다.
        # 9월 회의 40% → 10월 회의 100% 가 +60%p 로 읽혀 시점 변경을
        # 승인하던 경로다(2026-09-22 codex 구현 검토 P1-2).
        v.append(f'§8: 정책 경로를 "{prev.get("timing")}"에서 "{nxt.get("timing")}"으로 '
                 f'옮겼는데, 전일과 오늘의 확률이 같은 사건이 아니다 '
                 f'(전일 {prev.get("prob_meeting")}/{prev.get("prob_range_lower")}, '
                 f'오늘 {nxt.get("prob_meeting")}/{nxt.get("prob_range_lower")}) — '
                 f'비교 불가능한 확률 변화로 시점을 옮길 수 없다')
        return
    moved = (old is not None and prob is not None and abs(prob - old) >= PROB_JUMP_PP)
    if not moved:
        v.append(f'§8: 정책 경로를 "{prev.get("timing")}"에서 "{nxt.get("timing")}"으로 '
                 f'옮겼는데 신규 지표 발표도, {PROB_JUMP_PP:.0f}%p 이상의 확률 이동도 없다')


# 매크로 4축. macro.AXIS_KO와 같은 키이며, 내일의 축약일 판정이 이 넷을 대조한다.
AXES = ('Labor', 'Activity', 'Consumption', 'Inflation')


def _check_axis_directions(macro_eval, next_macro, v):
    """4축 방향의 승계 계약. **존재만 봐서는 못 막는다** — 예전 검사는 truthy만
    보았고 `{'junk': 'x'}`도 통과했다(2026-09-06 codex 검토에서 재현).

    이 값이 빠지면 다음날 `macro._abbreviated()`는 대조할 전일 값이 없어 4축 조건을
    **통과로 본다** — 축이 실제로 뒤집힌 날에도 §9가 접힌다. 방향이 반대로 적혀
    있던 옛 주석(「접히지 않는다」)은 동작과 어긋난 설명이었다.
    """
    carried = (next_macro or {}).get('axis_directions')
    if not carried:
        v.append('macro_next.json에 axis_directions가 없다 — '
                 '4축 방향을 승계하지 않으면 다음날 축약일 판정이 무력해진다')
        return
    missing = [a for a in AXES if not carried.get(a)]
    if missing:
        v.append(f'macro_next.json axis_directions에 {", ".join(missing)}이(가) 비었다 — '
                 f'네 축 {", ".join(AXES)}를 모두 담을 것')
        return
    today = (macro_eval or {}).get('axis_directions') or {}
    off = [f'{a} {carried[a]}≠{today[a]}' for a in AXES
           if today.get(a) is not None and carried[a] != today[a]]
    if off:
        v.append(f'macro_next.json axis_directions가 오늘 계산값과 다르다({", ".join(off)}) — '
                 f'macro_eval.json의 값을 그대로 복사할 것')


def _check_next(next_macro, prev_macro, regime_cell, trans_cells, report_date, v):
    if not next_macro:
        v.append('macro_next.json이 없다 — 내일 매크로 책이 얼어붙는다')
        return
    if report_date and next_macro.get('report_date') != report_date:
        v.append(f'macro_next.json report_date가 {next_macro.get("report_date")}로 '
                 f'오늘({report_date})과 다르다')

    reg = next_macro.get('regime') or {}
    g, i = reg.get('growth'), reg.get('inflation')
    if (g, i) not in REGIME_NAMES:
        v.append(f'macro_next.json: 레짐 좌표 ({g}, {i})가 3×3 격자 밖이다')
    elif regime_cell and regime_cell.get('growth') is not None:
        if (g, i) != (regime_cell['growth'], regime_cell['inflation']):
            v.append(f'macro_next.json: 레짐 ({g}, {i})가 §8 표식의 '
                     f'({regime_cell["growth"]}, {regime_cell["inflation"]})와 다르다')

    prev_reg = (prev_macro or {}).get('regime') or {}
    if prev_reg and (prev_reg.get('growth'), prev_reg.get('inflation')) != (g, i):
        if report_date and reg.get('since') != report_date:
            v.append(f'macro_next.json: 레짐이 바뀌었는데 since가 {reg.get("since")}로 '
                     '오늘이 아니다')
        hist = [h for h in (next_macro.get('history') or [])
                if h.get('date') == report_date]
        if not hist:
            v.append('macro_next.json: 레짐이 바뀌었는데 history에 오늘 기록이 없다')

    nxt_trans = next_macro.get('transmission') or {}
    prev_trans = (prev_macro or {}).get('transmission') or {}
    for key in TRANSMISSION_ASSETS:
        row = nxt_trans.get(key)
        if not row:
            v.append(f'macro_next.json에 {key} 전달경로가 없다')
            continue
        d = row.get('direction')
        if d not in TRANSMISSION_LABELS:
            v.append(f'macro_next.json {key}: 방향 {d}가 범위 밖이다')
            continue
        cell = trans_cells.get(key)
        if cell and cell.get('direction') is not None and cell['direction'] != d:
            v.append(f'macro_next.json {key}: 방향 {d}가 §8 표의 '
                     f'{cell["direction"]}와 다르다')
        old = (prev_trans.get(key) or {}).get('direction')
        if old is not None and old != d and report_date and row.get('since') != report_date:
            v.append(f'macro_next.json {key}: 방향이 {old}→{d}로 바뀌었는데 since가 '
                     f'{row.get("since")}로 오늘이 아니다')


def _check_prob_source(prob, nxt, fedwatch, v, present=False):
    """인쇄된 확률이 **승인된 원천값과 같은가**.

    지금까지 `prob_pct` 는 에이전트가 만든 수치와 에이전트가 만든 `macro_next`
    를 대조할 뿐이었다. 그러면 다음 회의가 바뀌었거나 특정 구간 확률과 누적
    확률을 섞었어도 통과한다. 확률은 **회의일·목표구간·공급자**에 묶여야
    비교된다(2026-09-22 codex 검토 P1-7).
    """
    if prob is None:
        return
    if not fedwatch:
        # **파일이 있는데 승인되지 않은 것**과 **원천이 아예 없는 것**은 다르다.
        # 앞은 맥이 꺼져 어제 파일이 남았거나 세션이 어긋난 날이고, 그 숫자를
        # 통과시키면 장부에 적힌 값 자체가 무검증이다(codex 구현 검토 P1-1).
        # 뒤는 아직 이 경로를 쓰지 않는 날이라 기존 계약대로 둔다 — 원천 필수화는
        # 작성 계약(`.claude/agents/`)을 함께 바꿔야 하는 광범위 수정이라
        # spec 의 열린 항목에 단계로 남겼다.
        if present:
            v.append(f'§8: FedWatch 파일은 있으나 승인되지 않았는데 확률 {prob}% 를 '
                     f'인쇄했다 — 상태나 대상 세션이 정본과 어긋난다. 원천을 다시 '
                     f'받거나, prob_pct 를 비우고 prob_status 와 prob_note 를 적을 것')
        return
    meeting = nxt.get('prob_meeting')
    lower = nxt.get('prob_range_lower')
    if meeting is None or lower is None:
        v.append('§8: FedWatch 원천이 승인됐는데 macro_next.policy_path 에 '
                 'prob_meeting / prob_range_lower 가 없다 — 어느 회의의 어느 '
                 '구간 확률인지 밝히지 않으면 원천 대조가 불가능하다')
        return
    approved = _MF.find_probability(fedwatch, meeting_date=meeting, lower_pct=lower,
                                    upper_pct=nxt.get('prob_range_upper'))
    if approved is None:
        v.append(f'§8: 승인된 FedWatch 장부에 {meeting} / 하단 {lower}% 구간이 '
                 f'없다 — 존재하지 않는 사건의 확률을 인쇄하고 있다')
    elif abs(float(prob) - float(approved)) > 0.05:
        v.append(f'§8: 정책 경로 확률 {prob}% 가 원천값 {approved}% 와 다르다 '
                 f'({meeting} / 하단 {lower}%)')


def check(html, prev_macro, macro_eval, next_macro, fedwatch=None,
          fedwatch_present=False):
    section = section_macro(html)
    if section is None:
        return ['§8(매크로) 섹션을 찾을 수 없다']
    text = strip_tags(section)
    v = []

    _check_hygiene(html, v)
    regime_cell = _check_regime(section, text, macro_eval, v)
    _check_axis_strip(section, v)
    _check_quiet_day(section, macro_eval, v)
    _check_releases(html, macro_eval, v)
    trans_cells = _check_transmission(section, macro_eval, v)
    v.extend(check_falsifier(html, next_macro))
    _check_policy(text, prev_macro, macro_eval, next_macro, v, fedwatch,
                  fedwatch_present)
    _check_next(next_macro, prev_macro, regime_cell, trans_cells,
                (macro_eval or {}).get('report_date'), v)
    return v
