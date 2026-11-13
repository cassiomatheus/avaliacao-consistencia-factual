"""Sentence-level applicability and conservative proposals for the integrated UI."""
from .controlled.engine import generate_for_reference, text_occurrences

ENTITY_LABELS = {'ORG', 'PERSON', 'GPE', 'LOC', 'FAC', 'PRODUCT', 'NORP'}


def analyze_and_suggest(ref, source, *, nlp=None, coref_resolver=None, model_errors=None, seed=42):
    model_errors = model_errors or {}
    sentence = ref['summary_sentence_en']
    claim = ref['claim_en']
    parsed = nlp(sentence) if nlp else None
    entities = [e.text for e in parsed.ents if e.label_ in ENTITY_LABELS
                and len(text_occurrences(claim, e.text)) == 1] if parsed is not None else []
    mentions = [t.text for t in parsed if t.pos_ == 'PRON' or
                t.pos_ == 'NOUN' and t.i > 0 and parsed[t.i-1].lower_ in
                {'the', 'these', 'those', 'this', 'that', 'their', 'its'}] if parsed is not None else []
    results, proposals = {}, []
    for category, strategies in [('entity', ['entity']), ('predicate', ['negation', 'antonym']),
                                  ('coreference', ['coreference'])]:
        row = {'status': 'NO_SAFE_SUGGESTION', 'targets': [], 'proposal_ids': []}
        results[category] = row
        if category in {'entity', 'coreference'} and parsed is None:
            row.update(status='UNAVAILABLE', reason='A análise linguística não está disponível.',
                       detail=model_errors.get('nlp', 'Parser ausente'))
            continue
        if category == 'entity':
            row['targets'] = entities
            if not entities:
                row.update(status='NOT_APPLICABLE', reason='Não foi identificada uma entidade nomeada na sentença que também esteja nesta afirmação.')
                continue
        if category == 'coreference':
            row['targets'] = mentions
            if not mentions:
                row.update(status='NOT_APPLICABLE', reason='Não foi identificada uma expressão referencial compatível com o gerador nesta sentença.')
                continue
            if coref_resolver is None:
                row.update(status='UNAVAILABLE', reason='É necessário confirmar os antecedentes no contexto antes de propor uma troca.',
                           detail=model_errors.get('coreference', 'Resolvedor contextual ausente'))
                continue
        try:
            pairs, reasons = generate_for_reference(ref, source, strategies=strategies,
                nlp=nlp, coref_resolver=coref_resolver, seed=seed, max_per_claim=1)
            if pairs:
                proposals.extend(pairs)
                row.update(status='SUGGESTED', proposal_ids=[p['injection_id'] for p in pairs],
                           reason='Há uma alteração candidata para você conferir na sentença e nas evidências.')
            else:
                row.update(reason={'entity': 'Foi identificada uma entidade, mas não uma substituição compatível e segura no documento.',
                    'predicate': 'As regras atuais não encontraram uma alteração de ação, relação ou negação com segurança.',
                    'coreference': 'Há expressão referencial, mas não foi confirmada uma troca para um antecedente incorreto.'}[category],
                    checks=reasons)
        except Exception as exc:
            row.update(status='UNAVAILABLE', reason='Não foi possível concluir a análise deste tipo.', detail=str(exc))
    return proposals, results
