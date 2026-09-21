"""Append-only, locally verifiable research records; no trade execution or edge scoring."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

AUTO = {'recorded_at', 'prospective', 'previous_hash', 'input_hash', 'hash'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def timestamp(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError('timezone required')
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError(f'Invalid timestamp: {value!r}') from exc


def require_text(record, *keys):
    for key in keys:
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError(f'Nonempty text required: {key}')


def choice(record, key, allowed):
    if record.get(key) not in allowed:
        raise ValueError(f'Invalid {key}: {record.get(key)!r}')


def source_refs(value, ids):
    if not isinstance(value, list) or not value or any(v not in ids for v in value):
        raise ValueError('source_ids must reference supplied evidence')


def finite(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('Metric must be a finite number')


def validate_event(event, cutoff, sources):
    ids={source["id"] for source in sources}
    observed={source["id"]:timestamp(source["observed_at"]) for source in sources}
    require_text(event, 'name')
    scheduled = timestamp(event['scheduled_at'])
    if scheduled > cutoff:
        raise ValueError('Event occurs after cutoff')
    for expected in event.get('expectations', []):
        choice(expected, 'kind', {'survey','market_price','narrative'})
        require_text(expected, 'instrument', 'horizon')
        source_refs(expected.get('source_ids'), ids)
        if timestamp(expected['observed_at']) >= scheduled or any(observed[i] > timestamp(expected['observed_at']) for i in expected['source_ids']):
            raise ValueError('Expectation must precede event')
        if 'value' in expected:
            finite(expected['value']); require_text(expected, 'unit')
    actual = event.get('actual')
    if actual:
        source_refs(actual.get('source_ids'), ids)
        if not scheduled <= timestamp(actual['observed_at']) <= cutoff:
            raise ValueError('Actual observation outside event/cutoff')
        if 'value' in actual:
            finite(actual['value']); require_text(actual, 'unit')
    for reaction in event.get('reactions', []):
        choice(reaction,'window',{'immediate','close'})
        require_text(reaction,'instrument')
        source_refs(reaction.get('source_ids'),ids)
        if not scheduled <= timestamp(reaction['start_at']) <= timestamp(reaction['end_at']) <= cutoff:
            raise ValueError('Reaction outside event/cutoff')
        if 'before' in reaction or 'after' in reaction:
            finite(reaction.get('before'));finite(reaction.get('after'));require_text(reaction,'unit')
    if not event.get('expectations') or not actual or not event.get('reactions'):
        if not isinstance(event.get('missing'),list) or not event['missing'] or not all(isinstance(v,str) and v.strip() for v in event['missing']):
            raise ValueError('Incomplete event requires missing-data reasons')


def validate(record, prior):
    fields = {'id','type','market','report_date','data_cutoff','sources'} | AUTO
    fields |= {'hypothesis': {'stage','title','question','expectation','observation','our_view','difference','mechanism','alternative','support','invalidation','deadline','test_start_at','execution_status','trade','event'}, 'review': {'hypothesis_id','direction','mechanism','status','rationale','performance'}, 'cycle': {'central_questions','candidate_ids','reviewed_ids','unresolved','no_candidate_reason'}}.get(record.get('type'), set())
    if set(record)-fields: raise ValueError(f'Unknown record fields: {set(record)-fields}')
    require_text(record,'id','report_date')
    report_date=date.fromisoformat(record['report_date'])
    choice(record,'market',{'us','kr'})
    choice(record,'type',{'hypothesis','review','cycle'})
    now=timestamp(record['recorded_at']);cutoff=timestamp(record['data_cutoff'])
    market_zone=ZoneInfo('America/New_York' if record['market']=='us' else 'Asia/Seoul')
    if report_date>now.astimezone(market_zone).date():raise ValueError('Future report date')
    if cutoff>now: raise ValueError('Cutoff cannot exceed recording time')
    if prior and now<timestamp(prior[-1]['recorded_at']): raise ValueError('Recording time regressed')
    sources=record.get('sources')
    if not isinstance(sources,list): raise ValueError('sources must be a list')
    ids=set()
    for source in sources:
        require_text(source,'id','provenance')
        if source['id'] in ids: raise ValueError('Duplicate source id')
        ids.add(source['id'])
        if not timestamp(source['published_at'])<=timestamp(source['observed_at'])<=cutoff:
            raise ValueError('Evidence time exceeds cutoff or precedes publication')
    kind=record['type']
    hypotheses={p['id']:p for p in prior if p['type']=='hypothesis' and p['market']==record['market']}
    if kind in {'hypothesis','review'} and not sources: raise ValueError('Evidence required')
    if kind=='hypothesis':
        choice(record,'stage',{'observation','insight','idea','edge_candidate'})
        choice(record,'execution_status',{'planned','watch','not_taken'})
        require_text(record,'title','question','observation','our_view','difference','mechanism','alternative','support','invalidation')
        expected=record['expectation'];choice(expected,'kind',{'survey','market_price','narrative','unknown'})
        require_text(expected,'description')
        if expected['kind']!='unknown':
            require_text(expected,'instrument','horizon');source_refs(expected.get('source_ids'),ids)
        if timestamp(record['test_start_at'])>timestamp(record['deadline']):raise ValueError('test_start_at must not exceed deadline')
        if record['stage'] in {'idea','edge_candidate'}:
            require_text(record.get('trade',{}),'instrument','why_now','catalyst','horizon','risk_limit','exit','implementation','cost_assessment')
        if 'event' in record: validate_event(record['event'],cutoff,sources)
    elif kind=='review':
        if record.get('hypothesis_id') not in hypotheses: raise ValueError('Unknown or cross-market hypothesis')
        if cutoff<timestamp(hypotheses[record['hypothesis_id']]['recorded_at']):raise ValueError('Review cutoff precedes hypothesis registration')
        for key in ['direction','mechanism']: choice(record,key,{'supported','weakened','undecidable'})
        choice(record,'status',{'open','closed'});require_text(record,'rationale')
        performance=record['performance'];choice(performance,'status',{'unavailable','verified'})
        if performance['status']=='unavailable': require_text(performance,'reason')
        else:
            if not hypotheses[record['hypothesis_id']]['prospective']:raise ValueError('Retrospective hypothesis performance cannot be prospective verification')
            require_text(performance,'basis','unit','benchmark_name','cost_basis')
            source_refs(performance.get('source_ids'),ids)
            start=timestamp(performance['start_at']);end=timestamp(performance['end_at'])
            if not timestamp(hypotheses[record['hypothesis_id']]['recorded_at']) <= start < end <= cutoff:
                raise ValueError('Performance interval must follow hypothesis and precede cutoff')
            for key in ['gross','costs','net','benchmark']:finite(performance.get(key))
            if performance['costs']<0 or not math.isclose(performance['gross']-performance['costs'],performance['net'],abs_tol=1e-9):
                raise ValueError('Net performance must subtract known nonnegative costs')
    else:
        questions=record.get('central_questions')
        if not isinstance(questions,list) or not 1<=len(questions)<=2 or not all(isinstance(q,str) and q.strip() for q in questions): raise ValueError('One or two central questions required')
        candidates=record.get('candidate_ids');reviews=record.get('reviewed_ids')
        if not isinstance(candidates,list) or len(candidates)>2 or len(set(candidates))!=len(candidates) or any(i not in hypotheses for i in candidates): raise ValueError('Invalid candidate_ids')
        if any(hypotheses[i]['report_date']!=record['report_date'] for i in candidates):raise ValueError('Candidate belongs to another cycle date')
        if set(candidates)!={hid for hid,h in hypotheses.items() if h['report_date']==record['report_date']}:raise ValueError('Cycle must include every same-date hypothesis')
        if not candidates:require_text(record,'no_candidate_reason')
        valid_reviews={p['id']:p for p in prior if p['type']=='review' and p['market']==record['market']}
        if not isinstance(reviews,list) or len(set(reviews))!=len(reviews) or any(i not in valid_reviews for i in reviews): raise ValueError('Invalid reviewed_ids')
        for rid in reviews:
            r=valid_reviews[rid]
            latest=next(v for v in reversed(prior) if v['type']=='review' and v['hypothesis_id']==r['hypothesis_id'])
            if r['report_date']!=record['report_date'] or latest['id']!=rid:raise ValueError('Stale cycle review')
        same_day_latest={}
        for rid,r in valid_reviews.items():
            if r['report_date']==record['report_date']:same_day_latest[r['hypothesis_id']]=rid
        if set(reviews)!=set(same_day_latest.values()):raise ValueError('Cycle must include latest same-date reviews including closed failures')
        unresolved=record.get('unresolved',[])
        if not isinstance(unresolved,list):raise ValueError('unresolved must be a list')
        for item in unresolved:
            if item.get('hypothesis_id') not in hypotheses:raise ValueError('Unknown unresolved hypothesis')
            require_text(item,'reason')
        addressed={valid_reviews[i]['hypothesis_id'] for i in reviews}|{i['hypothesis_id'] for i in unresolved}
        for hid,hyp in hypotheses.items():
            latest=next((r for r in reversed(prior) if r['type']=='review' and r['hypothesis_id']==hid),None)
            if (latest is None or latest['status']=='open') and hid not in addressed and hid not in candidates:
                raise ValueError(f'Open hypothesis needs review or unresolved reason: {hid}')


def _read_records_unlocked(root):
    root=Path(root);path=root/'ledger.jsonl'
    if not path.exists():return []
    records=[];previous='';seen=set()
    try:
        for line in path.read_text(encoding='utf-8').splitlines():
            record=json.loads(line)
            if record['id'] in seen:raise ValueError('Duplicate id in ledger')
            if record['previous_hash']!=previous or digest({k:v for k,v in record.items() if k!='hash'})!=record['hash']: raise ValueError('Ledger hash chain mismatch')
            validate(record,records)
            if record['type']=='hypothesis' and record['prospective']!=(timestamp(record['recorded_at'])<timestamp(record['test_start_at'])<=timestamp(record['deadline'])):raise ValueError('Invalid prospective flag')
            for source in record['sources']:
                expected=f"evidence/{source['sha256']}"
                if source['snapshot']!=expected or hashlib.sha256((root/expected).read_bytes()).hexdigest()!=source['sha256']:raise ValueError('Evidence snapshot mismatch')
            previous=record['hash'];seen.add(record['id']);records.append(record)
    except (OSError,KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError(f'Malformed research ledger: {exc}') from exc
    return records


def read_records(root):
    root=Path(root)
    if not root.exists():return []
    with (root/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_SH)
        return _read_records_unlocked(root)


def append_record(root,payload,now=None):
    root=Path(root)
    if AUTO.intersection(payload):raise ValueError('Automatic fields cannot be supplied')
    fingerprint=deepcopy(payload);evidence=[]
    try:
        for source in fingerprint['sources']:
            if {'snapshot','sha256'}.intersection(source):raise ValueError('Snapshot fields are automatic')
            data=Path(source.pop('path')).read_bytes();evidence.append(data)
            source['sha256']=hashlib.sha256(data).hexdigest()
    except (KeyError,OSError,TypeError) as exc:raise ValueError(f'Cannot read evidence: {exc}') from exc
    input_hash=digest(fingerprint);root.mkdir(parents=True,exist_ok=True)
    with (root/'.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        prior=_read_records_unlocked(root)
        for existing in prior:
            if existing['id']==payload.get('id'):
                if existing['input_hash']==input_hash:return existing
                raise ValueError('ID already used with different input')
        record=deepcopy(payload)
        record['recorded_at']=timestamp(now or datetime.now(timezone.utc)).isoformat()
        try:validate(record,prior)
        except (KeyError,TypeError) as exc:raise ValueError(f'Missing or malformed field: {exc}') from exc
        if record['type']=='hypothesis':record['prospective']=timestamp(record['recorded_at'])<timestamp(record['test_start_at'])<=timestamp(record['deadline'])
        for source,data in zip(record['sources'],evidence):
            source.pop('path')
            sha=hashlib.sha256(data).hexdigest();relative=f'evidence/{sha}';destination=root/relative
            destination.parent.mkdir(exist_ok=True)
            if destination.exists() and destination.read_bytes()!=data:raise ValueError('Existing evidence corrupted')
            if not destination.exists():
                with destination.open('xb') as stream:
                    stream.write(data);stream.flush()
                    os.fsync(stream.fileno())
            source.update(sha256=sha,snapshot=relative)
        record.update(previous_hash=prior[-1]['hash'] if prior else '',input_hash=input_hash)
        record['hash']=digest(record)
        with (root/'ledger.jsonl').open('a',encoding='utf-8') as stream:
            stream.write(canonical(record).decode()+'\n');stream.flush()
            os.fsync(stream.fileno())
        return record


def summarize(root,market,start,end,as_of):
    if market not in {'us','kr'}:raise ValueError('Invalid market')
    start_date=date.fromisoformat(start);end_date=date.fromisoformat(end);cutoff=timestamp(as_of)
    if start_date>end_date or end_date>cutoff.date():raise ValueError('Invalid summary interval')
    records=[r for r in read_records(root) if r['market']==market and timestamp(r['recorded_at'])<=cutoff]
    rows=[]
    for h in records:
        if h['type']!='hypothesis':continue
        reviews=[r for r in records if r['type']=='review' and r['hypothesis_id']==h['id']]
        latest=reviews[-1] if reviews else None;status=latest['status'] if latest else 'open'
        created=timestamp(h['recorded_at']).date()
        in_cohort=start_date<=created<=end_date
        reviewed=any(start_date<=timestamp(r['recorded_at']).date()<=end_date for r in reviews)
        if created>end_date or not (in_cohort or reviewed or status=='open'):continue
        row={key:h[key] for key in ['id','title','stage','report_date','recorded_at','deadline','prospective','execution_status']}
        row.update(status=status,overdue=status=='open' and timestamp(h['deadline'])<=cutoff,
                   direction=latest['direction'] if latest else 'not_reviewed',mechanism=latest['mechanism'] if latest else 'not_reviewed',
                   performance=latest['performance'] if latest else {'status':'unavailable','reason':'Not reviewed'},latest_review_id=latest['id'] if latest else None)
        rows.append(row)
    return dict(market=market,start=start,end=end,as_of=cutoff.isoformat(),counts=dict(total=len(rows),prospective=sum(r['prospective'] for r in rows),retrospective=sum(not r['prospective'] for r in rows),open=sum(r['status']=='open' for r in rows),overdue=sum(r['overdue'] for r in rows)),hypotheses=rows,cycles=[r for r in records if r['type']=='cycle' and start<=r['report_date']<=end])
