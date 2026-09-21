from copy import deepcopy
import importlib
import json
from pathlib import Path
import subprocess
import sys

import pytest


def module():
    spec = importlib.util.find_spec('scripts.common.research_ledger')
    assert spec is not None, 'research ledger module must exist'
    return importlib.import_module('scripts.common.research_ledger')


NOW = '2026-09-20T12:00:00+00:00'


def hypothesis(tmp_path, **changes):
    source = tmp_path / 'source.txt'
    source.write_text('Observed release and market prices', encoding='utf-8')
    p = dict(id='h1', type='hypothesis', market='us', report_date='2026-09-20',
             data_cutoff='2026-09-20T11:00:00+00:00',
             sources=[dict(id='s1', path=str(source), provenance='public release URL',
                           published_at='2026-09-20T10:00:00+00:00', observed_at='2026-09-20T10:30:00+00:00')],
             stage='insight', title='Reaction question', question='Why the muted reaction?',
             expectation=dict(kind='unknown', description='No measured baseline available'),
             observation='Prices barely moved', our_view='Possible prior pricing', difference='Unmeasured',
             mechanism='Prior positioning', alternative='Other simultaneous news', support='Observed reaction',
             invalidation='Reaction reverses', test_start_at='2026-09-21T12:00:00+00:00', deadline='2026-09-25T12:00:00+00:00', execution_status='watch')
    p.update(changes)
    return p


def review(tmp_path, **changes):
    p = hypothesis(tmp_path)
    r = {k: p[k] for k in ['market', 'report_date', 'data_cutoff', 'sources']}
    r['data_cutoff']=NOW
    r.update(id='r1', type='review', hypothesis_id='h1', direction='undecidable', mechanism='undecidable',
             status='open', rationale='Need more observations', performance={'status':'unavailable','reason':'No executed trade'})
    r.update(changes)
    return r


def test_append_retry_and_snapshot(tmp_path):
    m = module(); root = tmp_path / 'research'; p = hypothesis(tmp_path)
    first = m.append_record(root, p, now=NOW)
    assert m.append_record(root, p, now='2026-09-21T12:00:00Z') == first
    assert len(m.read_records(root)) == 1
    assert first['prospective'] is True
    Path(p['sources'][0]['path']).unlink()
    assert m.read_records(root)[0]['id'] == 'h1'
    p['title'] = 'Changed'
    with pytest.raises(ValueError): m.append_record(root, p, now=NOW)


@pytest.mark.parametrize('mutation', ['future', 'naive', 'override', 'stage', 'known', 'trade'])
def test_invalid_hypothesis(tmp_path, mutation):
    p = hypothesis(tmp_path)
    if mutation == 'future': p['sources'][0]['observed_at'] = '2026-09-21T00:00:00Z'
    if mutation == 'naive': p['data_cutoff'] = '2026-09-20T11:00:00'
    if mutation == 'override': p['recorded_at'] = NOW
    if mutation == 'stage': p['stage'] = 'verified'
    if mutation == 'known': p['expectation']['kind'] = 'survey'
    if mutation == 'trade': p['stage'] = 'idea'
    with pytest.raises(ValueError): module().append_record(tmp_path/'r', p, now=NOW)


@pytest.mark.parametrize('target', ['ledger', 'evidence'])
def test_tampering_fails(tmp_path, target):
    m=module(); root=tmp_path/'r'; record=m.append_record(root,hypothesis(tmp_path),now=NOW)
    path = root/'ledger.jsonl' if target=='ledger' else root/record['sources'][0]['snapshot']
    path.write_text(path.read_text().replace('Reaction', 'Changed') if target=='ledger' else 'tampered')
    with pytest.raises(ValueError): m.read_records(root)


def test_review_references_and_asof(tmp_path):
    m=module(); root=tmp_path/'r'
    with pytest.raises(ValueError): m.append_record(root, review(tmp_path), now=NOW)
    m.append_record(root,hypothesis(tmp_path),now=NOW)
    with pytest.raises(ValueError): m.append_record(root,review(tmp_path, market='kr'),now=NOW)
    m.append_record(root,review(tmp_path,status='closed',direction='weakened'),now='2026-09-22T12:00:00Z')
    earlier=m.summarize(root,'us','2026-09-21','2026-09-21','2026-09-21T23:00:00Z')
    assert earlier['hypotheses'][0]['status']=='open'
    later=m.summarize(root,'us','2026-09-20','2026-09-23','2026-09-23T00:00:00Z')
    assert later['hypotheses'][0]['direction']=='weakened'
    assert m.summarize(root,'kr','2026-09-20','2026-09-23','2026-09-23T00:00:00Z')['hypotheses']==[]


def test_retrospective_and_missing_costs(tmp_path):
    m=module();root=tmp_path/'r'
    m.append_record(root,hypothesis(tmp_path,test_start_at='2026-09-18T12:00:00Z',deadline='2026-09-19T12:00:00Z',execution_status='not_taken'),now=NOW)
    result=m.summarize(root,'us','2026-09-20','2026-09-20',NOW)
    assert result['counts']['prospective']==0
    assert result['hypotheses'][0]['execution_status']=='not_taken'
    with pytest.raises(ValueError): m.append_record(root,review(tmp_path,performance={'status':'verified','net':4}),now=NOW)


def test_cycle_requires_due_review_or_reason(tmp_path):
    m=module();root=tmp_path/'r';p=hypothesis(tmp_path,test_start_at='2026-09-20T12:30:00Z',deadline='2026-09-20T13:00:00Z')
    m.append_record(root,p,now=NOW)
    c={k:p[k] for k in ['market','report_date','data_cutoff','sources']}
    c.update(id='c1',type='cycle',report_date='2026-09-21',central_questions=['What changed?'],candidate_ids=[],reviewed_ids=[],unresolved=[],no_candidate_reason='No new supported idea')
    with pytest.raises(ValueError): m.append_record(root,c,now='2026-09-21T12:00:00Z')
    c['unresolved']=[{'hypothesis_id':'h1','reason':'Next release pending'}]
    m.append_record(root,c,now='2026-09-21T12:00:00Z')


def test_empty_and_malformed(tmp_path):
    m=module();root=tmp_path/'r'
    assert m.summarize(root,'us','2026-09-20','2026-09-20',NOW)['counts']['total']==0
    root.mkdir();(root/'ledger.jsonl').write_text('not json\n')
    with pytest.raises(ValueError):m.read_records(root)


def test_cli_template_and_empty_summary(tmp_path):
    script=Path(__file__).resolve().parents[2]/'research_ledger.py'
    assert script.exists()
    output=subprocess.run([sys.executable,str(script),'template','--kind','hypothesis','--market','us'],capture_output=True,text=True)
    assert output.returncode==0, output.stderr
    assert json.loads(output.stdout)['type']=='hypothesis'
    output=subprocess.run([sys.executable,str(script),'summary','--root',str(tmp_path/'r'),'--market','us','--start','2026-09-20','--end','2026-09-20','--as-of',NOW],capture_output=True,text=True)
    assert output.returncode==0,output.stderr
    assert json.loads(output.stdout)['counts']['total']==0


def test_event_expectation_cannot_use_post_event_source(tmp_path):
    p=hypothesis(tmp_path)
    p['event']={'name':'Release','scheduled_at':'2026-09-20T10:15:00Z',
        'expectations':[{'kind':'survey','instrument':'CPI','horizon':'current month','source_ids':['s1'],'observed_at':'2026-09-20T10:00:00Z','value':3.1,'unit':'percent'}],
        'missing':['Actual and price path unavailable']}
    with pytest.raises(ValueError):module().append_record(tmp_path/'r',p,now=NOW)


def test_invalid_event_numeric_and_complete_snapshot(tmp_path):
    p=hypothesis(tmp_path)
    p['event']={'name':'Release','scheduled_at':'2026-09-20T10:45:00Z',
        'expectations':[{'kind':'survey','instrument':'CPI','horizon':'current month','source_ids':['s1'],'observed_at':'2026-09-20T10:35:00Z','value':3.1,'unit':'percent'}],
        'actual':{'value':3.2,'unit':'percent','source_ids':['s1'],'observed_at':'2026-09-20T10:45:00Z'},
        'reactions':[{'window':'immediate','instrument':'2Y Treasury','start_at':'2026-09-20T10:45:00Z','end_at':'2026-09-20T11:00:00Z','before':4.1,'after':float('nan'),'unit':'percent','source_ids':['s1']}]}
    with pytest.raises(ValueError):module().append_record(tmp_path/'r',p,now=NOW)
    p['event']['reactions'][0]['after']=4.15
    assert module().append_record(tmp_path/'r',p,now=NOW)['event']['actual']['value']==3.2


def test_reject_unknown_input_field(tmp_path):
    with pytest.raises(ValueError):module().append_record(tmp_path/'r',hypothesis(tmp_path,actual_pnl=1000),now=NOW)


def test_verified_performance_preserves_comparable_metrics(tmp_path):
    m=module();root=tmp_path/'r';m.append_record(root,hypothesis(tmp_path),now=NOW)
    p=review(tmp_path)
    p['data_cutoff']='2026-09-22T11:00:00Z'
    p['performance']={'status':'verified','basis':'External realized return statement','unit':'percent','benchmark_name':'Cash same capital and dates','cost_basis':'All fees and financing included','source_ids':['s1'],'start_at':'2026-09-20T12:00:00Z','end_at':'2026-09-22T10:00:00Z','gross':1.5,'costs':0.2,'net':1.3,'benchmark':0.1}
    result=m.append_record(root,p,now='2026-09-22T12:00:00Z')
    assert result['performance']['net']==1.3


def test_retry_detects_changed_source_bytes(tmp_path):
    m=module();p=hypothesis(tmp_path);root=tmp_path/'r'
    m.append_record(root,p,now=NOW)
    Path(p['sources'][0]['path']).write_text('Different evidence')
    with pytest.raises(ValueError):m.append_record(root,p,now=NOW)


def test_test_start_controls_preregistration(tmp_path):
    m=module();p=hypothesis(tmp_path,test_start_at='2026-09-20T11:30:00Z')
    assert m.append_record(tmp_path/'r',p,now=NOW)['prospective'] is False
    p=hypothesis(tmp_path,id='h2',test_start_at='2026-09-26T00:00:00Z')
    with pytest.raises(ValueError):m.append_record(tmp_path/'r',p,now=NOW)


def test_cycle_rejects_stale_candidate_and_stale_review(tmp_path):
    m=module();root=tmp_path/'r';p=hypothesis(tmp_path)
    m.append_record(root,p,now=NOW)
    r=review(tmp_path);r['data_cutoff']=NOW
    m.append_record(root,r,now=NOW)
    c={k:p[k] for k in ['market','data_cutoff','sources']}
    c.update(id='c1',type='cycle',report_date='2026-09-21',central_questions=['What changed?'],candidate_ids=['h1'],reviewed_ids=[],unresolved=[])
    with pytest.raises(ValueError):m.append_record(root,c,now='2026-09-21T12:00:00Z')
    c.update(candidate_ids=[],no_candidate_reason='No new ideas',reviewed_ids=['r1'])
    with pytest.raises(ValueError):m.append_record(root,c,now='2026-09-21T12:00:00Z')


def test_review_cannot_predate_hypothesis_information(tmp_path):
    m=module();root=tmp_path/'r';m.append_record(root,hypothesis(tmp_path),now=NOW)
    p=review(tmp_path);p['data_cutoff']='2026-09-20T11:00:00Z'
    with pytest.raises(ValueError):m.append_record(root,p,now=NOW)


def test_cli_requires_explicit_root(tmp_path):
    script=Path(__file__).resolve().parents[2]/'research_ledger.py'
    output=subprocess.run([sys.executable,str(script),'validate'],capture_output=True,text=True)
    assert output.returncode!=0
    assert '--root' in output.stderr


def test_retry_same_bytes_different_path_is_idempotent(tmp_path):
    m=module();p=hypothesis(tmp_path);root=tmp_path/'r'
    first=m.append_record(root,p,now=NOW)
    copied=tmp_path/'copy.txt';copied.write_bytes(Path(p['sources'][0]['path']).read_bytes())
    p['sources'][0]['path']=str(copied)
    assert m.append_record(root,p,now=NOW)==first


def test_cycle_requires_latest_review_on_same_date(tmp_path):
    m=module();p=hypothesis(tmp_path);root=tmp_path/'r';m.append_record(root,p,now=NOW)
    m.append_record(root,review(tmp_path),now=NOW)
    m.append_record(root,review(tmp_path,id='r2'),now=NOW)
    c={k:p[k] for k in ['market','report_date','data_cutoff','sources']}
    c.update(id='c1',type='cycle',central_questions=['What changed?'],candidate_ids=['h1'],reviewed_ids=['r1'],unresolved=[])
    with pytest.raises(ValueError):m.append_record(root,c,now=NOW)
    c['reviewed_ids']=['r2']
    assert m.append_record(root,c,now=NOW)['id']=='c1'


def test_future_report_date_rejected(tmp_path):
    with pytest.raises(ValueError):module().append_record(tmp_path/'r',hypothesis(tmp_path,report_date='2026-09-21'),now=NOW)


def test_read_and_append_use_shared_and_exclusive_locks(tmp_path):
    # A held exclusive writer lock must prevent a separate reader from observing a partial append.
    import fcntl
    import time
    root=tmp_path/'r';root.mkdir()
    with (root/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        code="from scripts.common.research_ledger import read_records; import sys; print(read_records(sys.argv[1]))"
        proc=subprocess.Popen([sys.executable,'-c',code,str(root)],stdout=subprocess.PIPE,text=True)
        try:
            time.sleep(0.1)
            assert proc.poll() is None
            fcntl.flock(lock,fcntl.LOCK_UN)
            assert proc.communicate(timeout=3)[0].strip()=='[]'
        finally:
            if proc.poll() is None:proc.kill();proc.wait()


def test_cycle_cannot_omit_closed_failure_review(tmp_path):
    m=module();p=hypothesis(tmp_path);root=tmp_path/'r';m.append_record(root,p,now=NOW)
    m.append_record(root,review(tmp_path,status='closed',direction='weakened'),now=NOW)
    c={k:p[k] for k in ['market','report_date','data_cutoff','sources']}
    c.update(id='c1',type='cycle',central_questions=['What changed?'],candidate_ids=['h1'],reviewed_ids=[],unresolved=[])
    with pytest.raises(ValueError):m.append_record(root,c,now=NOW)
    c['reviewed_ids']=['r1'];assert m.append_record(root,c,now=NOW)['id']=='c1'
    c['id']='c2';assert m.append_record(root,c,now=NOW)['id']=='c2'


def test_cycle_cannot_omit_same_day_hypothesis(tmp_path):
    m=module();p=hypothesis(tmp_path);root=tmp_path/'r';m.append_record(root,p,now=NOW)
    c={k:p[k] for k in ['market','report_date','data_cutoff','sources']}
    c.update(id='c1',type='cycle',central_questions=['What changed?'],candidate_ids=[],reviewed_ids=[],unresolved=[{'hypothesis_id':'h1','reason':'Pending'}],no_candidate_reason='No new ideas')
    with pytest.raises(ValueError):m.append_record(root,c,now=NOW)
