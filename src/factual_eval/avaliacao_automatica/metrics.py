"""Explicit denominators and document-cluster bootstrap, without fabricated metrics."""
from collections import Counter
import random

CLASSES=('SUPPORTED','CONTRADICTED','NOT_SUPPORTED')


def classification(rows):
    valid=[r for r in rows if r.get('expected_nli') in CLASSES and r.get('predicted_nli') in CLASSES and r.get('evaluable') is True]
    matrix={a:{b:0 for b in CLASSES} for a in CLASSES}
    for r in valid:matrix[r['expected_nli']][r['predicted_nli']]+=1
    scores={}
    for c in CLASSES:
        tp=matrix[c][c];fp=sum(matrix[a][c] for a in CLASSES if a!=c);fn=sum(matrix[c][a] for a in CLASSES if a!=c)
        scores[c]={'precision':tp/(tp+fp) if tp+fp else None,'recall':tp/(tp+fn) if tp+fn else None,
                   'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,'support':sum(matrix[c].values())}
    return {'evaluated':len(valid),'total':len(rows),'abstentions':len(rows)-len(valid),'confusion_matrix':matrix,
            'per_class':scores,'macro_f1':sum(s['f1'] or 0 for s in scores.values())/3 if valid else None,
            'macro_f1_policy':'Fixed three classes; undefined class F1 contributes zero, individual scores remain null.',
            'verified_contradiction_recall':scores['CONTRADICTED']['recall'],
            'false_alert_rate_verified_supported_controls':sum(r['predicted_nli']=='CONTRADICTED' for r in valid if r.get('is_control') and r['expected_nli']=='SUPPORTED')/sum(bool(r.get('is_control')) and r['expected_nli']=='SUPPORTED' for r in valid) if any(r.get('is_control') and r['expected_nli']=='SUPPORTED' for r in valid) else None}


def summarize(rows):
    measured=[r['success_at_k'] for r in rows if r.get('success_at_k') is not None]
    return {**classification(rows),'success_at_k':sum(measured)/len(measured) if measured else None,
            'success_at_k_denominator':len(measured),'alignment_counts':dict(Counter(r.get('alignment_status','NOT_EVALUABLE') for r in rows))}


def cluster_bootstrap(rows,seed=42,repeats=1000):
    docs=sorted({r['doc_id'] for r in rows})
    if len(docs)<10:
        return {'status':'NOT_EVALUABLE','documents':len(docs),'reason':'Fewer than 10 document clusters; no interpretable confidence interval reported.'}
    rng=random.Random(seed);values=[]
    groups={d:[r for r in rows if r['doc_id']==d] for d in docs}
    for _ in range(repeats):
        sample=[r for d in rng.choices(docs,k=len(docs)) for r in groups[d]]
        value=classification(sample)['macro_f1']
        if value is not None:values.append(value)
    if not values:return {'status':'NOT_EVALUABLE','reason':'No evaluable labels'}
    values.sort()
    return {'status':'OBSERVED','unit':'document','seed':seed,'repeats':repeats,'documents':len(docs),
            'macro_f1_percentile_95':[values[int(.025*(len(values)-1))],values[int(.975*(len(values)-1))]]}


def validate_split(assignments):
    seen={};source_splits={}
    for r in assignments:
        if r['split'] not in {'development','test'}:raise ValueError('Unknown experimental split')
        if r['doc_id'] in seen and seen[r['doc_id']]!=r['split']:raise ValueError('Document leakage between development and test')
        if r.get('source_hash'):
            if r['source_hash'] in source_splits and source_splits[r['source_hash']]!=r['split']:
                raise ValueError('Document source leakage between development and test')
            source_splits[r['source_hash']]=r['split']
        seen[r['doc_id']]=r['split']
    return seen
