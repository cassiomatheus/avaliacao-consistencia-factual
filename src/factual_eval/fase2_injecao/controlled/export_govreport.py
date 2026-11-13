"""Export an indexed GovReport slice as local doc_id/report/summary JSONL.

IMPORTANT: verify index ↔ summary sentence identifiers against your Fase1 snapshot.
No network requests are performed until the user invokes this script.
"""
import argparse
import json
from pathlib import Path


def main():
    a=argparse.ArgumentParser(description=__doc__)
    a.add_argument('--split',default='test',choices=['train','validation','test'])
    a.add_argument('--offset',type=int,default=0)
    a.add_argument('--limit',type=int,default=5)
    a.add_argument('--output',required=True,type=Path)
    args=a.parse_args()
    if args.offset<0 or args.limit<1: a.error('offset >= 0 and limit >= 1 are required')
    try:
        from datasets import load_dataset
    except ImportError as e:
        raise SystemExit('Install datasets in your local environment to export GovReport') from e
    dataset=load_dataset('ccdv/govreport-summarization',split=args.split,streaming=True)
    out=[]
    for n,example in enumerate(dataset):
        if n<args.offset:continue
        if n>=args.offset+args.limit:break
        if not example.get('report') or not example.get('summary'):
            raise ValueError(f'GovReport item {n} missing report/summary')
        out.append({'doc_id':f'govreport_{args.split}_{n:05d}',
                    'source_index':n,'dataset':'ccdv/govreport-summarization',
                    'split':args.split,'report':example['report'],'summary':example['summary']})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:
        for row in out:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(f'Exported {len(out)} documents to {args.output}. Verify sentence text against your Phase 1 inputs.')

if __name__=='__main__':main()
