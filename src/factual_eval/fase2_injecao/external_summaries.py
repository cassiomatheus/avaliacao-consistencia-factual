"""Import V6 manual selections without exposing edit metadata to the models."""
import argparse
import csv
from hashlib import sha256
import json
from pathlib import Path

COLUMNS={'predicate':'resumo_predicado','entity':'resumo_entity','coreference':'resumo_corref'}


def digest(path):return sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def compose(rows,source,category):
    original=source['summary'];report=source['report'];claims=set();edits=[]
    for row in rows:
        if row['document_id']!=source['doc_id'] or row['error_category']!=category:raise ValueError('Mixed documents/categories')
        if row['original_summary_en']!=original:raise ValueError('Original summary does not match source snapshot')
        expected=row.get('generator',{}).get('source_sha256')
        if expected and expected!=sha256(report.encode()).hexdigest():raise ValueError('Source report SHA-256 mismatch')
        claim=row.get('claim_id') or row.get('reference_claim_id') or row.get('summary_sentence_id')
        if not claim or claim in claims:raise ValueError('Select only one edit per claim and category')
        claims.add(claim);e=row['edit'];a,b=e['start_char'],e['end_char']
        if type(a)!=int or type(b)!=int or not 0<=a<b<=len(original):raise ValueError('Invalid original offsets')
        if original[a:b]!=e['original']:raise ValueError('Edit does not match original text')
        if not isinstance(e['replacement'],str) or e['original']==e['replacement']:raise ValueError('Invalid replacement')
        if original[:a]+e['replacement']+original[b:]!=row['modified_summary_en']:raise ValueError('Proposal has undescribed changes')
        if any(a<p['end_char'] and p['start_char']<b for p in row.get('other_claim_token_spans',[])):raise ValueError('Edit affects another claim')
        spans=row.get('claim_token_spans',[])
        if spans and any(not original[i].isspace() and not any(p['start_char']<=i<p['end_char'] for p in spans) for i in range(a,b)):raise ValueError('Edit extends outside target claim')
        edits.append({'injection_id':row['injection_id'],'claim_id':claim,**e})
    edits.sort(key=lambda e:e['start_char'])
    if any(e['start_char']<edits[i-1]['end_char'] for i,e in enumerate(edits) if i):raise ValueError('Overlapping edits')
    if category=='coreference':
        for row in rows:
            trace=row.get('transformation_trace',{})
            for other in rows:
                if other is row:continue
                for key in ('original_antecedent','wrong_antecedent'):
                    span=trace.get(key);e=other['edit']
                    if span and e['start_char']<span['end_char'] and span['start_char']<e['end_char']:raise ValueError('Selection rewrites another coreference antecedent')
    result=original
    for e in reversed(edits):result=result[:e['start_char']]+e['replacement']+result[e['end_char']:]
    return result,edits


def prepare(selection_path,proposals_path,source_path):
    selection=json.loads(Path(selection_path).read_text(encoding='utf-8'))
    if selection.get('schema_version')!='summary_selection_v1':raise ValueError('Use Exportar seleção (.json) from the composer')
    if selection.get('dataset_id')!=digest(proposals_path):raise ValueError('Selection belongs to a different proposals JSONL (SHA-256 mismatch)')
    ids=selection.get('selected_injection_ids')
    if not isinstance(ids,list) or not ids or any(not isinstance(i,str) for i in ids) or len(ids)!=len(set(ids)):raise ValueError('Empty, invalid or duplicated selection')
    proposals=read_jsonl(proposals_path);lookup={r['injection_id']:r for r in proposals}
    if len(lookup)!=len(proposals):raise ValueError('Duplicate proposal IDs')
    if any(i not in lookup for i in ids):raise ValueError('Unknown selected proposal')
    document=selection['document_id'];selected=[lookup[i] for i in ids if lookup[i]['document_id']==document]
    if not selected:raise ValueError('No selected proposals for the active document')
    sources=read_jsonl(source_path)
    if len({s['doc_id'] for s in sources})!=len(sources):raise ValueError('Duplicate source documents')
    source=next((s for s in sources if s['doc_id']==document),None)
    if not source or not source.get('report') or not source.get('summary'):raise ValueError('Original report and full summary are required')
    index=source.get('source_index',0)
    if type(index)!=int or index<0:raise ValueError('source_index must be a nonnegative integer')
    output={'source_index':index,'external_doc_id':document,'fonte':source['report'],
            'resumo_original':source['summary'],'resumo_entity':'','resumo_predicado':'','resumo_corref':''}
    metadata=[]
    for category in COLUMNS:
        chosen=[r for r in selected if r['error_category']==category]
        if not chosen:continue
        summary,edits=compose(chosen,source,category);output[COLUMNS[category]]=summary
        metadata.append({'category':category,'column':COLUMNS[category],'inconsistency_count':len(edits),'edits':edits})
    if sum(m['inconsistency_count'] for m in metadata)!=len(selected):raise ValueError('Unknown inconsistency category')
    manifest={'schema_version':'external_summary_import_v1','external_document_id':document,
              'source_document_sha256':sha256(source['report'].encode()).hexdigest(),
              'selection_sha256':digest(selection_path),'proposals_sha256':digest(proposals_path),
              'source_file_sha256':digest(source_path),'source_index':index,
              'included_variants':['original']+[m['category'] for m in metadata],
              'variants':metadata,'selected_other_documents_not_imported':len(ids)-len(selected),
              'selected_proposal_expectations':[{'document_id':r['document_id'],'reference_claim_id':r.get('reference_claim_id'),'error_category':r['error_category'],'modified_claim_en':r.get('modified_claim_en'),'expected_relation':r.get('expected_relation'),'expected_label_is_validated':False,'injection_id':r['injection_id']} for r in selected],
              'is_gold':False,'label_policy':'Edit metadata are separate from evaluator text. Legacy gabarito_injetado remains none; it is not a human label.'}
    return output,manifest


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--selection',required=True,type=Path)
    p.add_argument('--proposals',required=True,type=Path)
    p.add_argument('--source',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    args=p.parse_args(argv);manifest_path=args.output.with_suffix('.manifest.json');expectations_path=args.output.with_suffix('.injections.jsonl')
    if args.output.suffix.lower()!='.csv':p.error('--output must have .csv extension')
    if args.output.exists() or manifest_path.exists() or expectations_path.exists():p.error('Output already exists; use a new --output')
    row,manifest=prepare(args.selection,args.proposals,args.source)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(row));writer.writeheader();writer.writerow(row)
    manifest['csv_sha256']=digest(args.output)
    expectations=manifest['selected_proposal_expectations']
    if all(r.get('reference_claim_id') and r.get('modified_claim_en') for r in expectations):
        expectations_path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in expectations),encoding='utf-8')
        manifest['expectations_path']=str(expectations_path)
        manifest['expectations_sha256']=digest(expectations_path)
    with manifest_path.open('x',encoding='utf-8') as f:json.dump(manifest,f,ensure_ascii=False,indent=2)
    print(json.dumps({'input_csv':str(args.output),'metadata':str(manifest_path),'documents':1,
                      'variants':manifest['included_variants'],
                      'inconsistencies':{m['category']:m['inconsistency_count'] for m in manifest['variants']}},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
