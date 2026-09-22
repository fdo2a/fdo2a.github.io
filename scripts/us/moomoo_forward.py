#!/usr/bin/env python3
"""moomoo 보조 입력의 **정규화와 승인 계약**.

이 모듈은 네트워크를 모른다. OpenD 연결·인증·타임아웃·호출제한은 진입점
(`scripts/collect_moomoo_forward.py`)의 일이고, 여기서는 받은 응답을 검사하고
정규화한다. SDK 가 없는 환경에서도 import 된다 — 게이트가 이 모듈을 쓴다.

막는 것은 하나다: **검증되지 않은 값이 발행 입력으로 승인되는 것.**

세 가지가 설계의 뼈대다.

① **수집시각과 원자료 기준시각은 다른 축이다.** 오늘 다시 저장했어도 원자료가
   어제 것이면 새 자료가 아니다. 맥이 꺼진 날 어제 파일이 그대로 남아 있기
   때문에, 파일 존재 여부로는 아무것도 판정할 수 없다.
② **확률은 사건에 묶여야 비교된다.** 회의일·목표구간·관측시각·공급자가 함께
   붙어 있지 않으면, 공급자가 바뀐 차이를 시장의 확률 변화로 오해한다.
   `macro_gate` 의 15%p 규칙이 그 오해를 정책 시점 변경의 근거로 삼는다.
③ **moomoo 는 연준이 아니다.** `calendar.py` 는 넘겨받은 회의일을 출처
   「연준 공표 일정」·상태 `confirmed` 로 **고정해 인쇄한다**. 검증하지 않은
   출처를 그 자리에 넣으면 더 강한 출처로 둔갑한다. 공식 일정이 정본이고
   moomoo 는 대조용이다.

When changing this: read `docs/superpowers/specs/2026-09-22-moomoo-forward-design.md`
before touching `scripts/us/moomoo_forward.py` or `scripts/collect_moomoo_forward.py`.
"""

import datetime as dt
import math

# --- 상태 어휘 ----------------------------------------------------------------
# 「없다」에는 종류가 있다. 부분 실패·정상 0건·권한 없음·노후화를 한 단어로
# 뭉치면, 유효한 격주 자료를 버리거나 낡은 자료에 오늘 날짜만 붙여 승인한다.
STATUSES = ('ok', 'empty', 'partial', 'unavailable', 'stale', 'invalid')

# 확률 분포 합계 허용 오차(%p). 공급자가 반올림해서 주기 때문에 정확히 100 이
# 아닐 수 있다. **넘으면 버린다 — 통과시키려고 정규화하지 않는다.**
SUM_TOLERANCE_PCT = 1.0

# 공식 FOMC 일정 확인의 유효기간(일). 미래 날짜가 하나 남았다는 사실은 최신
# 확인의 대용물이 아니다.
OFFICIAL_MAX_AGE_DAYS = 45


class InvalidProbability(ValueError):
    """확률 분포가 승인 조건을 못 넘겼다."""


def envelope(kind, *, rows, status, fetched_at, source_as_of=None, session=None,
             query_range=None, source=None, provider=None, note=None, missing=()):
    """보조 입력 한 덩어리를 승인 가능한 형태로 감싼다.

    `fetched_at` 은 **우리가 받은 시각**, `source_as_of` 는 **원자료의 기준
    시각**이다. 원천 시각을 모르면 `None` 으로 남긴다 — 수집시각으로 대체하면
    격주 갱신 자료가 매일 새 자료로 보인다.
    """
    if status not in STATUSES:
        raise ValueError(f'unknown status: {status!r} (allowed: {STATUSES})')
    rows = list(rows)
    if status == 'empty':
        # 정상 0건은 **조회가 성공하고 범위가 확인될 때만** 인정한다. 범위를
        # 모르면 그것은 0건이 아니라 모르는 것이다.
        if not query_range:
            raise ValueError('status=empty requires query_range')
        if rows:
            raise ValueError('status=empty with rows')
    if status == 'ok' and not rows:
        raise ValueError('status=ok with no rows — use empty or unavailable')
    return {
        'kind': kind,
        'status': status,
        'fetched_at': fetched_at,
        'source_as_of': source_as_of,
        'session': session,
        'query_range': query_range,
        'source': source,
        'provider': provider,
        'note': note,
        'missing': sorted(set(missing)),
        'rows': rows,
    }


def _finite_pct(value):
    try:
        p = float(value)
    except (TypeError, ValueError):
        raise InvalidProbability(f'not a number: {value!r}')
    if math.isnan(p) or math.isinf(p):
        raise InvalidProbability(f'not finite: {value!r}')
    if p < 0.0 or p > 100.0:
        raise InvalidProbability(f'outside [0, 100]: {p}')
    return p


def parse_target_range(text):
    """'3.75-4.00%' → (3.75, 4.00). 상·하단을 잃으면 구간을 식별할 수 없다."""
    raw = str(text or '').replace('%', '').replace('–', '-').strip()
    lo, _, hi = raw.partition('-')
    if not hi:
        raise InvalidProbability(f'unparsable target range: {text!r}')
    return float(lo), float(hi)


def normalize_fedwatch(rows, *, observed_at, provider):
    """회의별 확률 분포로 묶는다. 사건 식별자를 잃지 않는다."""
    by_meeting = {}
    for row in rows:
        day = str(row.get('meeting_date') or '').strip()
        if not day:
            raise InvalidProbability('row without meeting_date')
        lo, hi = parse_target_range(row.get('target_range'))
        p = _finite_pct(row.get('probability'))
        bucket = by_meeting.setdefault(day, {})
        if lo in bucket:
            # 같은 구간이 두 번 오면 어느 쪽이 참인지 알 수 없다.
            raise InvalidProbability(f'duplicate range {lo} for {day}')
        bucket[lo] = {'lower_pct': lo, 'upper_pct': hi, 'probability_pct': p}

    out = []
    for day in sorted(by_meeting):
        ranges = [by_meeting[day][k] for k in sorted(by_meeting[day])]
        total = sum(r['probability_pct'] for r in ranges)
        if abs(total - 100.0) > SUM_TOLERANCE_PCT:
            raise InvalidProbability(
                f'{day}: distribution sums to {total:.2f}, not 100 '
                f'(tolerance {SUM_TOLERANCE_PCT})')
        out.append({'meeting_date': day, 'observed_at': observed_at,
                    'provider': provider, 'ranges': ranges})
    return out


def probability_delta(before, after, *, meeting_date, lower_pct, upper_pct=None):
    """같은 사건·같은 공급자일 때만 변화량을 준다. 아니면 `None`.

    비교 불가능한 것을 0 이나 임의의 수로 채우면, `macro_gate` 의 15%p 규칙이
    공급자 교체나 회의 이동을 「시장이 움직였다」로 읽는다.
    """
    def _find(book):
        for m in book:
            if m['meeting_date'] != meeting_date:
                continue
            for r in m['ranges']:
                if abs(r['lower_pct'] - lower_pct) >= 1e-9:
                    continue
                if upper_pct is not None and abs(r['upper_pct'] - upper_pct) >= 1e-9:
                    continue
                return m, r
        return None, None

    mb, rb = _find(before)
    ma, ra = _find(after)
    if rb is None or ra is None:
        return None
    if mb['provider'] != ma['provider']:
        return None
    return round(ra['probability_pct'] - rb['probability_pct'], 4)


def fomc_book(official=None, moomoo_dates=(), *, checked_at, report_date=None,
              max_age_days=OFFICIAL_MAX_AGE_DAYS):
    """공식 일정을 정본으로 한 FOMC 장부. moomoo 는 `cross_check` 에만 남는다.

    `official` 은 `{'meetings': [...], 'source': ..., 'verified_at': 'YYYY-MM-DD'}`.
    없거나 확인이 낡았으면 **회의일을 비우고 사유를 `missing` 에 적는다** —
    이 파이프라인에서 삭제는 언제나 창작보다 낫다.
    """
    moomoo = sorted({str(d) for d in moomoo_dates})
    missing = []
    meetings = []
    source = None
    verified_at = None

    if not official or not official.get('meetings'):
        missing.append('official')
    else:
        source = official.get('source')
        verified_at = official.get('verified_at')
        age = _age_days(verified_at, checked_at)
        if age is None or age > max_age_days:
            missing.append('official_stale')
        else:
            # **직전 회의를 버리지 않는다.** 블랙아웃은 회의 다음 목요일까지라
            # 막 끝난 회의가 빠지면 그 주 판정 근거가 사라진다.
            meetings = sorted({str(d) for d in official['meetings']})

    agrees = None
    if meetings and moomoo:
        agrees = set(moomoo) <= set(meetings)

    return {
        'meetings': meetings,
        'sep_meetings': [d for d in (official or {}).get('sep_meetings', ())
                         if d in set(meetings)],
        'notation_votes': list((official or {}).get('notation_votes', ())),
        'source': source,
        'verified_at': verified_at,
        'checked_at': checked_at,
        'report_date': report_date.isoformat() if report_date else None,
        'cross_check': {'moomoo': moomoo, 'agrees': agrees},
        'missing': sorted(set(missing)),
    }


def _age_days(earlier, later):
    try:
        a = dt.date.fromisoformat(str(earlier))
        b = dt.date.fromisoformat(str(later))
    except (TypeError, ValueError):
        return None
    return (b - a).days


# --- 경제지표 컨센서스 --------------------------------------------------------
# **이름으로 잇지 않는다.** CPI 의 YoY 와 MoM, headline 과 core, GDP 속보와
# 수정치는 제목만으로 구별되지 않는다. 허용목록에 없으면 버린다 — 잘못 붙인
# Forecast 는 빈 칸보다 나쁘다.
CONSENSUS_MAP = {
    'cpi (yoy)': ('cpi_yoy', 'pct'),
    'cpi (mom)': ('cpi_mom', 'pct'),
    'core cpi (yoy)': ('core_cpi_yoy', 'pct'),
    'core cpi (mom)': ('core_cpi_mom', 'pct'),
    'ppi (yoy)': ('ppi_yoy', 'pct'),
    'ppi (mom)': ('ppi_mom', 'pct'),
    'core ppi (mom)': ('core_ppi_mom', 'pct'),
    'nonfarm payrolls': ('nonfarm_payrolls', 'count'),
    'unemployment rate': ('unemployment_rate', 'pct'),
    'average hourly earnings (mom)': ('avg_hourly_earnings_mom', 'pct'),
    'initial jobless claims': ('initial_claims', 'count'),
    'continuing jobless claims': ('continuing_claims', 'count'),
    'jolts job openings': ('jolts_openings', 'count'),
    'retail sales (mom)': ('retail_sales_mom', 'pct'),
    'core retail sales (mom)': ('core_retail_sales_mom', 'pct'),
    'core pce price index (yoy)': ('core_pce_yoy', 'pct'),
    'core pce price index (mom)': ('core_pce_mom', 'pct'),
    'personal spending (mom)': ('personal_spending_mom', 'pct'),
    'gdp (qoq)': ('gdp_qoq', 'pct'),
    'industrial production (mom)': ('industrial_production_mom', 'pct'),
    'durable goods orders (mom)': ('durable_goods_mom', 'pct'),
    'new home sales': ('new_home_sales', 'count'),
    'existing home sales': ('existing_home_sales', 'count'),
    'manufacturing pmi': ('manufacturing_pmi', 'index'),
    'services pmi': ('services_pmi', 'index'),
    'ism manufacturing pmi': ('ism_manufacturing_pmi', 'index'),
    'ism services pmi': ('ism_services_pmi', 'index'),
    'michigan consumer sentiment': ('michigan_sentiment', 'index'),
}

US_COUNTRY = 'united states'


def _num(text):
    """'3.1%' → 3.1, '16.30K' → 16300.0. 모르면 None."""
    raw = str(text or '').strip().replace('%', '').replace(',', '')
    if not raw or raw in ('--', 'N/A'):
        return None
    mult = 1.0
    if raw[-1:] in ('K', 'M', 'B', 'T'):
        mult = {'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}[raw[-1]]
        raw = raw[:-1]
    try:
        return float(raw) * mult
    except ValueError:
        return None


def normalize_consensus(rows, *, observed_at, provider='moomoo'):
    """미국 지표의 **Forecast 칸만** 만든다.

    Actual/Previous 는 FRED 가 정본이라 여기서 내보내지 않는다. FRED 최신치는
    개정된 값일 수 있고 공급자의 previous 는 발표 당시 값일 수 있어, 둘을 섞으면
    개정분이 「발표 서프라이즈」로 읽힌다.
    """
    out = []
    for row in rows:
        if str(row.get('country') or '').strip().lower() != US_COUNTRY:
            continue
        key = str(row.get('title') or '').strip().lower()
        mapped = CONSENSUS_MAP.get(key)
        if not mapped:
            continue
        consensus = _num(row.get('consensus'))
        if consensus is None:
            continue
        metric_key, unit = mapped
        out.append({
            'metric_key': metric_key,
            'title': row.get('title'),
            'unit': unit,
            'consensus': consensus,
            'star': row.get('star'),
            'timestamp': row.get('timestamp'),
            'observed_at': observed_at,
            'provider': provider,
            'vendor': None,   # 원집계 벤더가 문서에 없다. 임의로 채우지 않는다.
        })
    return out


# --- 세션 계약 ----------------------------------------------------------------

def target_session(kst_date, *, holidays=()):
    """KST 실행일 → 이 실행이 다루는 **미국 거래일**. 없으면 `None`.

    발행은 KST 화~토다(`scripts/us/CLAUDE.md`). 「평일」로 잡으면 미국 금요일장을
    다루는 토요일 발행을 놓치고, 월요일 실행은 미국 일요일이라 대상이 없다.

    휴장은 `holidays` 로 받는다 — 여기서 달력을 만들지 않는다.
    """
    if kst_date.weekday() not in (1, 2, 3, 4, 5):   # 화~토
        return None
    day = kst_date - dt.timedelta(days=1)
    seen = {dt.date.fromisoformat(str(h)) if not isinstance(h, dt.date) else h
            for h in holidays}
    while day.weekday() >= 5 or day in seen:
        day -= dt.timedelta(days=1)
    return day


def session_matches(env, *, report_date):
    """보조 입력의 대상 세션이 정본 `report_date` 와 같은가.

    수집 당시 정본이 아직 없으면 잠정으로 남기고 **발행 때 매칭한다**. 늦게
    깨어난 맥이 과거 보고서용으로 최신 데이터를 소급 포장하면 안 된다.
    """
    session = env.get('session')
    if not session:
        return None
    return str(session) == str(report_date)


# 관측이 유효한 창(시간). 세션 라벨만 맞으면 며칠 전 응답도 승인되던 구멍을
# 막는다(codex 구현 검토 P1-4). 발행은 세션 다음 날 아침이므로 36시간이면
# 정상 실행을 다 덮고, 그보다 오래된 것은 오늘 입력이 아니다.
OBSERVATION_MAX_AGE_HOURS = 36


def approved_fedwatch(env, *, report_date, now=None,
                      max_age_hours=OBSERVATION_MAX_AGE_HOURS):
    """승인된 FedWatch 확률 장부. 승인 못 하면 `None`.

    파일이 있다는 사실만으로는 오늘 입력이 되지 않는다. 상태가 `ok` 이고,
    **대상 세션이 정본 `report_date` 와 같고**, 관측이 허용 창 안일 때만
    승인한다.
    """
    if not env or env.get('kind') != 'fedwatch':
        return None
    if env.get('status') != 'ok' or not env.get('rows'):
        return None
    if session_matches(env, report_date=report_date) is not True:
        return None
    if observation_age_hours(env, now=now) is None:
        return None
    if observation_age_hours(env, now=now) > max_age_hours:
        return None
    return env['rows']


def observation_age_hours(env, *, now=None):
    """관측이 몇 시간 전 것인가. 읽을 수 없으면 `None`(=승인 불가)."""
    stamp = env.get('fetched_at')
    try:
        seen = dt.datetime.fromisoformat(str(stamp))
    except (TypeError, ValueError):
        return None
    if seen.tzinfo is None:
        return None
    now = now or dt.datetime.now(tz=seen.tzinfo)
    return (now - seen).total_seconds() / 3600.0


def find_probability(book, *, meeting_date, lower_pct, upper_pct=None):
    """승인 장부에서 그 사건의 확률을 찾는다. 없으면 `None`.

    **하단만으로는 사건이 식별되지 않는다.** 같은 하단의 3.75–4.00 과
    3.75–4.25 는 다른 사건이다. 상단을 주면 함께 맞춘다.
    """
    for meeting in book or ():
        if meeting.get('meeting_date') != str(meeting_date):
            continue
        for rng in meeting.get('ranges') or ():
            if abs(rng['lower_pct'] - float(lower_pct)) >= 1e-9:
                continue
            if upper_pct is not None and abs(rng['upper_pct'] - float(upper_pct)) >= 1e-9:
                continue
            return rng['probability_pct']
    return None


def same_event(a, b):
    """두 정책 경로가 **같은 사건**을 가리키는가.

    회의나 구간이 바뀌었는데 확률 차이를 「시장이 움직였다」로 읽으면, 9월
    회의 40% 에서 10월 회의 100% 로 갈아타는 것만으로 정책 시점 변경이
    승인된다(2026-09-22 codex 구현 검토 P1-2).
    """
    if not a or not b:
        return False
    keys = ('prob_meeting', 'prob_range_lower', 'prob_range_upper')
    for k in keys:
        if a.get(k) != b.get(k):
            return False
    return a.get('prob_meeting') is not None
