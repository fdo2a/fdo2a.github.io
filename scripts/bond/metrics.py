"""파생 계산 — 「어제 대비 무엇이 바뀌었나」와 뷰 3축의 트리거 재료.

이 모듈이 있는 이유는 계약 때문이다. 발행본 §2 는 이 리포트에서 가장 중요한 칸인데,
내용이 전부 뺄셈이다. 뺄셈을 작성 에이전트에게 맡기면 언젠가 틀린다 — 매크로 축 점수
z 를 writer 가 만지지 못하게 한 것과 같은 이유로, 여기서 계산이 **끝난 상태로** 넘긴다.
writer 는 읽어주기만 한다.

순수 함수다. 네트워크도 시계도 없다.
"""

from . import credit as credit_mod
from . import curve as curve_mod
from . import exposure as exp_mod
from . import etf as etf_mod


def _lvl(node, key):
    v = (node or {}).get(key)
    if isinstance(v, dict):
        return v.get('level')
    return v


def _bp(now, before):
    if now is None or before is None:
        return None
    return round((now - before) * 100, 1)


def _pct(now, before):
    if now is None or before in (None, 0):
        return None
    return round((now / before - 1) * 100, 3)


def _last_before(rows, path, cutoff):
    """cutoff 이전에서 **값이 실제로 있는** 가장 최근 관측 (date, value).

    바로 전날 행에 값이 비는 날이 있다(야후가 특정 종목의 봉을 건너뛴다). 그때
    「변화 없음」이 아니라 「비교 불가」로 처리하면 문장이 깨지고, 0 으로 채우면 거짓말이다.
    값이 있는 데까지 거슬러 올라가 비교하고 **무엇과 맞댄 값인지 날짜를 남긴다.**
    """
    best = None
    for r in rows:
        d = r.get('report_date') or ''
        if d >= cutoff:
            continue
        node = r
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node is not None:
            best = (d, node)
    return best or (None, None)


def _series(rows, path):
    """원장에서 한 계열을 뽑는다. path 는 ('us','10Y') 같은 키 경로."""
    out = []
    for r in rows:
        node = r
        for k in path:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if node is not None:
            out.append(node)
    return out


def _ma(series, n):
    vals = series[-n:]
    return sum(vals) / len(vals) if len(vals) >= n else None


def curve_block(market, prev, prev_dates=None):
    """국가별 커브 — 수준·1일 변화·형태·선도금리."""
    out = {}
    for country, node_key in (('us', 'us_curve'), ('de', 'de_curve'),
                              ('ea', 'ea_curve'), ('jp', 'jp_curve'),
                              ('gb', 'gb_curve'), ('kr', 'kr_curve')):
        node = market.get(node_key) or {}
        if not node:
            continue
        prev_node = (prev or {}).get(country) or {}
        tenors = {}
        for tenor, row in node.items():
            if not isinstance(row, dict):
                continue
            lvl = row.get('level')
            # 출처가 바뀐 만기는 «어제 대비»가 성립하지 않는다. 야후 스팟과 FRED 는
            # 산출 기준이 달라, 어제 FRED 값과 오늘 야후 값을 빼면 그 차이의 일부는
            # 시장이 아니라 소스 교체가 만든 것이다.
            prev_src = ((prev_dates or {}).get('us_source') or {}).get(tenor) \
                if country == 'us' else None
            src_changed = bool(prev_src) and prev_src != row.get('source')
            stale = row.get('date') != market.get('report_date') or src_changed
            tenors[tenor] = {
                'level': lvl,
                # 기준일보다 오래된 관측이면 «어제 대비»가 성립하지 않는다. 0.0bp 로
                # 인쇄하면 「안 움직였다」로 읽히는데 사실은 그날 값이 없는 것이다.
                'bp': None if stale else _bp(lvl, prev_node.get(tenor)),
                'date': row.get('date'),
                'stale': stale,
                'source_changed': src_changed,
                'source': row.get('source'),
            }
        if not tenors:
            continue
        # 만기마다 관측 날짜가 다르다. 미국 커브는 5Y·10Y·30Y 가 야후 스팟(T-0)이고
        # 나머지는 FRED(T-1 이상)라 **한 날짜로 정렬되는 일이 없다.** 그래서
        # 「커브 전체가 정렬돼야 계산한다」는 규칙은 미국 커브를 통째로 죽인다.
        #
        # 대신 레포 규칙(2026-07-28)을 따른다 — **각 파생값을 그것이 쓰는 다리들의
        # 날짜로 판정하고, 어긋나면 근거를 병기한다.** 발행값은 그대로 내되
        # 「무엇과 무엇을 맞댄 값인가」를 숨기지 않는다.
        dates = {v['date'] for v in tenors.values() if v.get('date')}
        latest = max(dates) if dates else None

        def pair(a, b):
            ra, rb = tenors.get(a), tenors.get(b)
            if not ra or not rb:
                return None, None, False
            bp = curve_mod.spread_bp(ra['level'], rb['level'])
            same = ra.get('date') == rb.get('date')
            basis = (f'{a} {ra.get("date")}({ra.get("source")}) · '
                     f'{b} {rb.get("date")}({rb.get("source")})')
            return bp, basis, same

        s2s10, b2s10, a2s10 = pair('2Y', '10Y')
        s5s30, b5s30, a5s30 = pair('5Y', '30Y')

        # 같은 날짜 다리끼리만 모아 선도금리를 만든다 — 이틀치를 섞은 커브에서
        # 뽑은 선도금리는 아무 뜻이 없다.
        same_day = {_years(t): v['level'] for t, v in tenors.items()
                    if _years(t) and v.get('date') == latest}
        # 커브 형태의 짧은 다리는 2년물이 원칙이다. 2년물이 낡은 날은 **2년 이상의
        # 가장 짧은 «오늘» 다리**로 대신한다 — 3개월물로 내려가면 안 된다. 단기 T-bill 은
        # 자금 사정·발행 물량에 흔들려 듀레이션 커브의 앞단을 대표하지 못하고,
        # 실제로 그렇게 잡았더니 10년물이 +9bp 오른 날을 「불 스티프닝」이라 불렀다.
        short_tenor = '2Y' if (tenors.get('2Y') or {}).get('bp') is not None else None
        if short_tenor is None:
            fresh = sorted((y, t) for t, y in ((t, _years(t)) for t in tenors)
                           if y and 2 <= y < 10
                           and (tenors[t] or {}).get('bp') is not None)
            short_tenor = fresh[0][1] if fresh else None
        short = (tenors.get(short_tenor) or {}).get('bp') if short_tenor else None
        long = tenors.get('10Y', {}).get('bp')
        out[country] = {
            'tenors': tenors,
            'curve_date': latest,
            'aligned': len(dates) == 1,
            'shape': curve_mod.shape(short, long),
            'shape_basis': (None if not short_tenor
                            else f'{short_tenor} 대 10Y'),
            'spread_2s10s_bp': s2s10,
            'spread_2s10s_basis': b2s10,
            'spread_2s10s_aligned': a2s10,
            'spread_5s30s_bp': s5s30,
            'spread_5s30s_basis': b5s30,
            'spread_5s30s_aligned': a5s30,
            'forwards': curve_mod.forwards(same_day),
            'forwards_date': latest,
        }
    return out


_YEARS = {'3M': 0.25, '6M': 0.5, '1Y': 1, '2Y': 2, '3Y': 3, '4Y': 4, '5Y': 5,
          '6Y': 6, '7Y': 7, '8Y': 8, '9Y': 9, '10Y': 10, '15Y': 15, '20Y': 20,
          '25Y': 25, '30Y': 30, '40Y': 40}


def _years(tenor):
    return _YEARS.get(tenor)


def rate_decomposition(market, prev):
    """명목 = 실질 + 기대인플레. 세 다리가 공통 날짜일 때만 계산한다.

    FRED 가 DGS·DFII·BEI 를 다른 시차로 내서, 정렬하지 않으면 항등식이 안 닫힌다
    (US 브리프가 2026-08-18 에 겪은 것과 같은 문제). 공통 날짜가 없으면 생략한다.
    """
    out = {}
    for tenor in ('5Y', '10Y', '30Y'):
        # 명목은 **FRED 계열**을 쓴다. 발행용 명목금리는 야후 스팟(T-0)이지만
        # 실질·기대인플레는 FRED 에만 있고 T-1 이라, 야후 명목과는 날짜가 영원히
        # 안 맞는다. 항등식이 닫히려면 세 다리가 같은 소스·같은 날이어야 한다.
        nom = ((market.get('us_curve_fred') or {}).get(tenor)
               or (market.get('us_curve') or {}).get(tenor) or {})
        real = (market.get('real_yields') or {}).get(tenor) or {}
        bei = (market.get('breakeven') or {}).get(tenor) or {}
        dates = {nom.get('date'), real.get('date'), bei.get('date')}
        if None in dates or len(dates) != 1:
            continue
        # 변화량도 **같은 두 날짜** 사이에서 뺀다. 각 계열의 직전 관측에서 따로 빼면
        # 항등식이 안 닫힌다 — 세 계열의 직전 관측일이 서로 다르기 때문이다.
        prev_dates = {nom.get('prev_date'), real.get('prev_date'), bei.get('prev_date')}
        if None in prev_dates or len(prev_dates) != 1:
            continue
        n_bp = _bp(nom.get('level'), nom.get('prev_level'))
        r_bp = _bp(real.get('level'), real.get('prev_level'))
        b_bp = _bp(bei.get('level'), bei.get('prev_level'))
        if None in (n_bp, r_bp, b_bp):
            continue
        driver = ('무변화' if abs(n_bp) < 1 else
                  '실질금리' if abs(r_bp) > abs(b_bp) * 1.5 else
                  '기대인플레' if abs(b_bp) > abs(r_bp) * 1.5 else '동반')
        out[tenor] = {'date': nom.get('date'), 'prev_date': nom.get('prev_date'),
                      'nominal_bp': n_bp, 'real_bp': r_bp, 'breakeven_bp': b_bp,
                      'residual_bp': round(n_bp - r_bp - b_bp, 1),
                      'driver_ko': driver,
                      'real_level': real.get('level'), 'bei_level': bei.get('level')}
    return out


def credit_block(market, prev, rows, prev_dates=None):
    out = {}
    for key, row in (market.get('credit') or {}).items():
        if not isinstance(row, dict):
            continue
        val = row.get('value')
        series = _series(rows, ('credit', key))
        st = credit_mod.standing(series, val) if series else None
        # 크레딧은 게시가 하루 늦어 항상 기준일보다 앞선 날짜를 단다. 그래서
        # 「어제 대비」는 **전일 원장 행에 담긴 관측 날짜**와 맞대야 성립한다.
        # 두 관측이 같은 날짜면 값이 안 변한 게 아니라 새 값이 없는 것이고,
        # 0.0bp 로 인쇄하면 「안 움직였다」는 거짓말이 된다.
        prev_date = ((prev_dates or {}).get('credit') or {}).get(key)
        stale = bool(prev_date) and prev_date == row.get('date')
        out[key] = {
            'value': val,
            'bp': round(val * 100, 1) if val is not None else None,
            'chg_bp': (None if stale
                       else _bp(val, ((prev or {}).get('credit') or {}).get(key))),
            'stale': stale,
            'date': row.get('date'),
            'source': row.get('source', 'FRED'),
            'standing': st,
        }
    return out


def etf_block(market, prev, prev_date):
    out = {}
    for ticker, row in (market.get('etf') or {}).items():
        p = ((prev or {}).get('etf') or {}).get(ticker) or {}
        prev_nav_date = p.get('nav_as_of')
        close, nav = row.get('close'), row.get('nav')
        nav_ret = _pct(nav, p.get('nav'))
        # 프리미엄/디스카운트는 **같은 날의** 종가와 NAV 를 맞댈 때만 뜻이 있다.
        # 발행사 NAV 가 하루 앞서는 날이 있어서(2026-08-27 실측: NAV 08-28 vs 종가
        # 08-27) 그대로 나누면 하루치 시장 움직임이 괴리로 둔갑한다.
        aligned = (bool(row.get('nav_as_of'))
                   and row.get('nav_as_of') == row.get('close_date'))
        # NAV 수익률과 순유입도 두 NAV 관측 날짜가 하루 벌어져 있을 때만 뜻이 있다.
        nav_step = bool(prev_nav_date) and prev_nav_date != row.get('nav_as_of')
        if not nav_step:
            nav_ret = None
        out[ticker] = {
            **row,
            'oas_bp': (None if row.get('oas_bp') is None
                       else round(row['oas_bp'], 1)),
            'nav_aligned': aligned,
            'change_pct': _pct(close, p.get('close')),
            'nav_return_pct': nav_ret,
            'premium_pct': etf_mod.premium_discount(close, nav) if aligned else None,
            'flow_est_usd': (etf_mod.flow_estimate(row.get('aum_usd'),
                                                   p.get('aum_usd'), nav_ret)
                             if nav_step else None),
            # 발행본은 순자산을 십억 달러로 인쇄한다. 게이트가 임의의 값을 10억으로
            # 나눠 허용하게 두는 대신, 인쇄하는 단위를 여기서 만들어 내려보낸다.
            'aum_bn': (None if row.get('aum_usd') is None
                       else round(row['aum_usd'] / 1e9, 1)),
            'duration_chg': (None if None in (row.get('duration'), p.get('duration'))
                             else round(row['duration'] - p['duration'], 3)),
            'ytw_chg_bp': _bp(row.get('ytw_pct'), p.get('ytw_pct')),
            'flow_basis_date': prev_date,
        }
    return out


def econ_block(econ, limit=10):
    """경제지표 실제·직전·차이. 차이를 렌더 시점에 빼면 그 값이 어느 데이터 파일에도
    없어서 게이트가 창작으로 잡는다(2026-08-31 실측). 여기서 미리 빼 둔다."""
    out = []
    for it in ((econ or {}).get('indicators') or [])[:limit]:
        a, p_ = it.get('actual'), it.get('previous')
        out.append({'name': it.get('name'), 'axis': it.get('axis'),
                    'actual': a, 'previous': p_, 'units': it.get('units') or '',
                    'diff': None if None in (a, p_) else round(a - p_, 4),
                    'ref_period': it.get('ref_period')})
    return out


def compute(market, rows, econ=None):
    """오늘의 원자료 + 원장 -> 발행본이 인용할 모든 파생값."""
    from .history import previous
    report_date = market.get('report_date')
    prev = previous(rows, report_date) if report_date else None
    prev_date = prev.get('report_date') if prev else None
    prev_dates = (prev or {}).get('dates') or {}
    curves = curve_block(market, prev, prev_dates)
    etfs = etf_block(market, prev, prev_date)
    fx = {}
    for k, row in (market.get('fx') or {}).items():
        if not isinstance(row, dict):
            continue
        base_date, base = _last_before(rows, ('fx', k), report_date)
        fx[k] = {**row,
                 'change_pct': _pct(row.get('level'), base),
                 'vs_date': base_date,
                 'vs_prev_session': base_date == prev_date}

    move = (market.get('vol') or {}).get('move')
    us10 = _lvl(market.get('us_curve'), '10Y')
    us_series = _series(rows, ('us', '10Y')) + ([us10] if us10 is not None else [])
    move_series = _series(rows, ('move',)) + ([move] if move is not None else [])
    us30 = _lvl(market.get('us_curve'), '30Y')
    us30_series = _series(rows, ('us', '30Y')) + ([us30] if us30 is not None else [])

    out = {
        'report_date': report_date,
        'prev_date': prev_date,
        'sessions_in_ledger': len(rows),
        'curves': curves,
        'decomposition': rate_decomposition(market, prev),
        'credit': credit_block(market, prev, rows, prev_dates),
        'fx': fx,
        'etf': etfs,
        'benchmark': etf_mod.attribution(etfs),
        'vol': {'move': move,
                'date': (market.get('vol') or {}).get('date'),
                'stale': bool((market.get('vol') or {}).get('stale')),
                'move_chg': (None if (market.get('vol') or {}).get('stale')
                             or None in (move, (prev or {}).get('move'))
                             else round(move - prev['move'], 2)),
                'standing': credit_mod.standing(move_series, move)},
        # 「지금 어디에 서 있나」 — 백분위를 한 번도 말하지 않는 발행본이 되지 않게
        # 기계가 먼저 계산해 둔다(US 브리프가 2026-08-30 에 겪은 실패와 같은 구조).
        'standing': {
            'us10y': credit_mod.standing(us_series, us10),
            'us30y': credit_mod.standing(us30_series, us30),
        },
    }
    out['teaching'] = teaching_block(out)
    out['econ'] = econ_block(econ)

    # 무엇을 얼마나 볼지는 «선언»이 아니라 벤치마크 노출에서 «역산»한다
    # (2026-09-01 사용자 지시). 벤치마크가 바뀌면 모니터링 비중도 따라 바뀐다.
    out['exposure'] = exp_mod.monitor_plan(
        [(t, w) for t, w, _ in etf_mod.BENCHMARK])
    out['segments'] = {t: exp_mod.SEGMENT_KO[exp_mod.segment_of(t)]
                       for t in (market.get('etf') or {})}
    out['etf_factors'] = exp_mod.per_etf(list(market.get('etf') or {}))

    # 해외 금리를 매일 보는 유일한 정당한 이유 — 동조인가 미국 고유인가.
    us10_bp = ((curves.get('us') or {}).get('tenors') or {}).get('10Y', {}).get('bp')
    out['divergence'] = {}
    for key, label in (('de', '독일'), ('jp', '일본'), ('gb', '영국')):
        f = ((curves.get(key) or {}).get('tenors') or {}).get('10Y', {}).get('bp')
        d = exp_mod.divergence(us10_bp, f, label)
        if d:
            out['divergence'][key] = d

    # 국가 간 금리차도 두 나라의 관측 날짜가 같을 때만 뜻이 있다. 독일이 T-0,
    # 영국이 T-1 로 오는 날이 실제로 있어서(2026-08-27 실측) 날짜를 안 보면
    # 하루 어긋난 금리차를 인쇄하게 된다.
    us_date = ((market.get('us_curve') or {}).get('10Y') or {}).get('date')

    def cross(node_key):
        row = (market.get(node_key) or {}).get('10Y') or {}
        if not row.get('date') or row['date'] != us_date:
            return None
        return curve_mod.spread_bp(row.get('level'), us10)

    out['us_de_10y_bp'] = cross('de_curve')
    out['us_jp_10y_bp'] = cross('jp_curve')
    out['us_gb_10y_bp'] = cross('gb_curve')
    out['cross_basis_date'] = us_date
    out['triggers'] = trigger_metrics(out, us_series, rows)
    out['diff_summary'] = diff_summary(out)
    return out


def trigger_metrics(m, us10_series, rows):
    """뷰 3축 트리거가 이름으로 참조하는 평평한 지표 사전.

    이름은 계약이다 — `bond_stance.json` 의 트리거가 이 키를 문자열로 가리키므로,
    키를 바꾸면 그날 트리거가 조용히 UNKNOWN 이 된다(그래서 UNKNOWN 은 NOT_MET 이
    아니라 「확대 불가」로 처리된다).
    """
    us = (m['curves'].get('us') or {})
    tn = us.get('tenors') or {}
    hy = (m['credit'].get('us_hy') or {})
    ig = (m['credit'].get('us_ig') or {})
    dec10 = (m['decomposition'].get('10Y') or {})

    ma20 = _ma(us10_series, 20)
    lvl10 = (tn.get('10Y') or {}).get('level')

    def chg(path, n):
        s = _series(rows, path)
        cur = {'us': lvl10}.get(path[0])
        if path[0] == 'credit':
            cur = (m['credit'].get(path[1]) or {}).get('value')
        if cur is None or len(s) < n:
            return None
        return round((cur - s[-n]) * 100, 1)

    return {
        'us10y_level': lvl10,
        'us10y_1d_bp': (tn.get('10Y') or {}).get('bp'),
        'us10y_dma20_gap_bp': (None if None in (lvl10, ma20)
                               else round((lvl10 - ma20) * 100, 1)),
        'us10y_5d_bp': chg(('us', '10Y'), 5),
        'us2y_1d_bp': (tn.get('2Y') or {}).get('bp'),
        'spread_2s10s_bp': us.get('spread_2s10s_bp'),
        'spread_2s10s_aligned': 1 if us.get('spread_2s10s_aligned') else 0,
        'spread_5s30s_bp': us.get('spread_5s30s_bp'),
        'spread_5s30s_aligned': 1 if us.get('spread_5s30s_aligned') else 0,
        'move_level': (m['vol'] or {}).get('move'),
        'move_chg': (m['vol'] or {}).get('move_chg'),
        'hy_oas_bp': hy.get('bp'),
        'hy_oas_1d_bp': hy.get('chg_bp'),
        'hy_oas_5d_bp': chg(('credit', 'us_hy'), 5),
        'hy_oas_pctile': ((hy.get('standing') or {}) or {}).get('percentile'),
        'ig_oas_bp': ig.get('bp'),
        'ig_oas_1d_bp': ig.get('chg_bp'),
        'ig_oas_pctile': ((ig.get('standing') or {}) or {}).get('percentile'),
        'real10y_1d_bp': dec10.get('real_bp'),
        'bei10y_1d_bp': dec10.get('breakeven_bp'),
        'us_de_10y_bp': m.get('us_de_10y_bp'),
        'fwd_1y1y': (us.get('forwards') or {}).get('1y1y'),
        'fwd_5y5y': (us.get('forwards') or {}).get('5y5y'),
    }


def teaching_block(m):
    """「오늘의 개념」이 쓰는 예제 수치.

    산문에 예시 숫자를 손으로 적으면 그 순간 창작이 되고, 게이트가 잡아야 마땅하다.
    그래서 예제도 **설명하는 그 함수가 직접 계산해서** 데이터로 내려보낸다.
    """
    us = (m['curves'].get('us') or {}).get('tenors') or {}
    bp30 = (us.get('30Y') or {}).get('bp')
    tlt = (m.get('etf') or {}).get('TLT') or {}
    bench_dur, port_dur, ref_bp = 6.5, 7.2, 10
    return {
        'tlt_duration': tlt.get('duration'),
        'tlt_theory_pct': etf_mod.duration_impact(tlt.get('duration'), bp30),
        'ref_duration': 6,
        'ref_bp': ref_bp,
        'ref_impact_pct': etf_mod.duration_impact(6, ref_bp),
        'benchmark_duration': bench_dur,
        'portfolio_duration': port_dur,
        'active_duration': round(port_dur - bench_dur, 2),
    }


def diff_summary(m):
    """§2 「어제 대비 바뀐 것」 — 크기순으로 줄 세운 변화 목록.

    무엇이 오늘의 뉴스인지를 기계가 고른다. writer 가 고르면 «쓰기 편한 것»을 고른다.
    """
    items = []

    def add(kind, label, value, unit, extra=None):
        if value is None:
            return
        items.append({'kind': kind, 'label': label, 'value': value,
                      'unit': unit, 'abs': abs(value), **(extra or {})})

    for country, node in (m.get('curves') or {}).items():
        for tenor, row in (node.get('tenors') or {}).items():
            add('rate', f'{country.upper()} {tenor}', row.get('bp'), 'bp',
                {'level': row.get('level'), 'date': row.get('date')})
    for key, row in (m.get('credit') or {}).items():
        add('credit', key, row.get('chg_bp'), 'bp',
            {'level_bp': row.get('bp'), 'date': row.get('date')})
    for key, row in (m.get('fx') or {}).items():
        add('fx', key, row.get('change_pct'), '%',
            {'level': row.get('level'), 'vs_date': row.get('vs_date'),
             'vs_prev_session': row.get('vs_prev_session')})
    for t, row in (m.get('etf') or {}).items():
        add('etf', t, row.get('change_pct'), '%', {'close': row.get('close')})
    add('vol', 'MOVE', (m.get('vol') or {}).get('move_chg'), 'pt',
        {'level': (m.get('vol') or {}).get('move')})

    items.sort(key=lambda x: -x['abs'])
    return {'movers': items[:12], 'count': len(items)}
