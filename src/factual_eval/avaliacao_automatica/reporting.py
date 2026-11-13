"""Reproducible scientific reports with explicit unavailable/abstention states."""
import csv
import json
from pathlib import Path
from .metrics import summarize, cluster_bootstrap


def csv_rows(path,rows):
    fields=list(dict.fromkeys(k for r in rows for k in r)) or ['status']
    with Path(path).open('x',newline='',encoding='utf-8') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def report(rows,output,metadata=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    conditions=sorted({r['condition'] for r in rows})
    summary={c:summarize([r for r in rows if r['condition']==c]) for c in conditions}
    statistics={c:cluster_bootstrap([r for r in rows if r['condition']==c]) for c in conditions}
    data={'status':'OBSERVED','metadata':metadata or {},'conditions':summary,
          'documents':len({r['doc_id'] for r in rows}),
          'reference_claims':len({r['reference_claim_id'] for r in rows}),
          'limitations':['Incomplete human evidence coverage: absence of a known set does not invalidate alternatives.',
                         'Semantic matching is model-based and must be evaluated separately on known alignments.',
                         'Interventions diagnose interacting components, not exclusive causal attribution.'],
          'metric_unit':'reference target per case and condition; statistical unit is document'}
    if (metadata or {}).get('quality_claims_allowed') is False:
        data['status']='SYNTHETIC_SMOKE_ONLY'
    (output/'experiment_summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
    (output/'statistical_summary.json').write_text(json.dumps(statistics,ensure_ascii=False,indent=2))
    for name in ['claims_alignment.csv','evidence_comparison.csv','nli_evaluation.csv','error_diagnostics.csv']:
        csv_rows(output/name,rows)
    for key,name in [('doc_id','metrics_by_document.csv'),('error_type','metrics_by_error_type.csv'),('position_bin','metrics_by_position.csv')]:
        groups=[]
        for condition in conditions:
            for group in sorted({str(r.get(key,'UNKNOWN')) for r in rows}):
                group_rows=[r for r in rows if r['condition']==condition and str(r.get(key,'UNKNOWN'))==group]
                if group_rows:groups.append({'condition':condition,key:group,**summarize(group_rows)})
        csv_rows(output/name,groups)
    lines=['# Relatório experimental', '', '## Resultado observado', '',
        f"Documentos: {data['documents']}. Claims-alvo de referência: {data['reference_claims']}.",
        'Denominador: cada claim-alvo, caso e condição. As repetições do mesmo documento não são observações estatísticas independentes.', '',
        '| Condição | Casos | NLI avaliáveis | Abstenções | Success@K | Denominador Success@K | Macro-F1 |',
        '| --- | --- | --- | --- | --- | --- | --- |']
    if (metadata or {}).get('quality_claims_allowed') is False:
        data['status']='SYNTHETIC_SMOKE_ONLY'
        lines.insert(2,'**Teste sintético de integração. Os rótulos simulam anotação para exercitar o protocolo; não são validação humana de dados da pesquisa nem estimativa da qualidade factual dos modelos.**\n')
    for c,s in summary.items():lines.append(f"| {c} | {s['total']} | {s['evaluated']} | {s['abstentions']} | {s['success_at_k']} | {s['success_at_k_denominator']} | {s['macro_f1']} |")
    lines.extend(['', '## Resultado validado', '',
        'Somente rótulos de referência congelados e alterações com relação factual pré-aprovada pelo humano são pontuados. A qualidade das anotações depende da revisão humana.', '',
        '## Hipótese', '', 'Diferenças entre E0–E3 podem ajudar a localizar falhas. Não demonstram atribuições causais exclusivas.', '',
        '## Limitações metodológicas', '', *['- '+x for x in data['limitations']],
        '- Intervalos de confiança usam bootstrap por documento com seed fixa. Com menos de dez documentos, permanecem indisponíveis.',
        '- Evidências de referência são fornecidas como conjuntos concatenados e identificados; não como trechos contíguos fictícios.',
        '- Success@K é medido nas condições de recuperação automática. Condições de evidência fornecida têm esse indicador indisponível.', '',
        'Veja [resumo JSON](./experiment_summary.json), [diagnósticos](./error_diagnostics.csv) e [estatística](./statistical_summary.json).'])
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return data
