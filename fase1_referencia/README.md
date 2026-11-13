# Fase 1 — Construção da referência

**Resumo original → claims → recuperação → validação humana única → referência congelada.**

1. `extrair_claims_originais.py` recebe JSONL com `report`, `summary` e `source_index`, cria entrada apenas original e extrai claims.
2. `prepare_reference.py` recupera candidatos somente para `original` por padrão.
3. `generate_review_html.py` e `serve_review.py` abrem a revisão de claims, conjuntos suficientes e classificação factual. Nenhuma predição cria gold.
4. `export_reference.py` exporta somente decisões humanas finalizadas, com fonte e busca conferidas.
5. `congelar_referencia.py` confere o snapshot e os offsets, preserva os conjuntos suficientes e cria um contrato estável para as outras fases. Não repete a anotação nem afirma que todas as claims de uma sentença foram extraídas.

Exemplo, na raiz do projeto e no ambiente do avaliador:

```bash
python fase1_referencia/extrair_claims_originais.py --source fase1_referencia/dados/govreport_source.jsonl --device cuda:0 --run-id original-001
python fase1_referencia/prepare_reference.py --input outputs/fase1_referencia/original-001/claims/claims.parquet --device auto --run-id candidatos-001
python fase1_referencia/generate_review_html.py --input outputs/fase1_referencia/candidatos-001/prepare-reference --run-id html-001
python fase1_referencia/serve_review.py --html outputs/fase1_referencia/html-001/review-html/avaliacao.html --annotations outputs/fase1_referencia/anotacoes.json --port 8773 --open
```

Após concluir a validação humana:

```bash
python fase1_referencia/export_reference.py --input outputs/fase1_referencia/candidatos-001/prepare-reference --annotations outputs/fase1_referencia/anotacoes.json --run-id gold-001
python fase1_referencia/congelar_referencia.py --gold outputs/fase1_referencia/gold-001/export-reference/gold_claims.jsonl --frame outputs/fase1_referencia/candidatos-001/prepare-reference --source fase1_referencia/dados/govreport_source.jsonl --output outputs/fase1_referencia/referencia-001
```

A saída congelada contém `reference_claims.jsonl`, `sources.jsonl` e `manifest.json`: claim original validada, classe factual, conjuntos suficientes de evidências e offsets exatos na fonte. `legado_sentencial/` preserva os dados antigos; os vínculos revisados por sentença não são promovidos automaticamente a referência por claim.
