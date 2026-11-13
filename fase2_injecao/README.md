# Fase 2 — Injeção controlada

**Claim original validada → claim alterada → atualização da sentença/resumo → registro da inconsistência esperada.**

O caminho canônico usa a referência congelada da Fase 1. Cada versão registra `reference_claim_id`, `original_claim_en`, `modified_claim_en`, edição da claim, edição no resumo, tipo esperado e proveniência. Só claims originalmente `SUPPORTED` com conjuntos suficientes podem ser injetadas. Uma versão por tipo aplicável; as versões partem do original.

```bash
# Este ambiente já possui spaCy e FastCoref. O código é carregado desta nova pasta.
~/factual-injector-ui/.venv/bin/python fase2_injecao/gerar_controlado.py generate --references outputs/fase1_referencia/referencia-001/reference_claims.jsonl --source outputs/fase1_referencia/referencia-001/sources.jsonl --output outputs/fase2_injecao/propostas-001.jsonl --rejected outputs/fase2_injecao/rejeitados-001.jsonl
python fase2_injecao/visualizar_selecao.py --input outputs/fase2_injecao/propostas-001.jsonl --serve --port 8772
```

As regras de predicado e quantidade são locais; entidades usam NER e aliases; correferência exige antecedentes contextuais e confirmação do vínculo modificado pelo resolvedor. O pacote opcional `controlled` declara FastCoref; não atualize as dependências do avaliador só para usar o gerador. O ambiente acima é uma opção existente, não requisito de caminho fixo.

Na interface, selecione as inconsistências por tipo e exporte a seleção. O compositor aplica várias alterações do mesmo tipo em claims diferentes e gera um resumo final por tipo, além dos registros de cada edição.

```bash
python fase2_injecao/import_selected_summaries.py --selection fase2_injecao/selecoes/selecao_inconsistencias.json --proposals outputs/fase2_injecao/propostas-001.jsonl --source outputs/fase1_referencia/referencia-001/sources.jsonl --output fase3_pipeline/entradas/experimento-001.csv
```

O CSV contém apenas fonte e textos. Os metadados ficam em `.manifest.json`; quando a seleção possui vínculo com claims humanas, `.injections.jsonl` registra as expectativas para o módulo de avaliação automática. Esse arquivo não é fornecido aos modelos da Fase 3.

**Expectativa não é gold derivado automaticamente.** A relação pós-injeção permanece hipótese não validada até existir uma derivação factual defensável. O comparador não calcula acurácia NLI desses casos como se a hipótese fosse verdade.

`provisorios/` conserva os lotes antigos baseados em divisão sintática, inclusive as 30 propostas já vistas. Eles continuam utilizáveis em testes exploratórios e não substituem a referência humana por claim. Para a seleção antiga, os caminhos a partir da raiz são `fase2_injecao/provisorios/claim_versions_v62.jsonl` e `fase1_referencia/dados/govreport_source.jsonl`. O gerador V5 em `generate_dataset.py` permanece apenas por compatibilidade histórica.
