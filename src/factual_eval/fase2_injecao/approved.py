"""Materialize frozen preapproved minimal pairs without labels in model inputs."""
import argparse
import csv
import json
import re
from pathlib import Path
from hashlib import sha256
from factual_eval.fase1_referencia.workspace import read_rows, write_rows, verify_snapshot, fingerprint
from .controlled.engine import validate_pair


def materialize(snapshot, output):
    snapshot, output = Path(snapshot), Path(output)
    verify_snapshot(snapshot)
    references = {r['reference_claim_id']: r for r in read_rows(snapshot/'reference_claims.jsonl')}
    sources = {r['doc_id']: r for r in read_rows(snapshot/'sources.jsonl')}
    approved = read_rows(snapshot/'approved_perturbations.jsonl')
    if len({r['injection_id'] for r in approved}) != len(approved):
        raise ValueError('Duplicate approved perturbation')
    output.mkdir(parents=True, exist_ok=False)
    cases = []
    fields = ['source_index', 'fonte', 'resumo_original', 'resumo_entity', 'resumo_predicado', 'resumo_corref']
    columns = {'entity': 'resumo_entity', 'predicate': 'resumo_predicado', 'coreference': 'resumo_corref'}
    def publish(case_id, source, text, variant, injection=None):
        path = output/(case_id+'.csv')
        row = dict.fromkeys(fields, '')
        row.update(source_index=source['source_index'], fonte=source['report'])
        row['resumo_original' if variant == 'original' else columns[variant]] = text
        if '[ERROR_' in text:
            raise ValueError('Error marker leaked')
        with path.open('x', newline='', encoding='utf-8') as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader(); writer.writerow(row)
        cases.append({'case_id': case_id, 'doc_id': source['doc_id'], 'variant': variant,
                      'input_csv': path.name, 'input_sha256': sha256(path.read_bytes()).hexdigest(),
                      'injection': injection})
    for did, source in sources.items():
        publish('original_'+sha256(did.encode()).hexdigest()[:12], source, source['summary'], 'original')
    for p in approved:
        if re.fullmatch(r'I_[0-9a-f]{16,64}',p.get('injection_id','')) is None:
            raise ValueError('Unsafe perturbation ID')
        ref = references.get(p['reference_claim_id'])
        source = sources.get(p['document_id'])
        if not ref or not source or p.get('reference_fingerprint') != fingerprint(ref):
            raise ValueError('Stale preapproval')
        if p.get('validation_provenance') != 'HUMAN_PREAPPROVED_EDIT' or not p.get('expected_label_is_validated'):
            raise ValueError('Unvalidated edit')
        if p['expected_relation'] not in {'SUPPORTED', 'CONTRADICTED', 'NOT_SUPPORTED'}:
            raise ValueError('Unvalidated relation')
        if source['summary'] != p['original_summary_en'] or validate_pair(p):
            raise ValueError('Invalid approved minimal pair')
        # One isolated intervention per case prevents overlapping/context interactions.
        publish(p['injection_id'], source, p['modified_summary_en'], p['error_category'], p)
    write_rows(output/'cases.jsonl', cases)
    (output/'manifest.json').write_text(json.dumps({'schema_version':'approved-cases-v1',
        'snapshot_sha256':sha256((snapshot/'manifest.json').read_bytes()).hexdigest(),
        'cases':len(cases), 'policy':'One approved localized edit per modified full summary; metadata excluded from CSV.'}, indent=2))
    return cases


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();print(json.dumps(materialize(a.snapshot,a.output),ensure_ascii=False,indent=2))
