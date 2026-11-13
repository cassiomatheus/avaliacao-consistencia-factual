# Fase 3 — Pipeline avaliado

**Resumo modificado → extração de claims → recuperação de evidências → NLI.**

```bash
conda activate nlp_mestrado
python fase3_pipeline/run_pipeline.py --input fase3_pipeline/entradas/selecao_v63_20261111.csv --all-docs --device cuda:0
```

O comando canônico termina em NLI, salva em `outputs/fase3_pipeline/` e rejeita `--from-stage generate` e `--until-stage taxonomy`. A taxonomia e a avaliação da qualidade ficam fora do pipeline avaliado, em `avaliacao_automatica/`.

O pipeline não recebe a referência congelada, conjuntos gold, registros de injeção, respostas esperadas nem IDs de claims originais como pistas para os modelos. Extrai novas claims das versões completas. O original pode acompanhar os modificados como controle, sem assumir que todo resumo original seja factualmente perfeito.

A entrada antiga disponível em `entradas/` contém o original, cinco alterações de entidade e uma de predicado. É um teste provisório do fluxo anterior: não é referência gold. Nenhum modelo foi reexecutado na reorganização.

## Recuperação com RRF

A recuperação combina rankings semânticos e BM25 por Reciprocal Rank Fusion, com `retrieval.rrf_k: 60`. Cada lista usa posições a partir de 1 e contribui `1 / (k + posição)`; candidatos ausentes contribuem zero. Consultas duplicadas são removidas. Sentenças e janelas são processadas separadamente.

O RRF ordena a união completa dos pools antes do cross-encoder. O cross-encoder continua responsável pela ordem final e usa RRF para desempates. Os resultados registram `rrf_score`, `rrf_ranks`, `rrf_k` e `fusion_method`. O campo legado `retrieval_score` permanece como sinal de qualidade para o NLI e não ordena os candidatos.

Consulte a [explicação e os limites no README principal](../README.md#como-a-fase-3-usa-rrf). Execute uma nova condição para comparar com resultados anteriores; esta mudança não reprocessa os Parquets existentes.
