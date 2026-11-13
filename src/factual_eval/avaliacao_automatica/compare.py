"""Read-only diagnosis against a frozen reference; exact alignment abstains on ambiguity."""
import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path


def load(path):
    p=Path(path)
    if p.suffix=='.parquet':
        import pandas as pd
        return pd.read_parquet(p).to_dict('records')
    return [json.loads(l) for l in p.read_text(encoding='utf-8').splitlines() if l.strip()]

def norm(text):return ' '.join(str(text).split())
def unique(rows,key):
    found={}
    for row in rows:
        k=key(row)
        if k in found:raise ValueError('Duplicate identity: '+str(k))
        found[k]=row
    return found

def compare(references,predictions,injections=(),retrieval=(),semantic=None):
    from .alignment import align_many
    from .evidence import evidence_comparison
    from factual_eval.fase1_referencia.workspace import fingerprint
    refs=unique(references,lambda r:r['reference_claim_id'])
    for ref in refs.values():
        if ref.get('reference_status')!='VALIDATED' or ref.get('claim_validation_status')!='HUMAN_VALIDATED':raise ValueError('Use frozen Phase 1 references')
    changed=unique(injections,lambda r:(r['document_id'],r['reference_claim_id'],r.get('error_category')))
    for r in injections:
        if r['reference_claim_id'] not in refs or not r.get('modified_claim_en'):raise ValueError('Injection is not linked to a validated original claim')
    found=unique(predictions,lambda r:r['claim_id'])
    if any(p.get('status_factual_nli') not in {'SUPPORTED','CONTRADICTED','NOT_SUPPORTED'} for p in predictions):raise ValueError('Invalid predicted NLI status')
    retrieved=unique(retrieval,lambda r:r['claim_id'])
    variants=sorted({r.get('tipo_resumo',r.get('variant','original')) for r in predictions})
    expected=[]
    for variant in variants:
        for rid,ref in refs.items():
            if not any(p.get('doc_id')==ref['doc_id'] and p.get('tipo_resumo',p.get('variant','original'))==variant for p in predictions):continue
            mutation=changed.get((ref['doc_id'],rid,variant))
            expected.append({'reference':ref,'variant':variant,'mutation':mutation,
                'text':mutation['modified_claim_en'] if mutation else ref['claim_en']})
    key=lambda did,variant,text:(did,variant,norm(text))
    expected_groups={}
    for e in expected:expected_groups.setdefault(key(e['reference']['doc_id'],e['variant'],e['text']),[]).append(e)
    predicted_groups={}
    for p in predictions:predicted_groups.setdefault(key(p['doc_id'],p.get('tipo_resumo',p.get('variant','original')),p.get('claim',p.get('claim_original',''))),[]).append(p)
    results=[];used=set()
    alignments={}
    for doc_id,variant in {(e['reference']['doc_id'],e['variant']) for e in expected}:
        targets={str(i):e['text'] for i,e in enumerate(expected) if e['reference']['doc_id']==doc_id and e['variant']==variant}
        candidates=[p for p in predictions if p['doc_id']==doc_id and p.get('tipo_resumo',p.get('variant','original'))==variant]
        alignments.update(align_many(targets,candidates,semantic))
    for expected_index,e in enumerate(expected):
        ref=e['reference'];mutation=e['mutation'];k=key(ref['doc_id'],e['variant'],e['text']);matches=predicted_groups.get(k,[])
        record={'reference_claim_id':ref['reference_claim_id'],'doc_id':ref['doc_id'],'variant':e['variant'],
                'expected_claim_en':e['text'],'original_factual_label':ref['claim_label'],
                'alignment_method':'exact_whitespace','is_modified':bool(mutation)}
        alignment=alignments[str(expected_index)]
        record['alignment_state']=alignment['status']
        if alignment['status']=='AMBIGUOUS':
            record.update(alignment_status='AMBIGUOUS',diagnosis='ALIGNMENT_AMBIGUOUS');results.append(record);continue
        if alignment['status']=='MATCHED' and len(alignment['claim_ids'])>1:
            used.update(alignment['claim_ids'])
            grouped=[retrieved[pid] for pid in alignment['claim_ids'] if pid in retrieved]
            comparison=evidence_comparison(ref,grouped) if len(grouped)==len(alignment['claim_ids']) else {'status':'NOT_EVALUABLE','success_at_k':None}
            record.update(alignment_status='ALIGNED',alignment_method=alignment['method'],evaluated_claim_ids=alignment['claim_ids'],
                          nli_comparison='UNSCORABLE_MULTI_CLAIM_DECISION',diagnosis='COMPOSITIONAL_ALIGNMENT_NO_NLI_AGGREGATION',
                          evidence_status=comparison['status'],success_at_k=comparison['success_at_k'])
            results.append(record);continue
        if not matches and alignment['status']=='MATCHED' and len(alignment['claim_ids'])==1:
            matches=[found[alignment['claim_ids'][0]]]
            record['alignment_method']=alignment['method']
        if not matches:
            record['alignment_state']=alignment['status']
            record.update(alignment_status='UNMATCHED',diagnosis='EXTRACTION_OR_ALIGNMENT_UNRESOLVED');results.append(record);continue
        if len(matches)!=1 or len(expected_groups[k])!=1:
            record.update(alignment_status='AMBIGUOUS',diagnosis='ALIGNMENT_AMBIGUOUS');results.append(record);continue
        p=matches[0];used.add(p['claim_id']);record.update(alignment_status='ALIGNED',evaluated_claim_id=p['claim_id'],predicted_nli=p['status_factual_nli'])
        # Window anchor IDs are not sufficient evidence sets and are not equated
        # to Phase 1 sentence IDs. Compare complete source evidence text instead.
        evidence=ref.get('evidences',[]);sets=ref.get('known_sufficient_evidence_sets',[])
        passages=None
        if p['claim_id'] in retrieved:
            r=retrieved[p['claim_id']];passages=[x['text'] for field in ['top_sentences','top_paragraphs'] for x in r.get(field,[])]
        if passages is None:record['evidence_comparison']='NOT_MEASURED_NO_RETRIEVAL'
        elif not sets:record['evidence_comparison']='NOT_APPLICABLE_NO_POSITIVE_REFERENCE_SET'
        else:
            comparison=evidence_comparison(ref,[retrieved[p['claim_id']]])
            record['evidence_status']=comparison['status']
            record['success_at_k']=comparison['success_at_k']
            covered=set(comparison.get('covered_evidence_ids',[]))
            known_complete=comparison['success_at_k'] is True
            record.update(covered_reference_evidence_ids=sorted(covered),known_sufficient_set_recovered=known_complete,
                evidence_comparison='KNOWN_SUFFICIENT_SET_RECOVERED' if known_complete else 'NO_KNOWN_SUFFICIENT_SET_RECOVERED')
        if mutation:
            record.update(expected_type=mutation.get('expected_inconsistency_type',mutation.get('error_category')),
                          expected_nli_hypothesis=mutation.get('expected_relation'),nli_comparison='UNSCORABLE_EXPECTED_LABEL_UNVALIDATED',
                          diagnosis='EXPECTED_RELATION_REQUIRES_VALID_DERIVATION')
            decision=mutation.get('human_review',{})
            validated=(mutation.get('validation_provenance')=='HUMAN_PREAPPROVED_EDIT'
                       and mutation.get('expected_label_is_validated') is True
                       and mutation.get('protocol_version')=='integrated-human-v1'
                       and mutation.get('reference_fingerprint')==fingerprint(ref)
                       and decision.get('status')=='APPROVED' and decision.get('evidence_relation_confirmed') is True
                       and bool(decision.get('reviewed_by'))
                       and mutation.get('expected_relation') in {'SUPPORTED','CONTRADICTED','NOT_SUPPORTED'})
            if validated:
                expected_label=mutation['expected_relation']
                record.update(expected_nli=expected_label,validation_provenance='HUMAN_PREAPPROVED_EDIT',
                    nli_comparison='MATCH' if p['status_factual_nli']==expected_label else 'MISMATCH',diagnosis='VERIFIED_EDIT_COMPARISON')
        else:
            record.update(expected_nli=ref['claim_label'],nli_comparison='MATCH' if p['status_factual_nli']==ref['claim_label'] else 'MISMATCH',
                diagnosis='REFERENCE_AGREEMENT' if p['status_factual_nli']==ref['claim_label'] else 'NLI_DISAGREEMENT_WITH_ORIGINAL_REFERENCE')
        results.append(record)
    extras=[{'evaluated_claim_id':p['claim_id'],'doc_id':p['doc_id'],'alignment_status':'UNALIGNED_PREDICTION',
             'diagnosis':'CLAIM_NOT_ALIGNED_TO_REFERENCE'} for p in predictions if p['claim_id'] not in used]
    # Duplicate/ambiguous claims are diagnostics, not automatically false positives.
    from .metrics import classification
    metrics=classification([{**r,'predicted_nli':r.get('predicted_nli'),
                              'evaluable':r.get('nli_comparison') in {'MATCH','MISMATCH'},
                              'is_control':not r['is_modified']} for r in results])
    return {'records':results,'unaligned_predictions':extras,
            'summary':{'reference_comparisons':len(results),'evaluated_claims':len(predictions),
                       'nli_metrics':metrics,
                       'alignment_counts':dict(Counter(r['alignment_status'] for r in results)),
                       'nli_counts':dict(Counter(r.get('nli_comparison','NOT_MEASURED') for r in results)),
                       'note':'No semantic-equivalence assumption for unmatched claims. Missing known evidence sets do not invalidate alternative evidence.'}}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',required=True,type=Path);p.add_argument('--nli',required=True,type=Path)
    p.add_argument('--injections',type=Path);p.add_argument('--retrieval',type=Path);p.add_argument('--output',required=True,type=Path)
    p.add_argument('--semantic-alignment',action='store_true')
    a=p.parse_args()
    if a.output.exists():p.error('Use a new output directory')
    scorer=None
    if a.semantic_alignment:
        from .alignment import ModelEquivalence
        from factual_eval.config import load_config
        scorer=ModelEquivalence(load_config())
    result=compare(load(a.reference),load(a.nli),load(a.injections) if a.injections else [],load(a.retrieval) if a.retrieval else [],semantic=scorer)
    a.output.mkdir(parents=True)
    for name,records in [('diagnostics.jsonl',result['records']),('unaligned_predictions.jsonl',result['unaligned_predictions'])]:
        (a.output/name).write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records),encoding='utf-8')
    inputs={name:sha256(path.read_bytes()).hexdigest() for name,path in [('reference',a.reference),('nli',a.nli),('injections',a.injections),('retrieval',a.retrieval)] if path}
    (a.output/'report.json').write_text(json.dumps({**result['summary'],'input_sha256':inputs},ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['summary'],ensure_ascii=False,indent=2))
