"""Conservative alignment: lexical identity, compositional identity, semantic confirmation.

Semantic thresholds are fixed protocol parameters, never tuned on test outcomes.
Embeddings only retrieve candidates; bidirectional entailment and entity/number
compatibility are required for a semantic match. They remain model-based evidence.
"""
import re

PROTOCOL = {'version':'alignment-v1', 'cosine_min':0.82, 'entailment_min':0.95,
            'note':'Fixed development defaults; model-based matches require separate aligner validation.'}


def norm(text):
    return ' '.join(str(text).split())


def anchors_compatible(a,b):
    numbers=lambda t:sorted(re.findall(r'\b\d+(?:[.,]\d+)*\b',t))
    acronyms=lambda t:sorted(re.findall(r'\b[A-Z]{2,}\b',t))
    neg=lambda t:bool(re.search(r"\b(?:not|no|never|neither|without|cannot)\b|n't\b",t,re.I))
    return numbers(a)==numbers(b) and acronyms(a)==acronyms(b) and neg(a)==neg(b)


def align(target, candidates, semantic=None, extraction_complete=False):
    """semantic(text, texts) returns cosine, forward entailment, reverse entailment.

    Target IDs are not passed to the scorer, and equal occurrence IDs do not prove
    equality after re-extraction. Unresolved matches explicitly abstain.
    """
    text=norm(target)
    exact=[c for c in candidates if norm(c['claim'])==text]
    if exact:
        return {'status':'MATCHED' if len(exact)==1 else 'AMBIGUOUS', 'method':'exact_whitespace',
                'claim_ids':[c['claim_id'] for c in exact] if len(exact)==1 else []}
    atoms=[norm(t) for t in re.split(r'(?<=[.!?])\s+',text)]
    if len(atoms)>1:
        groups=[[c for c in candidates if norm(c['claim'])==part] for part in atoms]
        ids=[g[0]['claim_id'] for g in groups if len(g)==1]
        if all(len(g)==1 for g in groups) and len(set(ids))==len(atoms):
            return {'status':'MATCHED','method':'compositional_exact','claim_ids':ids}
        if ids:
            return {'status':'PARTIAL_MATCH','method':'partial_compositional','claim_ids':ids}
    if not candidates:
        return {'status':'OMITTED' if extraction_complete else 'NOT_EVALUABLE','method':'no_candidates','claim_ids':[]}
    if semantic is None:
        return {'status':'NOT_EVALUABLE','method':'semantic_confirmation_unavailable','claim_ids':[]}
    scores=semantic(text,[c['claim'] for c in candidates])
    if len(scores)!=len(candidates):
        raise ValueError('Alignment scorer changed candidate count')
    confirmed=[];plausible=[]
    for c,score in zip(candidates,scores):
        cosine,forward,reverse=score
        if cosine>=PROTOCOL['cosine_min']:
            plausible.append(c['claim_id'])
            compatible=anchors_compatible(text,c['claim']) and (not hasattr(semantic,'compatible') or semantic.compatible(text,c['claim']))
            if compatible and min(forward,reverse)>=PROTOCOL['entailment_min']:
                confirmed.append(c['claim_id'])
    if len(confirmed)==1:
        return {'status':'MATCHED','method':'bidirectional_entailment_with_anchor_guards','claim_ids':confirmed,
                'confirmation_provenance':'MODEL_BASED_EQUIVALENCE','protocol':PROTOCOL}
    return {'status':'AMBIGUOUS' if len(confirmed)>1 or plausible else 'NOT_EVALUABLE',
            'method':'semantic_abstention','claim_ids':[],'protocol':PROTOCOL}


class ModelEquivalence:
    def __init__(self,config,device='auto'):
        from sentence_transformers import SentenceTransformer
        import spacy
        from factual_eval.fase3_pipeline.nli.model import NLIAligner
        from factual_eval.config import device_for
        self.embedding=SentenceTransformer(config['retrieval']['embedding_model'],
            revision=config['retrieval']['embedding_revision'],device='cpu')
        opts=dict(config['nli']);opts={k:opts[k] for k in ('model_name','revision','batch_size','max_length')}
        # Keep the confirmation model off the experiment GPU (12 GB target).
        opts['device']='cpu'
        self.nli=NLIAligner(**opts)
        self.nlp=spacy.load(config['claims']['spacy_model'])

    def compatible(self,a,b):
        signature=lambda text:sorted((e.label_,e.text) for e in self.nlp(text).ents)
        return signature(a)==signature(b)

    def __call__(self,text,texts):
        import numpy as np
        vectors=self.embedding.encode([text]+texts,normalize_embeddings=True)
        cosine=(vectors[1:]@vectors[0]).tolist()
        output=[]
        for i,t in enumerate(texts):
            e,_,_=self.nli.process_batch([(text,t),(t,text)],disable_prog_bar=True)
            output.append((float(cosine[i]),float(e[0]),float(e[1])))
        return output


def align_many(targets,candidates,semantic=None,extraction_complete=False):
    """Resolve the cohort jointly: a prediction cannot silently satisfy two targets."""
    from collections import Counter
    results={key:align(text,candidates,semantic,extraction_complete) for key,text in targets.items()}
    counts=Counter(pid for result in results.values() if result['status']=='MATCHED' for pid in result['claim_ids'])
    for result in results.values():
        if result['status']=='MATCHED' and any(counts[pid]>1 for pid in result['claim_ids']):
            result.update(status='AMBIGUOUS',method='shared_prediction_conflict',claim_ids=[])
    return results


def evaluate_aligner(cases,scorer=None):
    results=[]
    for case in cases:
        result=align(case['target'],case['candidates'],scorer,case.get('extraction_complete',False))
        expected=case['expected_status']
        results.append({'case_id':case['case_id'],'expected_status':expected,**result,
                        'correct_status':result['status']==expected,
                        'correct_match':set(result['claim_ids'])==set(case.get('expected_claim_ids',[])) if expected=='MATCHED' else None})
    n=len(results);abstain=sum(r['status'] in {'AMBIGUOUS','NOT_EVALUABLE'} for r in results)
    return {'protocol':PROTOCOL,'cases':n,'coverage':(n-abstain)/n if n else None,
            'abstention_rate':abstain/n if n else None,'correct_status':sum(r['correct_status'] for r in results),
            'validated_matches':sum(r['correct_match'] is True for r in results), 'results':results}
