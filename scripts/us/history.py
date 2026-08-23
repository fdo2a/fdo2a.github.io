"""Append-only 이력 — stance.json / macro.json 은 매일 덮어쓰기라 과거 판단이 남지 않는다.

주간·월간 복기가 이 로그를 소비하지만, 로그 자체는 그것과 무관하게 있어야 할 자산이다.
쓰기는 멱등이다 — 같은 report_date 를 두 번 넣어도 한 줄이다.
"""

import json
import os

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
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + '\n')
    return True
