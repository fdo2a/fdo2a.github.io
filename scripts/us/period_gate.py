"""주간·월간 정리의 발행 게이트.

이 리포트는 그 기간 발행본의 총정리다. 그래서 두 가지를 본다 —
**원본에 없던 숫자를 지어내지 않았는가**, 그리고 **원본의 어느 하루를 통째로
빠뜨리지 않았는가**. 뒤쪽은 총정리에만 있는 검사다: 요약은 빠뜨려도 티가 안 나고,
빠진 그날의 사건은 어디에도 남지 않는다.
"""

import re

from us.macro_gate import BANNED_LABELS
from us.post_check import banned_markers, body_text, data_tokens, mask_dates

INTERNAL_TERMS = ('weekly.json', 'monthly.json', 'scorecard.json', 'recap_source.json',
                  'stance.jsonl', 'macro.jsonl', 'market_data.json', 'research_notes.md',
                  'macro_metrics.json', 'kr_flows.json', '_sessions',
                  'signed-z', 'allowed_grades', 'basket_excess_pct')

_NUM = re.compile(r'-?\d+(?:\.\d+)?')


def _canon(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else f'{f:.10g}'


# 날짜 문자열이 들어 있는 필드. 여기서 뽑은 「-17」이 허용 수치가 되면 「-17%」 창작이
# 그대로 통과한다(2026-08-30 codex 검토).
_DATE_KEY = re.compile(r'^\d{4}-\d{2}(-\d{2})?$|^\d{4}-W\d{2}$')

_DATE_FIELDS = ('date', 'start_date', 'end_date', 'since', 'released', 'ref_period',
                'generated', 'key', 'bvps_as_of', 'flows_date')


def _numbers(obj, out=None):
    out = set() if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            # 날짜를 담는 필드의 값은 수치가 아니다 — 「2026-08-17」에서 -17 이 허용
            # 토큰이 되면 「-17%」 창작이 그대로 통과한다(2026-08-30 codex 검토).
            if k in _DATE_FIELDS:
                continue
            # 키 자체는 토큰으로 남긴다 — 「S&P 500」·「2s10s」처럼 이름에 든 숫자는
            # 본문이 정당하게 부른다. 날짜꼴 키만 뺀다.
            if not (isinstance(k, str) and _DATE_KEY.match(k)):
                _numbers(k, out)
            _numbers(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _numbers(v, out)
    elif isinstance(obj, bool):
        pass
    elif isinstance(obj, (int, float)):
        _add(out, obj)
    elif isinstance(obj, str):
        # 문자열 **안의** 날짜를 가린 뒤 센다. 필드명 제외만으로는 부족하다 — series 는
        # 값이 [날짜, 수치] 리스트라 키 이름이 없고, 회수한 발행본의 헤드라인·요약에는
        # 날짜가 문장 속에 박혀 있다. 「2026-08-21」이 -21 로 뜯겨 허용 집합에 섞이면
        # 「-21%」 창작이 그대로 통과한다(2026-08-30 첫 발행에서 발견).
        for m in _NUM.findall(mask_dates(obj)):
            _add(out, m)
    return out


_UNIT = re.compile(r'(-?\d[\d,]*\.?\d*)\s*(%p|%|bp|배|달러|엔|원|포인트)')


def _united_numbers(html):
    """단위를 달고 나온 수치 — 작은 정수라도 면제하지 않는다."""
    text = mask_dates(body_text(html))
    return {_canon(m.group(1).replace(',', '')) for m in _UNIT.finditer(text)}


def _round_variants(x):
    """원값과 1·2자리 반올림. **값을 0으로 지우는 반올림은 넣지 않는다.**

    산문은 반올림해 쓴다 — 0.8478%를 「0.85%」로 적는 것은 창작이 아니다. 그러나
    +0.4872%를 「0% 올랐다」로 적는 것은 반올림이 아니라 다른 말이다. 정수 반올림을
    무조건 허용한 탓에 이 문장이 그대로 통과했다(2026-08-30 주간본 회수 사유).
    """
    out = {_canon(x)}
    for nd in (0, 1, 2):
        r = round(x, nd)
        if r == 0 and x != 0:
            continue
        out.add(_canon(r))
    return out


def _add(out, value):
    """부호 있는 꼴과 절댓값을 함께 허용한다.

    「10년물이 12.0bp 내렸다」는 정상 서술이다 — 방향을 말로 쓰고 크기만 적는다.
    부호가 맞는지는 이 게이트가 아니라 verify_post 가 본다. 여기서 부호까지 요구하면
    사람이 쓰는 방식의 문장을 매번 막는다(2026-08-30 codex 검토 반영 중 발견).
    """
    out.add(_canon(value))
    try:
        f = float(value)
    except (TypeError, ValueError):
        return
    # 산문은 반올림해 쓴다(일간 문체 규칙과 같다). 0.8478%를 「0.85%」로 적는 것은
    # 창작이 아니다 — 원값과 1·2자리 반올림을 함께 허용한다(2026-08-30 첫 발행에서 발견).
    for x in (f, abs(f)):
        out |= _round_variants(x)


def _html_numbers(html):
    """본문의 수치. **부호를 살려서** 센다.

    data_tokens 는 토큰을 자르면서 앞의 마이너스를 버린다. 그대로 쓰면 「-21%」가 21 로
    읽혀, 원본 어딘가에 21 이 있기만 하면 통과한다 — 부호가 뒤집힌 창작이 그대로
    지나가는 자리였다(2026-08-30 첫 발행에서 발견).
    """
    text = mask_dates(body_text(html)).replace(',', '').replace('−', '-')
    return {_canon(m) for m in _NUM.findall(text)}


# 「S&P 500은 57.3% 올랐다」가 통과하던 자리. 어느 날 PMI가 57.3 이었으면 그 값이
# 허용 집합에 들어 있기 때문이다. 이름 옆에 붙은 수치는 **그 항목의 값이어야 한다**
# (2026-08-30 codex 검토).
_NEAR = 40      # 이름 뒤 이 글자 안의 수치를 그 항목의 것으로 본다


def _date_mentioned(text, iso):
    """「2026-08-25」·「2026년 8월 25일」·「8월 25일」 셋 다 그날을 부른 것으로 본다."""
    if iso in text:
        return True
    try:
        y, m, d = iso.split('-')
    except ValueError:
        return False
    m, d = int(m), int(d)
    return bool(re.search(rf'({y}년\s*)?{m}월\s*{d}일', text))


def _check_provenance(text, agg):
    """이름 **바로 뒤 첫 수치**가 그 항목의 값인가.

    창을 넓게 잡으면 뒷 항목의 값까지 그 이름의 것으로 읽는다 — 절 경계(쉼표·마침표)에서
    끊고 첫 수치 하나만 본다.
    """
    v = []
    for group in ('indices', 'sectors', 'fx', 'commodities'):
        for name, row in ((agg or {}).get(group) or {}).items():
            if not isinstance(row, dict) or row.get('pct') is None:
                continue
            # 단위별로 갈라 둔다. 하나로 합치면 종가 7711.76 이 허용 집합에 있다는
            # 이유로 「S&P 500은 7711.76% 올랐다」가 통과한다(2026-08-30 회수 사유).
            own = {'%': set(), 'level': set()}
            own['%'] |= _round_variants(abs(row['pct']))
            for k in ('start', 'end'):
                val = row.get(k)
                if isinstance(val, (int, float)):
                    own['level'] |= _round_variants(abs(val))
            for m in re.finditer(re.escape(name), text):
                # 마침표는 소수점이기도 하다 — 뒤에 공백·끝이 올 때만 절 경계로 본다.
                window = re.split(r'[,·。]|\.(?=\s|$)',
                                  text[m.end():m.end() + _NEAR])[0]
                hit = _UNIT.search(window)
                if not hit:
                    continue
                raw = abs(float(hit.group(1).replace(',', '')))
                unit = '%' if hit.group(2) in ('%', '%p') else 'level'
                # 괄호가 없으면 & 가 먼저 묶여 검사가 통째로 무력해진다.
                mine = _round_variants(raw)
                if mine & own[unit]:
                    continue
                expect = row['pct'] if unit == '%' else row.get('end')
                v.append(f'「{name}」 바로 뒤 수치가 그 항목의 값이 아니다: '
                         f'{hit.group(0).strip()} — 집계의 값은 '
                         + (f'{expect}%다' if unit == '%' else f'{expect}다'))
                break
    return v


def check(html, agg, scorecard, recap, span):
    v = []
    text = body_text(html)

    # 스키마·완성도 — 반쪽 집계로 낸 총정리는 다음 기간에 정정할 방법이 없다.
    if (agg or {}).get('span') != span:
        v.append(f'집계 파일의 span이 「{(agg or {}).get("span")}」인데 {span}로 발행하려 한다')
    if not (agg or {}).get('complete'):
        miss = ', '.join((agg or {}).get('missing') or []) or '사유 미기록'
        v.append(f'집계가 complete=false다 — 완성본만 발행한다 (결측: {miss})')
    if (recap or {}).get('key') and (agg or {}).get('key') \
            and recap['key'] != agg['key']:
        v.append(f'회수한 발행본의 기간 키({recap["key"]})가 집계({agg["key"]})와 다르다')

    # 집계가 그 기간의 마지막 거래일을 빠뜨렸는가. 회수한 발행본이 집계 종료일보다
    # 뒤에 있으면 그날이 통째로 사라진 것이다 — complete 는 계열이 다 있는지만 본다.
    dates = [p.get('date') for p in ((recap or {}).get('posts') or []) if p.get('date')]
    if dates and (agg or {}).get('end_date') and max(dates) > agg['end_date']:
        v.append(f'집계가 {agg["end_date"]}에서 끝나는데 {max(dates)} 발행본이 있다 — '
                 '그 거래일이 총정리에서 통째로 빠진다')

    # 거래일 수는 본문에 있어야 한다 — 「몇 거래일을 정리한 글인가」가 총정리의 기본값이다.
    sessions = (agg or {}).get('sessions')
    # 「5」가 본문 어딘가에 있다는 것으로는 부족하다 — 수치는 어디에나 있다.
    if sessions and not re.search(rf'(?<!\d){sessions}\s*(거래일|영업일|일간|일\b)', text):
        v.append(f'커버한 거래일 수({sessions}거래일)가 본문에 없다')

    for marker in banned_markers(html):
        v.append(f'발행본에 미확인 마커가 남았다: {marker} — 확인해 확정하거나 삭제할 것')

    low = text.lower()
    for word in BANNED_LABELS:
        if word in low:
            v.append(f'발행본에 buy-side 표기("{word}")가 남았다 — 전략·리포트·시황 정리로 부를 것')
            break

    for term in INTERNAL_TERMS:
        if term in text:
            v.append(f'내부 용어·파일명이 발행본에 노출됐다: {term}')

    start, end = agg.get('start_date'), agg.get('end_date')
    if not (start and start in text) or not (end and end in text):
        v.append(f'커버 기간이 본문에 없다 — 시작({start})과 종료({end}) 거래일을 명시할 것')

    # 총정리 커버리지 — 원본의 모든 거래일이 본문에 있어야 한다
    for post in ((recap or {}).get('posts') or []):
        d = post.get('date')
        if d and not _date_mentioned(text, d):
            v.append(f'{d} 발행본이 총정리에서 빠졌다 — 그날 사건이 사라진다. '
                     f'헤드라인: {post.get("headline", "")[:40]}')

    for d in ((recap or {}).get('missing') or []):
        v.append(f'{d} 발행본이 없다 — 목록에는 있는데 파일을 못 찾았다. '
                 '총정리 전에 원본을 확인할 것')

    allowed = _numbers(agg) | _numbers(scorecard or {})
    for post in ((recap or {}).get('posts') or []):
        allowed |= _numbers(post.get('figures') or [])
    allowed |= {str(y) for y in range(2020, 2036)}

    united = _united_numbers(html)
    for n in sorted(_html_numbers(html) - allowed):
        try:
            f = abs(float(n))
        except ValueError:
            continue
        # 작은 정수는 섹션 번호·순위·거래일 수일 수 있어 통과시키되, **단위를 달고
        # 나온 값은 예외 없이 검사한다** — 「7% 올랐다」가 그냥 지나가던 구멍이다
        # (2026-08-30 codex 검토).
        if f <= 12 and f == int(f) and n not in united:
            continue
        v.append(f'어느 원본에도 없는 수치가 본문에 있다: {n} — 창작 금지. '
                 '집계 파일이나 그 기간 발행본에 실린 값만 인용할 것')

    v += _check_provenance(text, agg)

    ru = (scorecard or {}).get('rollup') or {}
    if any((ru.get(k) or {}).get('insufficient') for k in ru):
        if '표본 부족' not in text:
            v.append('누적 구간의 표본이 부족한데 본문이 그 사실을 밝히지 않았다 — '
                     '「누적 표본 부족」을 명시하고 당기만 실을 것')
    return v
