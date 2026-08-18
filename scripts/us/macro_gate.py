"""Publication gate for §8 (매크로 논리).

The writer can be told that a regime only moves on a new release; only a gate can
prove the published page obeyed it. Same division of labour as stance_gate, and the
same bluntness — a macro read that quietly drifts is the failure this exists to end.

One check here has no counterpart in §8: **reconciliation**. The macro book and the
stance book are read on the same axis but over different horizons, so they are allowed
to disagree. What they are not allowed to do is disagree silently.

Pure — `check()` takes strings and dicts and returns a list of violation messages.
"""

import re

from .macro import (REGIME_NAMES, TRANSMISSION_ASSETS, TRANSMISSION_GROUPS,
                    TRANSMISSION_LABELS, conflicts, regime_name)
from .stance_gate import locate_section, number_forms, strip_tags

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


def section_macro(html):
    return locate_section(html, '매크로 논리')


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


def parse_group_blocks(section):
    """{group key: prose} — each block runs to the next group marker or section end.

    Slicing on the marker rather than on a matching close tag keeps this indifferent to
    how the writer nests the block, which is one less thing for a gate to be brittle about.
    """
    hits = [(m.group(1), m.start()) for m in _GROUP.finditer(section or '')]
    out = {}
    for n, (key, at) in enumerate(hits):
        end = hits[n + 1][1] if n + 1 < len(hits) else len(section)
        out[key] = strip_tags(section[at:end])
    return out


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

    _check_groups(section, v)
    return cells


def _check_groups(section, v):
    """Every channel gets a narrated block, and every block names a number.

    The strip alone would say what the macro likes without ever saying why, and a
    block with no figure in it is the 「추이 확인 필요」 non-answer wearing a heading.
    """
    blocks = parse_group_blocks(section)
    for key, label, _ in TRANSMISSION_GROUPS:
        text = blocks.get(key)
        if text is None:
            v.append(f'§8: {label} 서술 블록이 없다 — <div data-macro-group="{key}">로 감쌀 것')
        elif not re.search(r'\d', text):
            v.append(f'§8 {key}({label}): 확인 지표가 수치로 없다 — '
                     '「추이 확인 필요」류 무판정 문구는 금지')


def _check_reconciliation(section, next_macro, stance, v):
    if not stance:
        return
    clash = conflicts((next_macro or {}).get('transmission'), stance)
    for key in clash:
        if f'data-reconcile="{key}"' not in section:
            v.append(f'§8 {key}: 매크로 방향과 §9 스탠스 등급이 반대인데 해소 문단이 없다 '
                     f'— 해당 문단에 data-reconcile="{key}"를 달 것')


def _check_policy(text, prev_macro, macro_eval, next_macro, v):
    prev = (prev_macro or {}).get('policy_path') or {}
    nxt = (next_macro or {}).get('policy_path') or {}
    if not nxt:
        v.append('macro_next.json에 policy_path가 없다')
        return

    prob = nxt.get('prob_pct')
    if prob is None:
        v.append('macro_next.json policy_path에 prob_pct가 없다 — '
                 'FedWatch 수치 없이는 정책 경로를 검증할 수 없다')
    elif not _cited(text, prob):
        v.append(f'§8: 정책 경로 확률 {prob}%가 본문에 인용되지 않았다')

    if not prev.get('timing') or nxt.get('timing') == prev.get('timing'):
        return
    if (macro_eval or {}).get('new_releases'):
        return
    old = prev.get('prob_pct')
    moved = (old is not None and prob is not None and abs(prob - old) >= PROB_JUMP_PP)
    if not moved:
        v.append(f'§8: 정책 경로를 "{prev.get("timing")}"에서 "{nxt.get("timing")}"으로 '
                 f'옮겼는데 신규 지표 발표도, {PROB_JUMP_PP:.0f}%p 이상의 확률 이동도 없다')


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


def check(html, prev_macro, macro_eval, next_macro, stance=None):
    section = section_macro(html)
    if section is None:
        return ['§8(매크로 논리) 섹션을 찾을 수 없다']
    text = strip_tags(section)
    v = []

    regime_cell = _check_regime(section, text, macro_eval, v)
    trans_cells = _check_transmission(section, macro_eval, v)
    _check_reconciliation(section, next_macro, stance, v)
    _check_policy(text, prev_macro, macro_eval, next_macro, v)
    _check_next(next_macro, prev_macro, regime_cell, trans_cells,
                (macro_eval or {}).get('report_date'), v)
    return v
