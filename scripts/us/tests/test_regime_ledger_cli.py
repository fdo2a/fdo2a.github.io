"""기록 → 주간 빌드 를 실제 명령줄로 잇는다. 한 주를 매일 기록하고 토요일에 센다."""

import json
import os
import subprocess
import sys

from us.period_gate import _numbers

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
WEEK = ['2026-11-02', '2026-11-03', '2026-11-04', '2026-11-05', '2026-11-06']


def _w(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)


def _day(d, day, nfp_ref, cpi_ref, run='r'):
    gen = f'{day} 08:00 KST'
    inds = [{'name': 'Nonfarm Payrolls (chg)', 'label_ko': '비농업 고용', 'axis': 'Labor',
             'ref_period': nfp_ref, 'actual': 119.0, 'direction': '개선', 'vs_prev': '개선'},
            {'name': 'CPI YoY', 'label_ko': 'CPI', 'axis': 'Inflation',
             'ref_period': cpi_ref, 'actual': 3.0, 'direction': '둔화', 'vs_prev': '하락'}]
    _w(os.path.join(d, 'macro_metrics.json'), {'report_date': day, 'generated': gen, 'indicators': inds})
    _w(os.path.join(d, 'econ_indicators.json'), {'generated': gen, 'indicators': inds})
    _w(os.path.join(d, 'market_data.json'), {'report_date': day, 'generated': gen})
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'record_releases.py'),
                        '--datadir', d, '--run-id', run], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_a_normal_week_end_to_end(tmp_path):
    d = str(tmp_path)
    _w(os.path.join(d, 'market_holidays.json'), {'us': {'dates': [], 'valid_through': '2027-12-31'}})
    os.makedirs(os.path.join(d, 'history'))
    with open(os.path.join(d, 'history', 'macro.jsonl'), 'w') as fh:
        fh.write(json.dumps({'report_date': '2026-10-30', 'regime': {'growth': 1, 'inflation': 1}}) + '\n')
    _day(d, '2026-10-30', '2026-09-01', '2026-09-01')            # 출발점
    for day in WEEK:
        nfp = '2026-10-01' if day >= '2026-11-06' else '2026-09-01'
        cpi = '2026-10-01' if day >= '2026-11-04' else '2026-09-01'
        _day(d, day, nfp, cpi)
    _day(d, '2026-11-06', '2026-10-01', '2026-10-01', run='retry')  # 같은 날 재실행
    agg = os.path.join(d, 'weekly.json')
    _w(agg, {'key': '2026-W45', 'span': 'weekly', 'start_date': WEEK[0], 'end_date': WEEK[-1]})
    out = os.path.join(d, 'period_scorecard.json')
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'build_scorecard.py'), '--agg', agg,
                        '--datadir', d, '--out', out], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    reg = json.load(open(out))['regime']
    assert reg['days_scanned'] == 5 and reg['missing_days'] == []
    assert reg['growth']['verdict'] == '정합' and reg['growth']['total'] == 1
    assert reg['inflation']['verdict'] == '불일치' and reg['inflation']['total'] == 1
    assert reg['verdict'] == '엇갈림'
    ledger = [json.loads(x) for x in open(os.path.join(d, 'history', 'releases.jsonl'))]
    assert sum(1 for x in ledger if x['kind'] == 'release') == 2


def test_dates_in_the_regime_block_are_not_quotable_numbers():
    reg = {'missing_days': ['2026-11-04'], 'prints': [{'date': '2026-11-06', 'ref_period': '2026-10-01',
                                                        'official_date': '2026-11-06',
                                                        'detected_on': '2026-11-06'}],
           'growth': {'pct': 67, 'total': 3}}
    nums = _numbers({'regime': reg})
    assert '67' in {str(n) for n in nums} or 67 in nums
    for bad in ('-04', '-06', '-11', '2026', '04', '-01'):
        assert bad not in {str(n) for n in nums}


def test_the_workflow_records_after_collect_and_before_the_calendar_rewrite():
    """공식일은 이번 실행이 덮어쓰기 전의 calendar.json 에서 온다 — 순서가 계약이다."""
    import yaml
    wf = yaml.safe_load(open(os.path.join(ROOT, '..', '.github', 'workflows',
                                          'collect-market-data.yml'), encoding='utf-8'))
    steps = next(j['steps'] for j in wf['jobs'].values()
                 if any('record_releases.py' in (s.get('run') or '') for s in j.get('steps') or []))
    names = [s.get('name') or '' for s in steps]
    rec = next(i for i, s in enumerate(steps) if 'record_releases.py' in (s.get('run') or ''))
    col = next(i for i, s in enumerate(steps) if 'collect_market_data.py --outdir' in (s.get('run') or ''))
    cal = next(i for i, s in enumerate(steps) if 'build_calendar.py' in (s.get('run') or ''))
    assert col < rec < cal, names
    assert steps[rec].get('if') == 'always()'
    commits = [s.get('run') or '' for s in steps if 'push_with_retry.sh' in (s.get('run') or '')]
    assert all('data/history' in c for c in commits), '두 커밋 경로 모두 원장을 담아야 한다'


def test_an_unreadable_ledger_makes_the_week_undecidable_without_crashing(tmp_path):
    d = str(tmp_path)
    _w(os.path.join(d, 'market_holidays.json'), {'us': {'dates': [], 'valid_through': '2027-12-31'}})
    os.makedirs(os.path.join(d, 'history', 'releases.jsonl'))     # 디렉터리 → OSError
    agg = os.path.join(d, 'weekly.json')
    _w(agg, {'key': '2026-W45', 'span': 'weekly', 'start_date': WEEK[0], 'end_date': WEEK[-1]})
    out = os.path.join(d, 'sc.json')
    r = subprocess.run([sys.executable, os.path.join(ROOT, 'build_scorecard.py'), '--agg', agg,
                        '--datadir', d, '--out', out], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    reg = json.load(open(out))['regime']
    assert reg['verdict'] == '판정불가' and reg['note'] == '새 발표 기록을 읽지 못했다'
    assert reg['growth']['note'] == '새 발표 기록을 읽지 못했다'
