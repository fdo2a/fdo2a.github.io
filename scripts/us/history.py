"""Append-only 이력 — stance.json / macro.json 은 매일 덮어쓰기라 과거 판단이 남지 않는다.

주간·월간 복기가 이 로그를 소비하지만, 로그 자체는 그것과 무관하게 있어야 할 자산이다.
쓰기는 멱등이다 — 같은 report_date 를 두 번 넣어도 한 줄이다.
"""

import json
import os
import tempfile

# 발동 판정에 필요한 필드만 — desc 산문은 매일 바뀌어 이력을 부풀리기만 한다
_TRIGGER_KEYS = ('kind', 'metric', 'op', 'value', 'toward')
_ASSET_KEYS = ('grade', 'label', 'since', 'thesis', 'tilt', 'curve')


def _trigger(t):
    return {k: t[k] for k in _TRIGGER_KEYS if k in t}


def stance_record(stance):
    assets = {}
    for key, a in (stance.get('assets') or {}).items():
        row = {k: a[k] for k in _ASSET_KEYS if k in a}
        trig = a.get('triggers') or {}
        row['triggers'] = {d: [_trigger(t) for t in (trig.get(d) or [])]
                           for d in ('increase', 'decrease')}
        assets[key] = row
    return {'report_date': stance.get('report_date'),
            'horizon': stance.get('horizon'),
            'assets': assets}


def macro_record(macro):
    return {'report_date': macro.get('report_date'),
            'horizon': macro.get('horizon'),
            'regime': macro.get('regime'),
            'policy_path': macro.get('policy_path')}


MARKET_GROUPS = ('indices', 'sectors', 'fx', 'commodities', 'memory', 'ai_infra')


def market_record(data):
    """그날 발행본이 인쇄한 시세 그대로 한 행.

    기간 집계는 이 원장만 읽는다. 시세를 다시 받으면 조정계수(auto_adjust)와 기준
    시각·출처가 달라져 총정리가 원본과 다른 숫자를 싣게 된다 — 2026-08-30 실측으로
    10년물 4.67 대 4.72(FRED 대 야후 스팟), 금 4,529.90 대 4,504.10, 원달러
    1,380.45 대 1,375.67이 갈렸고 주간본을 발행 직전에 회수했다. 총정리가 원본과
    다른 숫자를 싣는 것은 이 발행물의 존재 이유를 무너뜨린다.

    값이 없는 이름은 담지 않는다 — 빈 자리는 결측으로 남아야 하고, 기간 집계가
    `missing` 으로 알린다.
    """
    row = {'report_date': data.get('report_date')}
    for group in MARKET_GROUPS:
        row[group] = {name: float(r['last'])
                      for name, r in ((data or {}).get(group) or {}).items()
                      if isinstance(r, dict) and r.get('last') is not None}
    row['yields'] = {tenor: float(r['level'])
                     for tenor, r in ((data or {}).get('yields') or {}).items()
                     if isinstance(r, dict) and r.get('level') is not None}
    return row


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # 손상된 줄 하나가 이력 전체를 못 읽게 만들지 않는다
    return rows


def append_jsonl(path, record, key='report_date'):
    """Returns True if written, False if a row with the same key already existed."""
    val = record.get(key)
    if val is None:
        return False
    rows = read_jsonl(path)
    if any(r.get(key) == val for r in rows):
        return False
    rows.append(record)
    rows.sort(key=lambda r: r.get(key) or '')
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    # 같은 디렉터리에 임시 파일을 쓰고 os.replace 로 원자적으로 바꿔치기 —
    # 이 파일은 재구성 불가능한 유일본이라 중간에 죽어도 원본이 훼손되면 안 된다.
    fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.history-', suffix='.tmp')
    os.close(fd)
    try:
        with open(tmp_path, 'w', encoding='utf-8') as fh:
            for r in rows:
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    return True
