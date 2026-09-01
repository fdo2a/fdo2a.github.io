"""「왜 이 비중인가」를 매일 다시 재서 발행본에 내려보낸다.

`portfolio.py` 의 상수는 한 번 계산해 고정한 값이다 — 매일 다시 계산하면 등급이
그대로인 날에도 목표가 움직여 「등급이 바뀐 날에만 리밸런싱」이 무너진다. 그러면
그 상수가 아직 맞는지는 누가 보나. 이 모듈이 그 자리다.

세 가지를 잰다.

  변동성      각 슬리브의 연변동성. 한 칸의 크기가 여기서 나온다.
  위험 몫     중립 책의 위험을 어느 슬리브가 지고 있나. 「주식이 3분의 2」가
              의도한 대로인지 매일 확인된다.
  한 칸의 크기 상수 × 오늘 변동성. 예산에서 크게 벗어나면 재보정 신호를 띄운다.

**교보재 수치를 산문에 손으로 적지 않는다** — 채권 파이프라인이 세운 규칙 그대로다.
「금 한 칸은 0.74%p」는 여기서 계산해 내려보낸다.
"""

import math

from .portfolio import (AI_STEP, ENERGY_STEP, EQUITY_STEP, FI_LONG_STEP, FI_TOTAL,
                        FX_RISK_SHARE, FX_STEP, MEMORY_STEP, METALS_STEP,
                        NEUTRAL_GRADES, NOTCH_RISK_PCT, SLEEVE_LABEL, SLEEVE_ORDER,
                        SLEEVE_TICKERS, sleeve_weights)

TRADING_DAYS = 252
MIN_OBS = 120            # 반년치도 없으면 변동성을 말하지 않는다
DRIFT_TOLERANCE = 0.35   # 예산 대비 이만큼 벗어나면 재보정 신호

# 등급 한 칸이 자본을 얼마나 옮기는가. 채권만 다르다 — 합계가 고정된 채 장·단기
# 사이를 옮기므로, 움직이는 것은 「장기 비중」이고 위험은 «장−단 차»의 변동성이다.
NOTCH_STEP = {'equity_core': EQUITY_STEP, 'memory': MEMORY_STEP,
              'ai_infra': AI_STEP, 'metals': METALS_STEP, 'energy': ENERGY_STEP,
              'fx_short': FX_STEP, 'fx_long': FX_STEP}
BOND_NOTCH_SHIFT = FI_TOTAL * FI_LONG_STEP


def _returns(closes, dates, tickers):
    """공통 세션에서만 수익률을 만든다. 날짜를 맞추지 않으면 상관이 거짓이 된다."""
    have = [t for t in tickers if (closes or {}).get(t) and (dates or {}).get(t)]
    if len(have) != len(tickers):
        return None
    common = sorted(set.intersection(*(set(dates[t]) for t in have)))
    if len(common) < MIN_OBS:
        return None
    series = {}
    for t in have:
        by = dict(zip(dates[t], closes[t]))
        px = [by[d] for d in common]
        series[t] = [px[i] / px[i - 1] - 1 for i in range(1, len(px))
                     if px[i - 1]]
    n = min(len(v) for v in series.values())
    return [[series[t][-n:][i] for t in have] for i in range(n)]


def _basket(rows):
    return [sum(r) / len(r) for r in rows]


def _vol(series):
    if len(series) < MIN_OBS:
        return None
    mean = sum(series) / len(series)
    var = sum((x - mean) ** 2 for x in series) / len(series)
    return math.sqrt(var * TRADING_DAYS) * 100


def sleeve_returns(closes, dates):
    """슬리브별 일간 수익률(동일가중 바스켓). 값이 없는 슬리브는 담지 않는다."""
    out = {}
    for key in SLEEVE_ORDER:
        rows = _returns(closes, dates, SLEEVE_TICKERS[key])
        if rows:
            out[key] = _basket(rows)
    return out


def compute(closes, dates):
    """-> 발행본이 그대로 렌더할 «구성의 근거». 재료가 없으면 None."""
    rets = sleeve_returns(closes, dates)
    if not rets:
        return None
    vols = {k: _vol(v) for k, v in rets.items()}
    vols = {k: v for k, v in vols.items() if v}
    if 'equity_core' not in vols:
        return None

    neutral = sleeve_weights(NEUTRAL_GRADES)
    # 위험 몫은 상관을 무시한 단순 기여(비중 × 변동성)로 낸다. 「누가 위험을 지고
    # 있나」를 보여 주는 데는 이것으로 충분하고, 한계는 캡션에 밝힌다.
    contrib = {k: neutral[k] / 100 * vols[k] for k in vols}
    total = sum(contrib.values()) or 1.0
    shares = {k: contrib[k] / total * 100 for k in contrib}

    # 채권 한 칸은 «장−단 차»의 변동성으로 잰다. 합계가 고정돼 있어 배분이 아니라
    # 듀레이션만 움직이기 때문이다.
    bond_vol = None
    if 'bonds_long' in rets and 'bonds_short' in rets:
        n = min(len(rets['bonds_long']), len(rets['bonds_short']))
        bond_vol = _vol([rets['bonds_long'][-n:][i] - rets['bonds_short'][-n:][i]
                         for i in range(n)])

    notches, drifted = [], []
    for key in SLEEVE_ORDER:
        if key == 'bonds_long' and bond_vol:
            step, vol_ = BOND_NOTCH_SHIFT, bond_vol
        elif key in NOTCH_STEP and key in vols:
            step, vol_ = NOTCH_STEP[key], vols[key]
        else:
            continue
        risk = step / 100 * vol_
        budget = NOTCH_RISK_PCT * (FX_RISK_SHARE if key.startswith('fx') else 1.0)
        off = abs(risk - budget) / budget if budget else 0
        if off > DRIFT_TOLERANCE:
            drifted.append(key)
        notches.append({'sleeve': key, 'label': SLEEVE_LABEL[key],
                        'step_pct': round(step, 2), 'vol_pct': round(vol_, 1),
                        'risk_pct': round(risk, 2), 'budget_pct': round(budget, 2)})

    equity_family = sum(shares.get(k, 0) for k in
                        ('equity_core', 'memory', 'ai_infra'))
    # 슬리브마다 공통 세션이 달라진다. **가장 짧은 것**을 밝힌다 — 첫 슬리브 길이를
    # 쓰면 「199거래일을 쟀다」면서 에너지는 129거래일로 잰 값을 인쇄하게 된다
    # (2026-09-02 codex 검토).
    return {
        'sessions': min(len(v) for v in rets.values()),
        'budget_pct': NOTCH_RISK_PCT, 'fx_share': round(FX_RISK_SHARE, 3),
        'vol': {k: round(v, 1) for k, v in vols.items()},
        'neutral_risk_share': {k: round(v, 1) for k, v in shares.items()},
        'equity_risk_share_pct': round(equity_family, 1),
        'notches': notches,
        'recalibrate': sorted(drifted),
    }
