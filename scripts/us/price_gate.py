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
from html.parser import HTMLParser

# Machinery the reader has no use for. The 08-17 brief printed "signed-z 0.895" and a
# filename; the same failure mode applies to anything named here.
INTERNAL_JARGON = ('주성분', '고유값', 'NNLS', 'nnls', 'lstsq', '최소자승',
                   'price_context', 'sector_contribution', 'move_multiple',
                   'level_percentile', 'fit_r2', 'residual', 'cohesion',
                   'percentile', 'multiple')

MIN_FIT_R2 = 0.90

# 교차검증이 이만큼 벌어지면 커브 하나가 낡은 것이므로 그날은 선도금리를 요구하지
# 않는다. 정확히 ±15는 요구 대상 — 코드와 writer 스펙이 같은 부등호를 쓴다.
MAX_FORWARD_GAP_BP = 15

MARKERS = ('data-relation', 'data-attribution', 'data-driver', 'data-forward',
           'data-cohesion', 'data-scorecard')

_INERT_TAGS = {'script', 'style', 'template'}
_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link',
              'meta', 'param', 'source', 'track', 'wbr'}
_HIDING_STYLE = re.compile(r'(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)',
                           re.I)


def _hides(tag, attrs):
    """Whether this element's subtree is invisible to the reader."""
    if tag in _INERT_TAGS:
        return True
    for name, value in attrs:
        if name == 'hidden':
            return True
        if name == 'aria-hidden' and (value or '').strip().lower() == 'true':
            return True
        if name == 'style' and _HIDING_STYLE.search(value or ''):
            return True
    return False


class _Reader(HTMLParser):
    """The text a reader sees, and the text under each marker attribute.

    HTML 을 정규식으로 읽으면 네 가지를 전부 잘못 읽는다 — 중첩
    (`<div hidden><div>…</div>…</div>` 의 뒷부분이 살아남는다), 속성 안의 문자열
    (`title="display:none"` 이 정상 본문을 지우고 `title=">"` 가 시작 태그를 닫는다),
    태그 이름의 접두사(`<script-demo>` 가 `<script>` 로 읽힌다), 엔티티
    (`&nbsp;` 만 든 문단이 「서술했다」로 통과한다). 넷 다 실제로 게이트를 통과하는
    것을 재현했다(codex 검토 2026-09-07). 표준 라이브러리 파서로 한 번에 없앤다.

    게이트가 읽는 문장과 독자가 보는 문장이 갈리는 자리가 곧 게이트가 뚫리는
    자리다 — 이 클래스가 그 둘을 하나로 유지한다.
    """

    def __init__(self, attrs=MARKERS):
        super().__init__(convert_charrefs=True)
        self._wanted = tuple(attrs)
        self.blocks = {a: {} for a in self._wanted}
        self.text = []
        self._open = []     # [(tag, hides, [chunk lists this element feeds])]
        self._hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return
        hiding = _hides(tag, attrs)
        feeds = []
        if not hiding and not self._hidden:
            got = dict(attrs)
            for a in self._wanted:
                if got.get(a):
                    chunks = []
                    self.blocks[a].setdefault(got[a], []).append(chunks)
                    feeds.append(chunks)
        self._open.append((tag, hiding, feeds))
        if hiding:
            self._hidden += 1

    def handle_endtag(self, tag):
        # 짝이 안 맞는 닫는 태그는 «가장 가까운 같은 이름»까지만 닫는다. 없으면
        # 무시한다 — 여기서 스택을 통째로 비우면 뒤에 오는 정상 문단이 사라진다.
        for i in range(len(self._open) - 1, -1, -1):
            if self._open[i][0] == tag:
                self._hidden -= sum(1 for _, h, _f in self._open[i:] if h)
                del self._open[i:]
                return

    def handle_data(self, data):
        if self._hidden:
            return
        self.text.append(data)
        for _tag, _h, feeds in self._open:
            for chunks in feeds:
                chunks.append(data)


def _read(html):
    """(visible text, {attr: {value: [text per element]}})."""
    r = _Reader()
    r.feed(html or '')
    r.close()
    blocks = {a: {v: [''.join(c) for c in lists] for v, lists in got.items()}
              for a, got in r.blocks.items()}
    return ''.join(r.text), blocks


def _told(blocks, attr):
    """Marker values whose element actually carries text. A marker on an empty
    element is not a description — same bar for every rule here."""
    return {k: [t for t in texts if t.strip()]
            for k, texts in blocks[attr].items() if any(t.strip() for t in texts)}


_SIGNS = ('-', '\u2212', '\u2013', '\u2014')


def _states(text, number, signed=True):
    """Is `number` in `text` as a number, not as a piece of a bigger one?

    0.25 must not be satisfied by 10.25, and 5.02 must not be satisfied by 15.02.
    `signed=False` also refuses a leading minus — a rate of 5.02% is not stated by
    writing -5.02%, nor by writing it with the sign a word away. A leading + is
    fine. The residual keeps `signed=True` because it is printed with its sign.
    """
    for m in re.finditer(rf'(?<![\d.]){re.escape(number)}(?![\d.])', text or ''):
        if signed or not text[:m.start()].rstrip().endswith(_SIGNS):
            return True
    return False


_MD_RE = re.compile(r'(?<!\d)(\d{1,2})\s*월\s*(\d{1,2})\s*일')
_YEAR_TAIL_RE = re.compile(r'(\d+)\s*년[^\d]{0,3}$')


def _dates(text, iso):
    """Whether the block names the basis date — ISO or the Korean form.

    The forward is built from FRED legs that lag the tape, so a 09-04 brief carries a
    09-03 rate. Printing the number without the day it belongs to reads as today's.
    A year that is written and wrong fails, however it is attached (「2025년도」·
    「2025년의」·「12026년」 all read as a stated year); an omitted year is allowed,
    since the brief's own date supplies it.
    """
    if not iso:
        return True
    try:
        y, m, d = (int(x) for x in iso.split('-'))
    except (TypeError, ValueError):
        return True
    text = text or ''
    if re.search(rf'(?<!\d){re.escape(iso)}(?!\d)', text):
        return True
    for mo in _MD_RE.finditer(text):
        if int(mo.group(1)) != m or int(mo.group(2)) != d:
            continue
        said = _YEAR_TAIL_RE.search(text[max(0, mo.start() - 16):mo.start()])
        if said is None or int(said.group(1)) == y:
            return True
    return False


def check(html, price_context, scorecard=None):
    """Return a list of violations, one string each. Empty list = publishable."""
    v = []
    seen, blocks = _read(html)
    if blocks['data-scorecard']:
        # 파일을 못 읽었다는 것은 「표본이 충분하다」는 뜻이 아니다. 모르면 막는다.
        if not (scorecard or {}).get('sufficient'):
            v.append(
                f"성적표 표본 부족: 채점된 판단이 {(scorecard or {}).get('scored')}건으로"
                f" {(scorecard or {}).get('min_sample')}건에 못 미친다(성적표를 못 읽었으면 None)."
                ' 적중률·성적 관련 서술을 빼고 발행할 것.'
            )
    if not price_context:
        return v

    marked = set(_told(blocks, 'data-relation'))
    for row in price_context.get('correlations') or []:
        if row.get('flipped') and row['key'] not in marked:
            v.append(
                f"관계 전환 침묵: '{row['label_ko']}'의 부호가 직전 60세션 대비 뒤집혔는데"
                f" (최근 {row.get('value')}, 직전 {row.get('prior')}) 본문에 없다."
                f" 해당 문단에 data-relation=\"{row['key']}\"를 달고 서술할 것."
            )

    drivers = price_context.get('drivers') or {}
    # 1등은 3년 381개 창에서 전부 「주식」이었다 — 그 자리의 교체는 사건이 아니라
    # 일어나지 않는 일이다. 도는 것은 그다음 자리이고, 여기서 지키는 것도 그쪽이다.
    if drivers.get('companion_changed') and not _told(blocks, 'data-driver'):
        v.append(
            f"공통 움직임에 함께 붙은 자산군이 바뀌었는데 본문에 없다:"
            f" 직전 60세션 구간은 '{drivers.get('companion_prior')}',"
            f" 최근 60세션은 '{(drivers.get('companion') or {}).get('group_ko')}'다."
            ' 해당 문단에 data-driver="1"을 달고 서술할 것.'
        )

    # 값과 기준일은 매일 필수, 해석은 그날 할 말이 있을 때만. 매일 해석 문단을
    # 강제하면 천천히 움직이는 값에 대해 채움 문장이 나간다(codex 검토 2026-09-07).
    fwd = price_context.get('forward_5y5y') or {}
    nominal = fwd.get('nominal')
    gap = fwd.get('breakeven_gap_bp')
    stale = gap is not None and abs(gap) > MAX_FORWARD_GAP_BP
    if nominal is not None and not stale:
        want = f'{nominal:.2f}'
        # 값과 기준일은 «같은 블록»에 있어야 한다. 블록을 합쳐서 보면 값에 틀린
        # 날짜를 붙여 놓고 다른 블록의 맞는 날짜로 때울 수 있다.
        texts = [t for ts in _told(blocks, 'data-forward').values() for t in ts]
        carrying = [t for t in texts if _states(t, want, signed=False)]
        if not carrying:
            v.append(
                f'5년 뒤 5년 금리 누락: {want}%가 본문에 없다.'
                ' 해당 문단에 data-forward="1"을 달고 값과 기준일을 적을 것.'
            )
        elif not any(_dates(t, fwd.get('date')) for t in carrying):
            v.append(
                f"5년 뒤 5년 금리의 기준일 누락: 이 값은 {fwd.get('date')} 것이고"
                ' 발행일보다 이를 수 있다. 값과 같은 블록에 기준일을 적을 것.'
            )

    # 응집도는 평범한 날에는 쓸 말이 없다 — 이례적인 날에만 지킨다.
    coh = price_context.get('cohesion') or {}
    if coh.get('band') in ('매우 높음', '매우 낮음'):
        want = f"{coh.get('top1_pct'):.1f}"
        # 숫자만으로는 43%가 높은지 낮은지 알 수 없다 — 통제 어휘가 함께 나와야
        # 독자가 이례성을 읽는다. 산문이 어색하면 같은 블록의 캡션에 적는다.
        texts = [t for ts in _told(blocks, 'data-cohesion').values() for t in ts]
        if not any(_states(t, want, signed=False) and coh['band'] in t for t in texts):
            v.append(
                f"시장이 한 덩어리로 움직이는 정도가 직전 {coh.get('history_windows')}창"
                f" 기준 '{coh['band']}'({want}%)인데 본문에 없다. 해당 문단에"
                ' data-cohesion="1"을 달고 값과 「' + coh['band'] + '」을 함께 적을 것.'
            )

    sc = price_context.get('sector_contribution') or {}
    attribution = _told(blocks, 'data-attribution')
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
            body = ' '.join(t for ts in attribution.values() for t in ts)
            if not _states(body, want):
                v.append(
                    f'기여도 분해가 완전한 척한다: 설명되지 않는 부분 {residual:+.2f}%p를'
                    f' 같은 블록에 함께 적을 것 ({want} 미검출).'
                )

    for term in INTERNAL_JARGON:
        if term in seen:
            v.append(f"내부 용어 노출: '{term}' — 발행본에 쓰지 않는다.")
    return v
