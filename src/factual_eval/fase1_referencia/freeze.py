"""Freeze an original-only human reference, sufficient evidence sets and exact spans."""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from factual_eval.schemas import document_id


def rows(path):return [json.loads(l) for l in Path(path).read_text(encoding='utf-8').splitlines() if l.strip()]
def hash_text(text):return sha256(text.encode()).hexdigest()
def hash_file(path):return sha256(Path(path).read_bytes()).hexdigest()
def write(path,records):path.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')


def exact_occurrence(text,fragment):
    # Recover the actual raw span even when the extractor normalized whitespace.
    pattern=r'\s+'.join(re.escape(w) for w in fragment.split())
    found=list(re.finditer(pattern,text)) if pattern else []
    if len(found)!=1:raise ValueError('Origin sentence must have exactly one occurrence in the original summary')
    return found[0].span()


def freeze(gold_path,frame_path,source_path,output):
    gold=rows(gold_path);frame=Path(frame_path);output=Path(output)
    if output.exists():raise FileExistsError('Use a new reference output directory')
    if not gold:raise ValueError('No validated human claims')
    original_claims={r['claim_id']:r for r in rows(frame/'claims.jsonl')}
    sentences={r['sentence_id']:r for r in rows(frame/'sentencas.jsonl')}
    documents={r['doc_id']:r for r in rows(frame/'documentos.jsonl')}
    sources={}
    for i,source in enumerate(rows(source_path)):
        did=document_id(source.get('source_index',i),source['report'])
        if did in sources:raise ValueError('Duplicate source document')
        sources[did]={'doc_id':did,'source_index':source.get('source_index',i),'report':source['report'],'summary':source['summary']}
    references=[];seen=set();used_sources={}
    for claim in gold:
        cid=claim['claim_id'];did=claim['doc_id'];raw=original_claims.get(cid)
        if cid in seen:raise ValueError('Duplicate reference claim')
        seen.add(cid)
        if claim.get('variant')!='original' or not raw or raw.get('variant')!='original':raise ValueError('Phase 1 accepts original summaries only')
        if claim.get('full_document_checked') is not True or claim.get('search_complete') is not True:raise ValueError('Incomplete human reference')
        label=claim.get('factual_label')
        if label not in {'SUPPORTED','CONTRADICTED','NOT_SUPPORTED'}:raise ValueError('Invalid human factual label')
        source=sources.get(did);document=documents.get(did)
        if not source or not document or document.get('source_sha256')!=hash_text(source['report']):raise ValueError('Original report snapshot mismatch')
        a,b=exact_occurrence(source['summary'],raw['origin_sentence'])
        sets=claim.get('gold_evidence_sets',[])
        if not isinstance(sets,list) or (label=='NOT_SUPPORTED' and sets) or (label!='NOT_SUPPORTED' and not sets):raise ValueError('Incompatible sufficient evidence sets')
        ids=set();evidences=[]
        for group in sets:
            if not group or len(group)!=len(set(group)):raise ValueError('Empty or repeated evidence set')
            for sid in group:
                sentence=sentences.get(sid)
                if not sentence or sentence['doc_id']!=did:raise ValueError('Foreign or missing source evidence')
                start,end=sentence['char_start'],sentence['char_end']
                if source['report'][start:end]!=sentence['text']:raise ValueError('Evidence offsets mismatch')
                if sid not in ids:
                    ids.add(sid);evidences.append({'evidence_id':sid,'text_en':sentence['text'],
                        'source_span':{'start_char':start,'end_char':end},'source_sentence_ids':[sid]})
        reference={'schema_version':'1.0','reference_status':'VALIDATED','claim_validation_status':'HUMAN_VALIDATED',
            'doc_id':did,'reference_claim_id':cid,'claim_id':cid,'claim_en':claim['claim_original'],
            'claim_label':label,'factual_label':label,'summary_sentence_id':f'{did}:original:SUMCHAR{a}',
            'summary_sentence_en':source['summary'][a:b],'source_summary_span':{'start_char':a,'end_char':b},
            'sentence_coverage_reviewed':False,'evidences':evidences,
            'known_sufficient_evidence_sets':[{'set_id':f'{cid}:E{i+1}','relation':label,'evidence_ids':group,'sufficiency_validated':True} for i,group in enumerate(sets)],
            'source_document_sha256':hash_text(source['report']),'source_summary_sha256':hash_text(source['summary']),
            'reviewed_by':claim.get('reviewed_by',''),'reviewed_at':claim.get('reviewed_at',''),
            'human_notes':claim.get('human_notes',''),'reference_dataset_id':claim['dataset_id']}
        references.append(reference);used_sources[did]=source
    output.mkdir(parents=True)
    write(output/'reference_claims.jsonl',references);write(output/'sources.jsonl',list(used_sources.values()))
    manifest={'schema_version':'frozen_reference_v1','phase':1,'claims':len(references),'documents':len(used_sources),
        'human_validation_scope':'original claims only; no sentence exhaustivity inferred',
        'gold_sha256':hash_file(gold_path),'source_sha256':hash_file(source_path),
        'files':{p.name:hash_file(p) for p in output.iterdir()}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    return output/'reference_claims.jsonl'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--gold',required=True,type=Path);p.add_argument('--frame',required=True,type=Path)
    p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(freeze(a.gold,a.frame,a.source,a.output))
