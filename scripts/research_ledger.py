#!/usr/bin/env python3
"""Create, validate and summarize durable research records."""
import argparse
import json
from pathlib import Path
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.common.research_ledger import append_record, read_records, summarize


def template(kind, market):
    p = dict(id='REPLACE_UNIQUE_ID', type=kind, market=market, report_date='YYYY-MM-DD',
             data_cutoff='YYYY-MM-DDTHH:MM:SS+00:00', sources=[dict(id='source1', path='LOCAL_PUBLIC_EVIDENCE_FILE', provenance='SOURCE_URL_OR_PROVENANCE', published_at='YYYY-MM-DDTHH:MM:SS+00:00', observed_at='YYYY-MM-DDTHH:MM:SS+00:00')])
    if kind == 'hypothesis':
        p.update(stage='insight',title='',question='',expectation={'kind':'unknown','description':''},observation='',our_view='',difference='',mechanism='',alternative='',support='',invalidation='',test_start_at='YYYY-MM-DDTHH:MM:SS+00:00',deadline='YYYY-MM-DDTHH:MM:SS+00:00',execution_status='watch')
    elif kind == 'review':
        p.update(hypothesis_id='',direction='undecidable',mechanism='undecidable',status='open',rationale='',performance={'status':'unavailable','reason':''})
    else:
        p.update(central_questions=[''],candidate_ids=[],reviewed_ids=[],unresolved=[],no_candidate_reason='')
    return p


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    t=commands.add_parser('template');t.add_argument('--kind',choices=['hypothesis','review','cycle'],required=True);t.add_argument('--market',choices=['us','kr'],required=True)
    a=commands.add_parser('append');a.add_argument('--input',type=Path,required=True);a.add_argument('--root',type=Path,required=True)
    v=commands.add_parser('validate');v.add_argument('--root',type=Path,required=True)
    s=commands.add_parser('summary');s.add_argument('--root',type=Path,required=True);s.add_argument('--market',choices=['us','kr'],required=True)
    for key in ['start','end','as-of']:s.add_argument('--'+key,required=True)
    s.add_argument('--out',type=Path)
    args=parser.parse_args(argv)
    try:
        if args.command=='template':result=template(args.kind,args.market)
        elif args.command=='append':result=append_record(args.root,json.loads(args.input.read_text(encoding='utf-8')))
        elif args.command=='validate':result={'valid':True,'records':len(read_records(args.root))}
        else:result=summarize(args.root,args.market,args.start,args.end,args.as_of)
        output=json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n'
        if getattr(args,'out',None):args.out.write_text(output,encoding='utf-8')
        else:print(output,end='')
    except (ValueError,OSError,TypeError) as exc:
        parser.exit(1,f'research ledger: {exc}\n')
    return 0


if __name__=='__main__':raise SystemExit(main())
