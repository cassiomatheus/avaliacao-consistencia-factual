"""Integrated human review contracts. No model prediction can create human gold."""
from copy import deepcopy
from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import uuid

PROTOCOL = 'integrated-human-v1'
LABELS = {'SUPPORTED', 'CONTRADICTED', 'NOT_SUPPORTED', 'INCONCLUSIVE'}
REVIEW_STATES = {'PENDING', 'APPROVED', 'CORRECTED', 'ADDED', 'REJECTED', 'AMBIGUOUS'}


def now():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(value):
    if isinstance(value, dict) and 'claim_validation_status' in value:
        value = {k: value.get(k) for k in ('reference_claim_id', 'claim_en', 'claim_label', 'summary_sentence_en',
            'source_summary_span', 'source_document_sha256', 'source_summary_sha256', 'evidences', 'known_sufficient_evidence_sets')}
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read_rows(path):
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def write_rows(path, rows):
    with Path(path).open('x', encoding='utf-8') as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')


def prepare_dataset(dataset, sources):
    """Attach verified original snapshots; never reconstruct a source from joined sentences."""
    from factual_eval.schemas import document_id
    from .preparation import segment_document
    result = deepcopy(dataset)
    if len({c['claim_id'] for c in result['claims']}) != len(result['claims']) or len({d['doc_id'] for d in result['documents']}) != len(result['documents']):
        raise ValueError('Duplicate frame identities')
    raw_sources = {}
    for i, source in enumerate(sources):
        if type(source.get('source_index', i)) is not int or source.get('source_index', i) < 0:
            raise ValueError('Invalid source index')
        did = document_id(source.get('source_index', i), source['report'])
        if did in raw_sources:
            raise ValueError('Duplicate source document')
        raw_sources[did] = {**source, 'doc_id': did, 'source_index': source.get('source_index', i)}
    attached = {}
    for document in result['documents']:
        did = document['doc_id']
        source = raw_sources.get(did)
        if not source or sha256(source['report'].encode()).hexdigest() != document.get('source_sha256'):
            raise ValueError('Source snapshot missing or mismatched: ' + did)
        for sentence in document['sentences']:
            a, b = sentence['char_start'], sentence['char_end']
            if source['report'][a:b] != sentence['text']:
                raise ValueError('Evidence offsets mismatch')
        document['summary_sentences'] = segment_document(source['summary'], did + ':SUMMARY')
        # Preserve extractor origins even if its sentence segmentation differs.
        for claim in result['claims']:
            if claim['doc_id'] != did or claim.get('variant') != 'original':
                continue
            if claim.get('summary_text') and claim['summary_text'] != source['summary']:
                raise ValueError('Original summary snapshot mismatch')
            fragment = claim.get('origin_sentence', '')
            occurrences = list(re.finditer(re.escape(fragment), source['summary'])) if fragment else []
            if len(occurrences) != 1:
                claim['integrated_anchor_status'] = 'AMBIGUOUS'
                continue
            a, b = occurrences[0].span()
            sentence = next((s for s in document['summary_sentences'] if s['char_start'] == a and s['char_end'] == b), None)
            if sentence is None:
                sentence = {'sentence_id': f'{did}:SUMMARY:SPAN{a}-{b}', 'text': fragment,
                            'char_start': a, 'char_end': b, 'sentence_index': len(document['summary_sentences'])}
                document['summary_sentences'].append(sentence)
            claim['integrated_sentence_id'] = sentence['sentence_id']
        attached[did] = source
    result['integrated_sources'] = attached
    return result


def catalog(dataset, review):
    extension = review.get('integrated') or {}
    edits = extension.get('claims') or {}
    records = {}
    for raw in dataset['claims']:
        if raw.get('variant') != 'original':
            continue
        cid = raw['claim_id']
        records[cid] = {'reference_claim_id': cid, 'doc_id': raw['doc_id'],
            'sentence_id': raw.get('integrated_sentence_id'), 'raw_extracted_claim': raw.get('claim_original', raw.get('claim_text', '')),
            'validated_claim': raw.get('claim_original', raw.get('claim_text', '')), 'claim_review_status': 'PENDING',
            **edits.get(cid, {})}
    for cid, edited in edits.items():
        if cid not in records:
            records[cid] = {'reference_claim_id': cid, 'raw_extracted_claim': None, **edited}
    return records


def validate_extension(dataset, review):
    ext = review.get('integrated')
    if ext is None:
        return
    if not isinstance(ext, dict) or ext.get('protocol_version') != PROTOCOL:
        raise ValueError('Unsupported integrated protocol')
    if not isinstance(ext.get('claims', {}), dict) or not isinstance(ext.get('sentences', {}), dict) or not isinstance(ext.get('perturbations', {}), dict):
        raise ValueError('Malformed integrated review')
    sentences = {s['sentence_id']: (d['doc_id'], s) for d in dataset['documents'] for s in d.get('summary_sentences', [])}
    raw = {c['claim_id']: c for c in dataset['claims']}
    for cid, c in ext.get('claims', {}).items():
        if not isinstance(c, dict) or c.get('claim_review_status') not in REVIEW_STATES:
            raise ValueError('Invalid claim review status')
        if c.get('reference_claim_id', cid) != cid:
            raise ValueError('Claim identity mismatch')
        if c.get('doc_id') not in dataset.get('integrated_sources', {}):
            raise ValueError('Unknown claim source')
        sid = c.get('sentence_id')
        if sid not in sentences or sentences[sid][0] != c['doc_id']:
            raise ValueError('Foreign summary sentence')
        if not isinstance(c.get('validated_claim'), str) or not c['validated_claim'].strip():
            raise ValueError('Empty reviewed claim')
        if cid in raw and (raw[cid]['doc_id'] != c['doc_id'] or raw[cid].get('integrated_sentence_id') != sid):
            raise ValueError('Extractor identity/anchor cannot be changed')
        if cid in raw and c.get('raw_extracted_claim') != raw[cid].get('claim_original', raw[cid].get('claim_text', '')):
            raise ValueError('Raw extractor output cannot be changed')
        if cid not in raw and (not cid.startswith(c['doc_id'] + ':H') or c.get('raw_extracted_claim') is not None):
            raise ValueError('Added claim must have a human ID and preserve empty extractor origin')
        if review.get('claims', {}).get(cid, {}).get('factual_label', '') not in LABELS | {'', 'UNCERTAIN'}:
            raise ValueError('Unknown factual label')
    for sid, annotation in ext.get('sentences', {}).items():
        if sid not in sentences or not isinstance(annotation, dict):
            raise ValueError('Unknown sentence coverage')
        if type(annotation.get('coverage_reviewed', False)) is not bool or type(annotation.get('selected', True)) is not bool:
            raise ValueError('Invalid sentence coverage flags')
    claims = catalog(dataset, review)
    for iid, proposal in ext.get('perturbations', {}).items():
        if not isinstance(iid,str) or re.fullmatch(r'I_[0-9a-f]{16,64}',iid) is None:
            raise ValueError('Invalid perturbation ID')
        if not isinstance(proposal, dict) or proposal.get('injection_id') != iid or proposal.get('reference_claim_id') not in claims:
            raise ValueError('Invalid perturbation identity')
        from factual_eval.fase2_injecao.controlled.engine import validate_pair
        errors = validate_pair(proposal)
        if errors:
            raise ValueError('Invalid perturbation: ' + str(errors))
        claim = claims[proposal['reference_claim_id']]
        source = dataset['integrated_sources'][claim['doc_id']]
        if proposal.get('document_id') != claim['doc_id'] or proposal.get('original_summary_en') != source['summary']:
            raise ValueError('Perturbation source mismatch')
        edit = proposal['edit']
        ce = proposal.get('claim_edit', {})
        original_claim = proposal.get('original_claim_en', '')
        a, b = ce.get('start_char'), ce.get('end_char')
        if not (type(a) is int and type(b) is int and 0 <= a < b <= len(original_claim)):
            raise ValueError('Invalid claim edit offsets')
        if original_claim[a:b] != edit['original'] or ce.get('original') != edit['original'] or ce.get('replacement') != edit['replacement'] or original_claim[:a] + edit['replacement'] + original_claim[b:] != proposal.get('modified_claim_en'):
            raise ValueError('Claim edit does not describe modified claim')
        sentence = proposal.get('original_sentence_en', '')
        occurrences = list(re.finditer(re.escape(sentence), source['summary'])) if sentence else []
        if len(occurrences) != 1:
            raise ValueError('Perturbation sentence anchor ambiguous')
        start, end = occurrences[0].span()
        if not start <= edit['start_char'] < edit['end_char'] <= end:
            raise ValueError('Edit outside original sentence')
        modified_sentence = sentence[:edit['start_char']-start] + edit['replacement'] + sentence[edit['end_char']-start:]
        if modified_sentence != proposal.get('modified_sentence_en'):
            raise ValueError('Modified full sentence mismatch')
        decision = proposal.get('human_review') or {}
        if decision.get('status', 'PENDING') not in {'PENDING', 'APPROVED', 'REJECTED', 'INCONCLUSIVE'}:
            raise ValueError('Invalid perturbation decision')
        if decision.get('status') == 'APPROVED':
            if decision.get('expected_relation') not in LABELS - {'INCONCLUSIVE'} or decision.get('evidence_relation_confirmed') is not True or not decision.get('reviewed_by'):
                raise ValueError('Approval requires reviewer and factual evidence confirmation')
        # Neither imported metadata nor an NLI output may claim human provenance.
        if proposal.get('expected_label_is_validated') or proposal.get('gold_eligible'):
            raise ValueError('Proposal metadata cannot create validated labels')


def reference_record(dataset, review, claim):
    cid, did = claim['reference_claim_id'], claim['doc_id']
    annotation = review.get('claims', {}).get(cid, {})
    if review.get('draft_sets', {}).get(cid):
        raise ValueError('Unfinished evidence selection')
    if claim['claim_review_status'] not in {'APPROVED', 'CORRECTED', 'ADDED'}:
        raise ValueError('Claim not approved')
    if not review.get('reviewer', '').strip():
        raise ValueError('Reviewer required')
    if annotation.get('review_status') != 'FINALIZADO' or annotation.get('claim_valid') != 'SIM' or annotation.get('full_document_checked') is not True or annotation.get('search_complete') is not True:
        raise ValueError('Incomplete claim validation')
    label = annotation.get('factual_label')
    if label not in LABELS - {'INCONCLUSIVE'}:
        raise ValueError('Claim factual decision is inconclusive')
    doc = next(d for d in dataset['documents'] if d['doc_id'] == did)
    sentence = next(s for s in doc['summary_sentences'] if s['sentence_id'] == claim['sentence_id'])
    source = dataset['integrated_sources'][did]
    sa, sb = sentence['char_start'], sentence['char_end']
    if not (type(sa) is int and type(sb) is int and 0 <= sa < sb <= len(source['summary'])) or source['summary'][sa:sb] != sentence['text']:
        raise ValueError('Summary sentence offsets mismatch')
    dictionary = {s['sentence_id']: s for s in doc['sentences']}
    sets = annotation.get('gold_evidence_sets', [])
    if not isinstance(sets, list) or (label == 'NOT_SUPPORTED' and sets) or (label != 'NOT_SUPPORTED' and not sets):
        raise ValueError('Incompatible sufficient evidence sets')
    seen, evidences, clean_sets = set(), [], []
    for group in sets:
        if not isinstance(group, list) or not group or len(group) != len(set(group)) or any(s not in dictionary for s in group):
            raise ValueError('Invalid evidence set')
        canonical = sorted(group)
        if canonical in clean_sets:
            raise ValueError('Duplicate evidence set')
        clean_sets.append(canonical)
        for sid in group:
            s = dictionary[sid]
            a, b = s['char_start'], s['char_end']
            if not (type(a) is int and type(b) is int and 0 <= a < b <= len(source['report'])) or source['report'][a:b] != s['text']:
                raise ValueError('Evidence offsets mismatch')
            if sid not in seen:
                seen.add(sid)
                evidences.append({'evidence_id': sid, 'text_en': s['text'], 'source_sentence_ids': [sid], 'source_span': {'start_char': a, 'end_char': b}})
    return {'schema_version': '1.0', 'reference_status': 'VALIDATED', 'claim_validation_status': 'HUMAN_VALIDATED',
        'validation_provenance': 'HUMAN_VERIFIED', 'protocol_version': PROTOCOL,
        'reference_claim_id': cid, 'claim_id': cid, 'doc_id': did, 'claim_en': claim['validated_claim'],
        'raw_extracted_claim': claim['raw_extracted_claim'], 'claim_review_status': claim['claim_review_status'],
        'claim_label': label, 'factual_label': label, 'summary_sentence_id': sentence['sentence_id'],
        'summary_sentence_en': sentence['text'], 'source_summary_span': {'start_char': sentence['char_start'], 'end_char': sentence['char_end']},
        'sentence_coverage_reviewed': (review['integrated'].get('sentences', {}).get(sentence['sentence_id']) or {}).get('coverage_reviewed', False),
        'annotation_scope': 'SELECTED_SENTENCES', 'evidence_search_status': 'COMPLETE',
        'source_document_sha256': sha256(source['report'].encode()).hexdigest(),
        'source_summary_sha256': sha256(source['summary'].encode()).hexdigest(), 'evidences': evidences,
        'known_sufficient_evidence_sets': [{'set_id': f'{cid}:E{i+1}', 'evidence_ids': g, 'relation': label, 'sufficiency_validated': True} for i, g in enumerate(clean_sets)],
        'created_at': claim.get('created_at', annotation.get('updated_utc', '')),
        'reviewed_by': review['reviewer'], 'reviewed_at': annotation.get('updated_utc', ''), 'reference_dataset_id': review['dataset_id']}


def blockers(dataset, review):
    claims = catalog(dataset, review)
    issues, references = [], []
    for claim in claims.values():
        if claim.get('sentence_id') is None:
            issues.append({'id': claim['reference_claim_id'], 'reason': 'UNRESOLVED_SUMMARY_ANCHOR'})
    ext = review.get('integrated') or {}
    for d in dataset['documents']:
        for s in d.get('summary_sentences', []):
            a = ext.get('sentences', {}).get(s['sentence_id'], {})
            if not a.get('selected', True):
                continue
            if not a.get('coverage_reviewed'):
                issues.append({'id': s['sentence_id'], 'reason': 'COVERAGE_NOT_REVIEWED'})
            members = [c for c in claims.values() if c['sentence_id'] == s['sentence_id']]
            if a.get('no_factual_information') and any(c['claim_review_status'] != 'REJECTED' for c in members):
                issues.append({'id':s['sentence_id'],'reason':'NONFACTUAL_SENTENCE_HAS_ACTIVE_CLAIMS'})
            texts = [' '.join(c['validated_claim'].split()) for c in members if c['claim_review_status'] in {'APPROVED','CORRECTED','ADDED'}]
            if len(set(texts)) != len(texts):
                issues.append({'id':s['sentence_id'],'reason':'DUPLICATE_CLAIMS_IN_SENTENCE'})
            if not members and not a.get('no_factual_information'):
                issues.append({'id': s['sentence_id'], 'reason': 'NO_CLAIMS_OR_NONFACTUAL_CONFIRMATION'})
            for c in members:
                if c['claim_review_status'] == 'REJECTED':
                    if not review.get('claims', {}).get(c['reference_claim_id'], {}).get('notes', '').strip():
                        issues.append({'id': c['reference_claim_id'], 'reason': 'REJECTION_REQUIRES_NOTE'})
                    continue
                try:
                    references.append(reference_record(dataset, review, c))
                except (ValueError, KeyError) as exc:
                    issues.append({'id': c['reference_claim_id'], 'reason': str(exc)})
    for iid, p in ext.get('perturbations', {}).items():
        decision = p.get('human_review', {})
        if decision.get('status', 'PENDING') in {'PENDING', 'INCONCLUSIVE'}:
            issues.append({'id': iid, 'reason': 'PERTURBATION_NOT_RESOLVED'})
        if decision.get('status') == 'APPROVED':
            ref = next((r for r in references if r['reference_claim_id'] == p['reference_claim_id']), None)
            if not ref or p.get('reference_fingerprint') != fingerprint(ref):
                issues.append({'id': iid, 'reason': 'STALE_OR_OUT_OF_SCOPE_APPROVAL'})
    if not references:
        issues.append({'id': 'workspace', 'reason': 'NO_VALIDATED_CLAIMS'})
    return issues, references


def progress(dataset, review):
    issues, references = blockers(dataset, review)
    claims = catalog(dataset, review)
    documents = []
    for d in dataset['documents']:
        items = [c for c in claims.values() if c['doc_id'] == d['doc_id']]
        edits = [p for p in (review.get('integrated') or {}).get('perturbations', {}).values() if p['document_id'] == d['doc_id']]
        documents.append({'doc_id': d['doc_id'], 'summary_sentences': len(d.get('summary_sentences', [])),
            'claims': len(items), 'reviewed': sum(c['claim_review_status'] != 'PENDING' for c in items),
            'validated': sum(r['doc_id'] == d['doc_id'] for r in references),
            'perturbations': dict(Counter(p.get('human_review', {}).get('status', 'PENDING') for p in edits))})
    return {'documents': documents, 'blockers': issues, 'can_freeze': not issues}


def freeze_workspace(dataset, review, output):
    validate_extension(dataset, review)
    issues, references = blockers(dataset, review)
    if issues:
        raise ValueError('Freeze blocked: ' + json.dumps(issues, ensure_ascii=False))
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    approved = []
    for proposal in review['integrated'].get('perturbations', {}).values():
        decision = proposal.get('human_review', {})
        if decision.get('status') != 'APPROVED':
            continue
        approved.append({**proposal, 'expected_relation': decision['expected_relation'],
            'expected_label_is_validated': True, 'human_validated_modified_relation': True,
            'expected_relation_status': 'HUMAN_PREAPPROVED_EDIT',
            'validation_status': 'HUMAN_PREAPPROVED_EDIT', 'validation_provenance': 'HUMAN_PREAPPROVED_EDIT',
            'validation_evidence_ids': [e['evidence_id'] for r in references if r['reference_claim_id'] == proposal['reference_claim_id'] for e in r['evidences']],
            'validation_evidence_sets': next(r for r in references if r['reference_claim_id'] == proposal['reference_claim_id'])['known_sufficient_evidence_sets'],
            'protocol_version': PROTOCOL})
    used = {r['doc_id'] for r in references}
    write_rows(output / 'reference_claims.jsonl', references)
    write_rows(output / 'sources.jsonl', [s for did, s in dataset['integrated_sources'].items() if did in used])
    write_rows(output / 'approved_perturbations.jsonl', approved)
    (output / 'review.json').write_text(json.dumps(review, ensure_ascii=False, indent=2))
    manifest = {'schema_version': 'integrated-frozen-v1', 'protocol_version': PROTOCOL, 'created_at': now(),
        'claims': len(references), 'approved_perturbations': len(approved), 'dataset_id': review['dataset_id'],
        'perturbation_decisions': dict(Counter(p.get('human_review',{}).get('status','PENDING') for p in review['integrated'].get('perturbations',{}).values())),
        'annotation_scope': 'SELECTED_SENTENCES', 'files': {p.name: sha256(p.read_bytes()).hexdigest() for p in output.iterdir()}}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return output


def verify_snapshot(path):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if Path(name).name != name or sha256((path / name).read_bytes()).hexdigest() != digest:
            raise ValueError('Frozen snapshot integrity mismatch')
    return manifest
