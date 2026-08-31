"""append-only 원장 — 채권 리포트의 「어제 대비」와 주간·월간 집계는 전부 여기서 나온다.

`bond_market.json` 은 매일 덮어쓰기라 어제 값이 남지 않는다. 그런데 이 리포트의 핵심
질문(「어제 대비 시장의 가격책정이 무엇이 바뀌었는가」)은 어제 값 없이는 성립하지 않는다.
그래서 원장을 쌓는다 — 주간·월간이 시세를 다시 받지 않는 이유와 같다(2026-08-30).

쓰기는 멱등이다. 같은 report_date 를 두 번 넣어도 한 줄이고, 나중 값이 이긴다.
"""

import json
import os
import tempfile


def _atomic_write(path, lines):
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d)
    try:
        with os.fdopen(fd, 'w') as f:
            for ln in lines:
                f.write(ln + '\n')
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def read(path):
    if not os.path.exists(path):
        return []
    out = []
    for ln in open(path):
        ln = ln.strip()
        if not ln:
            continue
        try:
            out.append(json.loads(ln))
        except json.JSONDecodeError:
            continue
    return out


def append(path, record, key='report_date'):
    """멱등 upsert. 날짜 순으로 정렬해 다시 쓴다."""
    if not record.get(key):
        raise ValueError(f'record has no {key}')
    rows = [r for r in read(path) if r.get(key) != record[key]]
    rows.append(record)
    rows.sort(key=lambda r: r.get(key) or '')
    _atomic_write(path, [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in rows])
    return len(rows)


def previous(rows, report_date, key='report_date'):
    """report_date 직전 행. 없으면 None — 첫 회차엔 「어제 대비」가 없다."""
    earlier = [r for r in rows if (r.get(key) or '') < report_date]
    return earlier[-1] if earlier else None


# 원장에 남길 필드 — 산문이나 라벨은 담지 않는다. 매일 바뀌면서 이력만 부풀린다.
def market_record(market):
    def curve(node):
        return {k: v.get('level') for k, v in (node or {}).items()
                if isinstance(v, dict) and v.get('level') is not None}

    def obs_dates(node):
        return {k: v.get('date') for k, v in (node or {}).items()
                if isinstance(v, dict) and v.get('date')}

    def obs_sources(node):
        return {k: v.get('source') for k, v in (node or {}).items()
                if isinstance(v, dict) and v.get('source')}

    return {
        'report_date': market.get('report_date'),
        # 관측 날짜를 버리면 다음 날 «어제 대비»가 성립하는지 판정할 수 없다.
        # 크레딧이 이틀 연속 같은 값을 주는 날과 정말 안 움직인 날이 구별되지 않는다.
        'dates': {
            'credit': obs_dates(market.get('credit')),
            'us': obs_dates(market.get('us_curve')),
            'us_source': obs_sources(market.get('us_curve')),
            'us_fred': obs_dates(market.get('us_curve_fred')),
            'de': obs_dates(market.get('de_curve')),
            'jp': obs_dates(market.get('jp_curve')),
            'gb': obs_dates(market.get('gb_curve')),
            'ea': obs_dates(market.get('ea_curve')),
        },
        'us': curve(market.get('us_curve')),
        # 발행값(야후 스팟)과 별개로 FRED 원본을 남긴다 — 명목=실질+기대인플레
        # 분해는 세 다리가 같은 소스·같은 날이어야 닫힌다.
        'us_fred': curve(market.get('us_curve_fred')),
        'de': curve(market.get('de_curve')),
        'jp': curve(market.get('jp_curve')),
        'gb': curve(market.get('gb_curve')),
        'kr': curve(market.get('kr_curve')),
        'ea': curve(market.get('ea_curve')),
        'real': curve(market.get('real_yields')),
        'bei': curve(market.get('breakeven')),
        'credit': {k: v.get('value') for k, v in (market.get('credit') or {}).items()
                   if isinstance(v, dict)},
        'fx': {k: v.get('level') for k, v in (market.get('fx') or {}).items()
               if isinstance(v, dict)},
        'move': (market.get('vol') or {}).get('move'),
        'etf': {k: {'close': v.get('close'), 'nav': v.get('nav'),
                    'nav_as_of': v.get('nav_as_of'),
                    'close_date': v.get('close_date'),
                    'aum_usd': v.get('aum_usd'), 'duration': v.get('duration'),
                    'ytw_pct': v.get('ytw_pct'), 'oas_bp': v.get('oas_bp')}
                for k, v in (market.get('etf') or {}).items()},
    }


def stance_record(book):
    keys = ('grade', 'label', 'since', 'thesis', 'tilt', 'segment')
    trig_keys = ('kind', 'metric', 'op', 'value', 'toward')
    assets = {}
    for key, a in (book.get('assets') or {}).items():
        row = {k: a[k] for k in keys if k in a}
        trig = a.get('triggers') or {}
        row['triggers'] = {d: [{k: t[k] for k in trig_keys if k in t}
                               for t in (trig.get(d) or [])]
                           for d in ('increase', 'decrease')}
        assets[key] = row
    return {'report_date': book.get('report_date'),
            'horizon': book.get('horizon'), 'assets': assets}
