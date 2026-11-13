# Avaliar os resumos escolhidos no Factual Injector UI

Use o texto integral do documento original e os resumos completos compostos na tela do gerador. A entrada do avaliador é um CSV, não o JSON de seleção nem o TXT isolado. O importador reconstrói exatamente as alterações escolhidas, preserva o original como controle e mantém a proveniência em um manifesto separado.

## 1. Exportar a seleção

Na visualização do gerador, marque as propostas desejadas e clique em **Exportar seleção (.json)**. Guarde o JSONL de propostas correspondente e o `govreport_source.jsonl` original. O SHA-256 da seleção precisa coincidir com o arquivo de propostas; não use outro lote.

O importador não usa modelos nem requer GPU:

```bash
cd ~/factual-consistency-evaluation
python3 scripts/import_selected_summaries.py \
  --selection ~/factual-injector-ui/output/selecao_inconsistencias.json \
  --proposals ~/factual-injector-ui/Gerador_Estatico_V6_Implementacao/gerador_estatico_v6/output/claim_versions_v62.jsonl \
  --source ~/factual-injector-ui/Gerador_Estatico_V6_Implementacao/gerador_estatico_v6/output/govreport_source.jsonl \
  --output outputs/imports/selecao_v63_20261111.csv
```

Esse CSV já foi preparado nesta máquina em 11/11/2026. Para importar uma seleção nova, mude o nome da saída; os destinos existentes são recusados.

A seleção observada contém **cinco alterações de entidade e uma de predicado**. A saída tem um documento e três versões não vazias: original, entidade e predicado. Não foi selecionada correferência, portanto `resumo_corref` fica vazio e a extração ignora essa variante. O TXT `resumo_entidade.txt` foi comparado e coincide com o resumo reconstruído.

O formato é:

| Coluna | Conteúdo |
| --- | --- |
| `fonte` | Documento integral original, nunca o resumo original usado como premissa |
| `resumo_original` | Resumo original como controle, sem presunção de gold |
| `resumo_predicado` | Resumo completo com apenas as alterações de predicado escolhidas |
| `resumo_entity` | Resumo completo com apenas as alterações de entidade escolhidas |
| `resumo_corref` | Resumo completo com apenas as alterações de correferência escolhidas, ou vazio |

`source_index` preserva a posição no GovReport. `external_doc_id` permite relacionar a entrada ao gerador. O avaliador continua criando seus próprios IDs de documentos/claims.

## 2. Executar extração, recuperação e NLI

Use o ambiente próprio do avaliador. Não ative o ambiente UltraBERT do gerador para este comando:

```bash
cd ~/factual-consistency-evaluation
conda activate nlp_mestrado

python scripts/run_pipeline.py \
  --input outputs/imports/selecao_v63_20261111.csv \
  --from-stage claims \
  --until-stage nli \
  --all-docs \
  --device cuda:0
```

Comece em **claims**, pois os erros já foram gerados e escolhidos. `--from-stage generate` produziria novas alterações, substituindo o experimento que você quer avaliar. A entrada muda; a configuração científica do extrator, recuperador e NLI permanece a do avaliador.

O comando imprime o diretório em `outputs/runs/`. Consulte:

- `claims/claims.parquet`: claims reextraídas das versões completas;
- `retrieval/retrieval.parquet`: evidências recuperadas pelo próprio avaliador;
- `nli/nli.parquet`: `SUPPORTED`, `CONTRADICTED` ou `NOT_SUPPORTED`, scores e passagem usada;
- `nli/stage_counts.json`: contagens por status;
- `manifest.json` e `execution.log`: proveniência e erros da execução.

Este procedimento foi validado quanto à importação/contrato de entrada. Os modelos não foram executados automaticamente durante a preparação do CSV.

## 3. Taxonomia e interpretação

Para incluir a classificação de tipos no pipeline completo, use `--until-stage taxonomy` em uma nova execução. A taxonomia opera no subconjunto que o NLI classificou como `CONTRADICTED`.

Os textos importados não contêm marcadores `[ERROR_...]` nem instruções que revelem a resposta. O manifesto `selecao_v63_20261111.manifest.json` conserva as edições, claims originais e quantidades para inspeção externa. Isso evita transformar essas informações em pistas para a extração ou o NLI.

O baseline identifica seus rótulos legados a partir de marcadores. Como esta entrada não possui marcadores, `gabarito_injetado` continua `none`. **A matriz de comparação legada da taxonomia não mede acurácia neste lote importado.** Não transforme `none` em rótulo humano nem o tipo de alteração em certeza de contradição.

A extração pode dividir ou reformular as claims: os IDs não correspondem diretamente aos do gerador. Cinco alterações inseridas também não garantem cinco claims extraídas ou cinco contradições detectadas. Examine cobertura da extração, evidências e decisões NLI, e confirme os casos com a referência humana descrita em [usage.md](usage.md#referência-humana). A quantidade e o tipo de edição são controles do experimento, não gold factual.
