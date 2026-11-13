# Módulo de avaliação automática

**Alinhamento de claims → comparação de evidências → comparação NLI → diagnóstico.** Este módulo lê os resultados; não interfere na extração, recuperação ou NLI.

```bash
python avaliacao_automatica/comparar_referencia.py --reference outputs/fase1_referencia/referencia-001/reference_claims.jsonl --nli outputs/fase3_pipeline/EXECUCAO/nli/nli.parquet --retrieval outputs/fase3_pipeline/EXECUCAO/retrieval/retrieval.parquet --injections fase3_pipeline/entradas/experimento-001.injections.jsonl --output outputs/avaliacao_automatica/comparacao-001
```

Substitua `EXECUCAO` pelo diretório informado pela Fase 3. A referência e as expectativas só entram neste momento.

Implementação inicial:

- Alinha por texto exato após normalização de espaços, preservando a caixa das entidades. Duplicatas geram `AMBIGUOUS`; paráfrases sem correspondência geram `UNMATCHED`. Não atribui equivalência semântica por adivinhação.
- Verifica se as passagens recuperadas contêm todos os membros de pelo menos um conjunto suficiente conhecido. O ID âncora de uma janela não representa o conjunto todo. Evidência alternativa ausente da referência não é declarada inválida.
- Compara NLI com a classificação humana nas claims não alteradas. Nas alteradas, a hipótese do gerador fica separada e é marcada como não pontuável enquanto não houver derivação factual validada.
- Produz `diagnostics.jsonl`, `unaligned_predictions.jsonl` e `report.json`, com hashes das entradas.

`classify_errors.py` preserva a classificação taxonômica legada para análise separada; a matriz baseada no gerador não é automaticamente acurácia contra referência humana.

Ainda falta um alinhador semântico robusto para mudanças de granularidade, protocolo de rótulos derivados pós-injeção e métricas globais com cobertura adequada. Esses limites aparecem no diagnóstico e no backlog, em vez de produzir números artificiais.
