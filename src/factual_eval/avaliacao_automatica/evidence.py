"""Evidence coverage by verified source spans, never by window anchor IDs."""
from hashlib import sha256
from .alignment import norm


def evidence_comparison(reference,retrieved,sentence_k=8,window_k=4):
    sets=[s for s in reference.get('known_sufficient_evidence_sets',[]) if s.get('sufficiency_validated') and s.get('evidence_ids')]
    if not sets:
        return {'status':'NOT_EVALUABLE','reason':'NO_POSITIVE_KNOWN_SUFFICIENT_SET','success_at_k':None}
    dictionary={e['evidence_id']:e for e in reference.get('evidences',[])}
    if any(not set(g['evidence_ids'])<=dictionary.keys() for g in sets):
        return {'status':'NOT_EVALUABLE','reason':'INCOMPLETE_REFERENCE_SET','success_at_k':None}
    intervals=[];texts=[];verified_source=None
    for r in retrieved:
        source=r.get('documento_fonte')
        if reference.get('doc_id') and r.get('doc_id') and reference['doc_id'] != r['doc_id']:
            return {'status':'NOT_EVALUABLE','reason':'FOREIGN_DOCUMENT','success_at_k':None}
        if source is not None:
            if verified_source is not None and verified_source != source:
                return {'status':'NOT_EVALUABLE','reason':'MIXED_SOURCE_DOCUMENTS','success_at_k':None}
            verified_source=source
        if source is not None and reference.get('source_document_sha256') and sha256(source.encode()).hexdigest()!=reference['source_document_sha256']:
            return {'status':'NOT_EVALUABLE','reason':'SOURCE_HASH_MISMATCH','success_at_k':None}
        if source is not None:
            for e in dictionary.values():
                span=e.get('source_span',{});a,b=span.get('start_char'),span.get('end_char')
                if a is not None or b is not None:
                    if not (type(a) is int and type(b) is int and 0<=a<b<=len(source)) or norm(source[a:b])!=norm(e['text_en']):
                        return {'status':'NOT_EVALUABLE','reason':'REFERENCE_OFFSET_TEXT_MISMATCH','success_at_k':None}
        for field,k in [('top_sentences',sentence_k),('top_paragraphs',window_k)]:
            for p in list(r.get(field,[]))[:k]:
                a,b=p.get('start_char'),p.get('end_char')
                if source is not None and type(a) is int and type(b) is int:
                    if not 0<=a<b<=len(source) or norm(source[a:b])!=norm(p['text']):
                        return {'status':'NOT_EVALUABLE','reason':'RECOVERED_OFFSET_TEXT_MISMATCH','success_at_k':None}
                    intervals.append((a,b))
                texts.append(norm(p['text']))
    merged=[]
    for a,b in sorted(intervals):
        if merged and (a<=merged[-1][1] or (verified_source is not None and verified_source[merged[-1][1]:a].isspace())):merged[-1]=(merged[-1][0],max(b,merged[-1][1]))
        else:merged.append((a,b))
    covered=[]
    for eid,e in dictionary.items():
        span=e.get('source_span',{});a,b=span.get('start_char'),span.get('end_char')
        if (type(a) is int and type(b) is int and any(x<=a<b<=y for x,y in merged)) or any(norm(e['text_en']) in t for t in texts):
            covered.append(eid)
    complete=[s.get('set_id') for s in sets if set(s['evidence_ids'])<=set(covered)]
    return {'status':'KNOWN_EVIDENCE_SET_FOUND' if complete else ('KNOWN_EVIDENCE_SET_NOT_FOUND' if covered or not texts else 'ALTERNATIVE_EVIDENCE_UNVERIFIED'),
            'success_at_k':bool(complete),'covered_evidence_ids':sorted(covered),'complete_sets':complete,
            'sentence_k':sentence_k,'window_k':window_k,'alternative_evidence_validity':'UNVERIFIED',
            'coverage_note':'Known sufficient sets are not an exhaustive inventory of valid evidence.'}
