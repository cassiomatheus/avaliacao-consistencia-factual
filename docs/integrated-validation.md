# Validação integrada e automação experimental

## Auditoria inicial

O código anterior já implementava: extração/retrieval/NLI independentes, revisão de evidências fora do Top-K, conjuntos suficientes, salvamento JSON atômico com controle de concorrência e histórico, tradução de leitura, gerador estático rastreável e exportação congelada de claims originais. Esses componentes são reutilizados.

As lacunas identificadas eram edição/adição de claims humanas, cobertura das sentenças omitidas, aprovação persistida de alterações na mesma revisão, materialização sem nova seleção humana, alinhamento com abstenção além do texto exato e relatórios com denominadores explícitos. O comparador anterior tratava expectativas de alterações como não pontuáveis, mesmo quando viessem a ser aprovadas por protocolo humano.

Ordem de implementação: contrato estendido e persistência → interface integrada → geração/aprovação/materialização → alinhamento e evidências → condições experimentais e relatório. A extensão de revisão mantém `schema_version: 1` e usa o namespace `integrated`, sem promover revisões históricas por sentença a gold por claim. Os snapshots anteriores não são migrados nem sobrescritos.

O catálogo E0–E6 histórico não deve ser confundido com as condições fatoriais E0–E3 deste fluxo. As condições são identificadas separadamente nos manifestos.

## Como iniciar

Use o ambiente existente e uma área nova de anotações. Estes comandos reutilizam as claims da execução local, preparam somente o original e não alteram a seleção antiga:

```bash
conda activate nlp_mestrado
python fase1_referencia/prepare_reference.py \
  --input outputs/fase3_pipeline/comparacao-validada-20261111/claims/claims.parquet \
  --device cuda:0 --run-id revisao-integrada-preparo-20261112
python fase1_referencia/generate_review_html.py \
  --input outputs/fase1_referencia/revisao-integrada-preparo-20261112/prepare-reference \
  --run-id revisao-integrada-html-20261112
python fase1_referencia/serve_review.py \
  --html outputs/fase1_referencia/revisao-integrada-html-20261112/review-html/avaliacao.html \
  --source fase1_referencia/dados/govreport_source.jsonl \
  --annotations outputs/fase1_referencia/revisao-integrada/anotacoes.json \
  --port 8773
```

As duas primeiras execuções já foram produzidas localmente em 12/11/2026. Se esses diretórios existem, pule esses comandos; para repetir, escolha novos `--run-id`. Em outro checkout, substitua a entrada pelo Parquet e o snapshot JSONL correspondentes. O snapshot precisa conter todos os documentos do HTML, com fontes e resumos originais exatos. Divergências de fonte, resumo e offsets são recusadas.

Abra **http://127.0.0.1:8773/integrated**. O comando também aceita `--open`. Sem `--source`, o serviço mantém a interface clássica. Quando existe tradução incorporada ao HTML, ela continua disponível; textos corrigidos sem tradução correspondente permanecem em inglês.

Para preparar um novo documento desde a extração, use [extrair_claims_originais.py](../fase1_referencia/extrair_claims_originais.py) e os procedimentos da [Fase 1](../fase1_referencia/README.md).

## Uma sessão humana

### Tradução para leitura

A interface pode mostrar português junto do original em inglês. A tradução usa o modelo local `qwen3.5:9b` do Ollama, temperatura zero e o protocolo `govreport-en-pt-v2-faithful`. O prompt exige preservar todas as orações, agentes, números, unidades, negações, ressalvas e modalidade, sem corrigir inconsistências do original. O inglês continua sendo o texto editável e a entrada científica; a tradução não cria decisões humanas.

Para traduzir todo o documento preparado, incluindo afirmações e evidências:

```bash
python fase1_referencia/translate_reference.py \
  --input outputs/fase1_referencia/revisao-integrada-preparo-20261112/prepare-reference \
  --scope all --model qwen3.5:9b \
  --cache outputs/fase1_referencia/traducoes-qwen35-fiel.sqlite3 \
  --run-id traducao-qwen35-fiel-20261112
```

Gere o HTML com `--translations` apontando para o diretório `translate-reference` dessa execução e reabra o serviço com esse HTML e o mesmo arquivo de anotações. Use um novo identificador para repetir a execução; o cache reaproveita segmentos concluídos. A interface mostra avisos heurísticos de possíveis diferenças. Esses avisos, assim como sua ausência, não comprovam equivalência semântica nem substituem uma conferência humana.

Uma segunda passagem com o mesmo modelo pode revisar os segmentos sinalizados:

```bash
python fase1_referencia/revisar_traducoes.py \
  --input outputs/fase1_referencia/traducao-qwen35-fiel-20261112/translate-reference \
  --output outputs/fase1_referencia/traducao-qwen35-fiel-revisada-20261112
```

Essa revisão preserva o artefato inicial, o inglês e os segmentos verificados por humanos. Registra a tradução anterior e o prompt de revisão; respostas vazias, truncadas ou com falha não substituem a tradução anterior. Os alertas são recalculados, sem promover traduções automáticas a verificadas por humanos. Para usar a segunda passagem na interface, aponte `--translations` para o novo diretório.

Na execução local, uma conferência adicional retraduziu os casos de números/siglas sinalizados e os segmentos contendo `catfish` sem contexto vizinho nem rascunho, usando o glossário técnico `catfish → bagre`. Essa opção é `--source-only-critical`. O resultado final está em `outputs/fase1_referencia/traducao-qwen35-fiel-final-20261112`; os 517 textos têm tradução, mas 112 ainda possuem alertas heurísticos para conferência. Isso não equivale a validação humana de fidelidade. O HTML correspondente foi gerado na execução `revisao-integrada-traduzida-qwen35-20261112`.

### Passos da revisão

A interface abre no primeiro passo. Preencha **Seu nome** e trabalhe com uma afirmação por vez:

1. **Afirmação:** leia a frase original e confira o texto extraído. Corrija-o se necessário, acrescente informações omitidas e confirme que conferiu a frase. Clique em **A afirmação está correta · escolher evidências**. Isso confirma a extração; a veracidade será avaliada no próximo passo.
2. **Evidências:** selecione os trechos do documento e salve-os como um grupo. Trechos necessários em conjunto devem ficar no mesmo grupo. Escolha a relação factual, confirme a leitura da fonte e a conclusão da busca, e clique em **Concluir verificação · revisar alterações**. Seleções ainda não salvas em grupo ficam preservadas como rascunho e impedem a finalização.
3. **Inconsistências:** para uma afirmação sustentada e finalizada, clique em **Analisar os 3 tipos e sugerir inconsistências**. O sistema examina a sentença e apresenta entidade, predicado e correferência separadamente, com motivos para não aplicação, ausência de sugestão segura ou análise indisponível. Uma entidade nomeada deve estar também na afirmação; a correferência exige confirmação contextual do antecedente. Não são forçadas propostas dos três tipos. Compare a sentença completa antes/depois, confirme a relação factual e aprove, rejeite ou registre dúvida. A análise automática utiliza os modelos já instalados e mantém propostas e decisões anteriores. As estratégias numéricas do fluxo legado continuam disponíveis por API/CLI; não são apresentadas como substituições de entidade nomeada nessa análise integrada.
4. **Finalizar:** consulte as pendências e salve a referência final quando todas estiverem resolvidas. Alterações posteriores na afirmação ou nas evidências invalidam aprovações antigas para essa finalização.

Use **Conferir outra afirmação** para seguir a revisão. **Visão geral** mostra o progresso; o seletor de documento, frase e afirmação fica em **Trocar de documento, frase ou afirmação**. Códigos e pontuações ficam em detalhes opcionais.

Claims/cobertura/evidências têm salvamento após edição e botões explícitos de gravação. A aprovação de uma proposta exige o botão de decisão. O cabeçalho informa a gravação em disco. As anotações clássicas e a extensão `integrated` compartilham o mesmo JSON, o mesmo bloqueio de arquivo, controle de versão e histórico atômico. Alterações concorrentes são recusadas; exporte o rascunho e recarregue antes de continuar.

As anotações históricas por sentença continuam preservadas e não são convertidas automaticamente em validações de claims. Um arquivo integrado deve ser reaberto com o mesmo HTML e snapshot; não o exporte pelo exportador clássico que desconhece claims humanas adicionadas. Use o congelamento integrado.

## Congelamento e materialização

O botão de salvar a referência final cria um job e publica, em um diretório novo:

```text
integrated_runs/<job>/snapshot/
  reference_claims.jsonl
  sources.jsonl
  approved_perturbations.jsonl
  review.json
  manifest.json
```

Todos os caminhos ficam ao lado do arquivo de anotações. O snapshot guarda os hashes dos arquivos, o protocolo e a revisão completa, inclusive o histórico de registros não exportados como gold. O sistema recusa sobrescrita e verifica os hashes antes de reutilizar o snapshot.

Para congelar a revisão já salva pela CLI, sem editar as anotações:

```bash
python fase1_referencia/congelar_integrado.py \
  --html outputs/fase1_referencia/revisao-integrada-html-20261112/review-html/avaliacao.html \
  --source fase1_referencia/dados/govreport_source.jsonl \
  --annotations outputs/fase1_referencia/revisao-integrada/anotacoes.json \
  --output outputs/fase1_referencia/meu-snapshot-integrado
```

Esse comando exige que as confirmações humanas já estejam gravadas e que não existam impedimentos. Ele não preenche campos pendentes nem cria validações humanas.

Pela interface, selecione um snapshot concluído e clique em **Materializar alterações aprovadas**. Também é possível executar:

```bash
python fase2_injecao/materializar_aprovadas.py \
  --snapshot /caminho/real/do/snapshot \
  --output outputs/fase2_injecao/meus-pares-aprovados
```

Substitua o caminho pelo `result.snapshot` apresentado no job. A saída inclui `cases.jsonl`, um manifesto e um CSV por caso. Cada modificado contém **uma única alteração localizada aprovada** sobre o resumo completo. Há controles originais separados. Esse desenho evita interações e sobreposição de múltiplas alterações; a composição histórica por tipo continua disponível no importador anterior.

Os CSVs contêm apenas posições de documentos, fonte e textos dos resumos. Metadados de validação e relações esperadas ficam em `cases.jsonl`, fora da entrada dos modelos. Cada CSV pode ser processado por [run_pipeline.py](../fase3_pipeline/run_pipeline.py).

## Comparação e condições E0–E3

Na interface, **Executar E0–E3 e relatório** materializa os pares aprovados e executa as etapas existentes em fila, com estado persistido. Reiniciar o serviço marca jobs interrompidos explicitamente; não os repete nem sobrescreve resultados. Gere um job novo para repetir. A confirmação semântica de alinhamentos é opcional e está disponível na CLI:

```bash
python avaliacao_automatica/executar_experimentos.py \
  --snapshot /caminho/real/do/snapshot \
  --output outputs/avaliacao_automatica/meu-experimento \
  --device cuda:0
```

| Condição | Claim | Evidência |
| --- | --- | --- |
| E0 | Extraída do resumo | Recuperada automaticamente |
| E1 | Extraída e alinhada de forma confiável | Conjuntos de referência |
| E2 | Claim-alvo original ou modificada pré-aprovada | Recuperada automaticamente |
| E3 | Claim-alvo original ou modificada pré-aprovada | Conjuntos de referência |

E0 não recebe o gabarito. E1 se abstém quando não existe alinhamento único ou referência positiva apropriada; composições um-para-muitos permanecem diagnosticadas, mas não são agregadas artificialmente em uma decisão NLI. E2 intervém na extração e E3 investiga o NLI com claim e evidências fornecidas. O checkpoint, os limiares e o decisor NLI são os mesmos nas quatro condições.

Conjuntos suficientes são concatenados em ordem de referência e identificados como conjuntos não contíguos. Não recebem offsets fictícios. A convenção de qualidade para evidência fornecida é 1.0 e fica registrada no manifesto; isso deve ser considerado ao interpretar diferenças entre condições. As três condições de intervenção compartilham uma passagem pelo NLI por caso. Os adaptadores científicos mantêm seu ciclo de carga/descarga de modelos por etapa; lotes grandes podem ter custo relevante de inicialização.

O alinhador utiliza identidade textual e composição exata. Com `--semantic-alignment`, embeddings selecionam candidatos, mas a confirmação requer entailment bidirecional, compatibilidade de números, negação, entidades NER e siglas. As confirmações têm proveniência `MODEL_BASED_EQUIVALENCE`; não são certificação humana. Limiares fixos do protocolo não são ajustados pelos resultados do teste. O alinhador semântico roda em CPU para não ocupar uma segunda cópia de DeBERTa na GPU do experimento.

Para avaliar o alinhador separadamente:

```bash
python avaliacao_automatica/avaliar_alinhador.py \
  --cases tests/fixtures/alignment_cases.json \
  --output outputs/avaliacao_automatica/alinhador-casos-conhecidos.json
```

O JSON contém status esperado e IDs esperados. Crie uma coleção de desenvolvimento independente, incluindo paráfrases e negativos difíceis, antes de validar o protocolo semântico com `--semantic`. Os testes sintéticos atuais verificam contratos, não calibram a qualidade do alinhador em GovReport.

O comparador canônico também aceita `--semantic-alignment`; continua reconhecendo os contratos antigos e só pontua alterações com pré-aprovação humana, protocolo e vínculo à referência conferidos. Expectativas provisórias continuam não pontuáveis.

## Relatórios e denominadores

A execução produz uma pasta `report` com:

- `experiment_summary.json` e `statistical_summary.json`;
- `claims_alignment.csv`, `evidence_comparison.csv`, `nli_evaluation.csv` e `error_diagnostics.csv`;
- `metrics_by_document.csv`, `metrics_by_error_type.csv` e `metrics_by_position.csv`;
- `report.md`.

O relatório preserva casos não alinhados no denominador total e informa abstenções, casos NLI avaliáveis, matriz de confusão, precisão, recall, F1 e macro-F1. A média macro usa as três classes fixas; classes sem denominador mantêm escores individuais indisponíveis e contribuem zero à média, conforme política registrada. Não confunda esse número com uma média apenas das classes presentes.

Success@K mede a recuperação integral de pelo menos um conjunto suficiente **conhecido** nas condições E0/E2 avaliáveis. O relatório publica seu denominador e a cobertura de alinhamento. E1/E3 não recebem Success@K artificialmente igual a 1. Passagens alternativas permanecem não verificadas. IDs de âncoras não são equiparados aos conjuntos; textos, hashes e intervalos de offsets conferidos permitem comparar segmentações diferentes e janelas sobrepostas.

Os resultados também registram comprimento do documento, quantidade de evidências e posição relativa. Quando há pelo menos dez documentos, a rotina calcula intervalo percentil por bootstrap agrupado por documento, seed 42 e mil réplicas. Abaixo desse limite, o intervalo fica indisponível. A divisão utiliza `experimental_split` em cada fonte (`development` ou `test`, padrão `test`); um documento não pode ocupar ambos. O sistema não ajusta seus limiares usando o teste, mas uma divisão adequada entre coleções depende do protocolo de seleção do pesquisador.

As decisões consolidadas também ficam em `decisions.jsonl`, com hash no manifesto. Para gerar outra apresentação do relatório sem executar os modelos novamente:

```bash
python avaliacao_automatica/consolidar_relatorio.py \
  --experiment outputs/avaliacao_automatica/meu-experimento \
  --output outputs/avaliacao_automatica/meu-relatorio
```

## Verificações e limites atuais

### Arquivos desta implementação

| Arquivo | Responsabilidade |
| --- | --- |
| [workspace.py](../src/factual_eval/fase1_referencia/workspace.py) | Catálogo de claims humanas, contratos, bloqueios, proveniência, progresso e snapshots. |
| [review_server.py](../src/factual_eval/fase1_referencia/review_server.py) | Integração das rotas e preservação do armazenamento JSON existente. |
| [workspace_service.py](../src/factual_eval/fase1_referencia/workspace_service.py) | Fila única de tarefas, progresso persistido, geração e congelamento. |
| [integrated.html](../src/factual_eval/fase1_referencia/integrated.html) | Revisão guiada em quatro passos, visão geral, salvamento e ações experimentais. |
| [disk_autosave.js](../src/factual_eval/fase1_referencia/disk_autosave.js), [modelo.html](../src/factual_eval/fase1_referencia/modelo.html) | Preservação da extensão integrada ao retomar/importar pela interface clássica. |
| [serve_review.py](../fase1_referencia/serve_review.py), [congelar_integrado.py](../fase1_referencia/congelar_integrado.py) | Inicialização da interface e congelamento por CLI. |
| [approved.py](../src/factual_eval/fase2_injecao/approved.py), [materializar_aprovadas.py](../fase2_injecao/materializar_aprovadas.py) | Reconstrução dos pares aprovados e publicação dos CSVs sem gabaritos. |
| [alignment.py](../src/factual_eval/avaliacao_automatica/alignment.py), [avaliar_alinhador.py](../avaliacao_automatica/avaliar_alinhador.py) | Correspondência conservadora, confirmação opcional e avaliação separada do alinhador. |
| [evidence.py](../src/factual_eval/avaliacao_automatica/evidence.py), [compare.py](../src/factual_eval/avaliacao_automatica/compare.py) | Cobertura de conjuntos por textos/spans e pontuação de relações pré-aprovadas. |
| [metrics.py](../src/factual_eval/avaliacao_automatica/metrics.py), [reporting.py](../src/factual_eval/avaliacao_automatica/reporting.py) | Métricas, denominadores, separação por documento e relatórios. |
| [experiments.py](../src/factual_eval/avaliacao_automatica/experiments.py), [executar_experimentos.py](../avaliacao_automatica/executar_experimentos.py), [consolidar_relatorio.py](../avaliacao_automatica/consolidar_relatorio.py) | Orquestração E0–E3 e reprodução dos relatórios sem nova inferência. |
| [schemas.py](../src/factual_eval/schemas.py) | Tratamento de índices NLI inteiros/nulos em colunas Parquet promovidas a decimal. |
| [test_integrated_workspace.py](../tests/test_integrated_workspace.py), [alignment_cases.json](../tests/fixtures/alignment_cases.json) | Contratos críticos e exemplos controlados de alinhamento. |

Também foram atualizados os índices de documentação, o README principal, o backlog e o [registro de validação](validation.md).

### Estado das funcionalidades

- Reutilizados: extrator, recuperadores, decisor NLI, gerador estático, serviço local, bloqueio/versões/histórico JSON e traduções existentes.
- Implementados: revisão/adição/rejeição de claims, cobertura selecionada, suficiência, pré-aprovação de alterações, congelamento, materialização, jobs locais, alinhamento conservador, comparação por spans, métricas e condições E0–E3.
- Parcial: equivalência semântica possui critérios e abstenções, mas ainda requer validação independente em uma coleção real; composição um-para-muitos só é aceita quando as proposições coincidem exatamente e suas decisões NLI não são agregadas em E1.
- Não implementado: derivação automática geral de rótulos `RULE_DERIVED`. Sem pré-aprovação humana apropriada, alterações permanecem provisórias.

Um piloto sintético com os modelos reais executou E0–E3 para um controle e uma alteração numérica. Ele verifica encadeamento e contratos; não valida qualidade factual em dados da pesquisa. A preparação local de um documento GovReport reutilizou 23 claims originais e recuperou candidatos reais; nenhuma anotação humana foi criada automaticamente.

Nenhum resultado anterior foi sobrescrito. Os snapshots e relatórios experimentais ficam fora do Git. Não foi realizada uma nova campanha humana nem calibrado o alinhador no conjunto de teste.
