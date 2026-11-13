#!/usr/bin/env python3
"""Prepare phase-2 candidate records from Factual Injector UI review and its EXACT retrieval JSONL.

Only carries forward annotations. Does NOT assert claim-level entailment or evidence sufficiency.
Requires no external Python packages.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path

SUPPORTED = 'Apoio (Support)'
CONTRADICTED = 'Contradição (Contradiction)'


def read_jsonl(path):
    with open(path, encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ValueError(f'Invalid JSONL {path}:{line_no}: {exc}') from exc


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def prepare(reviews_file, retrieval_file):
    review = json.loads(Path(reviews_file).read_text(encoding='utf-8'))
    expected_hash = review.get('dataset_id')
    actual_hash = sha256_file(retrieval_file)
    if expected_hash != actual_hash:
        raise ValueError('SHA-256 does not match: reviews belong to a different retrieval JSONL. '
                         f'expected={expected_hash}, actual={actual_hash}. '
                         'Use the original retrieval_ready.jsonl that produced the review export.')
    entries = {}
    for item in read_jsonl(retrieval_file):
        sentence_id = item.get('summary_sentence_id')
        if not sentence_id or sentence_id in entries:
            raise ValueError(f'Missing or duplicated summary_sentence_id: {sentence_id}')
        entries[sentence_id] = item
    candidates = []
    audit = {'reviewed_sentences': len(review.get('reviews', {})), 'completed_sentences': 0,
             'sentences_with_support': 0, 'supported_links': 0, 'contradicted_links': 0,
             'missing_evidence_ids': [], 'completed_without_support': []}
    for sentence_id, decision in review.get('reviews', {}).items():
        if decision.get('status') != 'completed':
            continue
        audit['completed_sentences'] += 1
        record = entries.get(sentence_id)
        if record is None:
            raise ValueError(f'No retrieval entry for reviewed sentence: {sentence_id}')
        evidence_lookup = {}
        for ev in record.get('retrieved_top_k', []):
            e_id = ev.get('doc_sent_id')
            if e_id in evidence_lookup:
                raise ValueError(f'Duplicated passage ID {e_id} in {sentence_id}')
            evidence_lookup[e_id] = ev
        supported = []
        contradictions = []
        for evidence_id, label in decision.get('labels', {}).items():
            if evidence_id not in evidence_lookup:
                audit['missing_evidence_ids'].append(f'{sentence_id}:{evidence_id}')
                continue
            ev = evidence_lookup[evidence_id]
            ev_out = {
                'evidence_id': evidence_id,
                'text_en': ev.get('text_en'), 'text_pt': ev.get('text_pt'),
                'source_sentence_ids': ev.get('source_sentence_ids'),
                'start_index': ev.get('start_index'), 'end_index': ev.get('end_index'),
                'annotation_label': label,
            }
            if not ev_out['text_en']:
                raise ValueError(f'Missing evidence English text for {sentence_id}:{evidence_id}')
            if label == SUPPORTED:
                supported.append(ev_out)
            elif label in (CONTRADICTED, 'Contradição'):
                contradictions.append(ev_out)
        audit['supported_links'] += len(supported)
        audit['contradicted_links'] += len(contradictions)
        if not supported:
            audit['completed_without_support'].append(sentence_id)
            continue
        audit['sentences_with_support'] += 1
        if not record.get('summary_sentence_en'):
            raise ValueError(f'Missing English summary sentence text: {sentence_id}')
        candidates.append({
            'schema_version': 'phase2_candidate_v1',
            'doc_id': record.get('doc_id'), 'summary_sentence_id': sentence_id,
            'summary_sentence_en': record['summary_sentence_en'],
            'summary_sentence_pt': record.get('summary_sentence_pt'),
            'supporting_passages_reviewed': supported,
            'contradicting_passages_reviewed': contradictions,
            'review_status': decision['status'],
            'reference_granularity': 'SENTENCE_LEVEL',
            'claim_level_sufficiency': 'NOT_ASSESSED',
            'eligible_for_validated_gold': False,
            'source_review_dataset_sha256': expected_hash,
            'notes': decision.get('notes', ''),
        })
    if audit['missing_evidence_ids']:
        raise ValueError('Reviewer labels refer to passage IDs not present in retrieval file: '
                         + ', '.join(audit['missing_evidence_ids'][:10]))
    return candidates, audit


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reviews', required=True, type=Path)
    ap.add_argument('--retrieval', required=True, type=Path)
    ap.add_argument('--out', required=True, type=Path)
    ap.add_argument('--audit', type=Path, default=None)
    args = ap.parse_args()
    candidates, audit = prepare(args.reviews, args.retrieval)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open('x', encoding='utf-8') as f:
        for row in candidates:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    audit_path = args.audit or args.out.with_suffix('.audit.json')
    with audit_path.open('x', encoding='utf-8') as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f'Prepared {len(candidates)} candidates. Saved {args.out}; audit at {audit_path}')


if __name__ == '__main__':
    main()
