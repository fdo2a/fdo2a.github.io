"""Publication gate for the price-context readings.

Two of the readings are only worth computing if the report cannot quietly ignore
them, so they are enforced here rather than asked for in the prompt:

  * A cross-asset relationship that changed sign is the kind of thing the brief has
    historically walked straight past. Same discipline as §8's reconciliation rule —
    disagreement is allowed, silence is not.
  * An attribution that prints the winners without the part it cannot explain reads
    as a complete decomposition. It is an estimate, and it has a residual.
  * A change in which asset group the market is moving on is the same class of event
    as a correlation flipping — it is the regime turning over in plain sight.
  * A track-record claim made off eight decisions is not a track record. The
    scorecard says when it has enough; the page may not get ahead of it.
"""

import re
from common.numbers import TAG_RE

# Machinery the reader has no use for. The 08-17 brief printed "signed-z 0.895" and a
# filename; the same failure mode applies to anything named here.
INTERNAL_JARGON = ('주성분', '고유값', 'NNLS', 'nnls', 'lstsq', '최소자승',
                   'price_context', 'sector_contribution', 'move_multiple',
                   'level_percentile', 'fit_r2', 'residual', 'cohesion',
                   'percentile', 'multiple')

MIN_FIT_R2 = 0.90


def _markers(html, attr):
    return set(re.findall(rf'{attr}="([^"]+)"', html or ''))


def _text(html):
    # 주석·속성값 안의 `>` 까지 한 토큰으로 — 정본은 common/numbers.py
    # (2026-09-01 codex 검토: 필수 해소 문구를 주석에 숨기면 통과했다).
    return TAG_RE.sub(' ', html or '')


def _blocks(html, attr):
    """Text of every element carrying the attribute, keyed by its value."""
    out = {}
    for m in re.finditer(rf'<(\w+)[^>]*\b{attr}="([^"]+)"[^>]*>(.*?)</\1>', html or '', re.S):
        out.setdefault(m.group(2), []).append(_text(m.group(3)))
    return out


def check(html, price_context, scorecard=None):
    """Return a list of violations, one string each. Empty list = publishable."""
    v = []
    if _markers(html, 'data-scorecard'):
        # 파일을 못 읽었다는 것은 「표본이 충분하다」는 뜻이 아니다. 모르면 막는다.
        if not (scorecard or {}).get('sufficient'):
            v.append(
                f"성적표 표본 부족: 채점된 판단이 {(scorecard or {}).get('scored')}건으로"
                f" {(scorecard or {}).get('min_sample')}건에 못 미친다(성적표를 못 읽었으면 None)."
                ' 적중률·성적 관련 서술을 빼고 발행할 것.'
            )
    if not price_context:
        return v

    marked = _markers(html, 'data-relation')
    for row in price_context.get('correlations') or []:
        if row.get('flipped') and row['key'] not in marked:
            v.append(
                f"관계 전환 침묵: '{row['label_ko']}'의 부호가 직전 60세션 대비 뒤집혔는데"
                f" (최근 {row.get('value')}, 직전 {row.get('prior')}) 본문에 없다."
                f" 해당 문단에 data-relation=\"{row['key']}\"를 달고 서술할 것."
            )

    drivers = price_context.get('drivers') or {}
    # 표식만 달고 내용이 없으면 서술한 것이 아니다.
    told = [t for t in _blocks(html, 'data-driver').get('1', [])
            + [x for k, v in _blocks(html, 'data-driver').items() if k != '1' for x in v]
            if t.strip()]
    if drivers.get('changed') and not told:
        v.append(
            f"주도 요인 전환 침묵: 시장을 끄는 힘이 '{drivers.get('prior')}'에서"
            f" '{(drivers.get('first') or {}).get('group_ko')}'로 바뀌었는데 본문에 없다."
            ' 해당 문단에 data-driver="1"을 달고 서술할 것.'
        )

    sc = price_context.get('sector_contribution') or {}
    attribution = _blocks(html, 'data-attribution')
    if attribution:
        r2 = sc.get('fit_r2')
        # None means the fit could not be measured at all — that is weaker evidence
        # than a low number, not stronger, so it must not pass where a low one fails.
        if r2 is None or r2 < MIN_FIT_R2:
            shown = '측정 불가' if r2 is None else r2
            v.append(
                f'기여도 분해 불가: 섹터가 지수를 설명하는 정도가 {shown}로 {MIN_FIT_R2} 미만이다.'
                ' 그날은 기여도 서술을 생략할 것.'
            )
        residual = sc.get('residual')
        if residual is not None:
            want = f'{abs(residual):.2f}'
            body = ' '.join(t for texts in attribution.values() for t in texts)
            if want not in body:
                v.append(
                    f'기여도 분해가 완전한 척한다: 설명되지 않는 부분 {residual:+.2f}%p를'
                    f' 같은 블록에 함께 적을 것 ({want} 미검출).'
                )

    body = _text(html)
    for term in INTERNAL_JARGON:
        if term in body:
            v.append(f"내부 용어 노출: '{term}' — 발행본에 쓰지 않는다.")
    return v
