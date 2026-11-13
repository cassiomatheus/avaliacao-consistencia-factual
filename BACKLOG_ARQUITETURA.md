# Backlog da arquitetura

## Referência e injeção
- [x] Interface integrada com correção/adição de claims, cobertura e pré-aprovação humana de alterações; [guia](docs/integrated-validation.md).
- [x] Materialização de pares mínimos pré-aprovados a partir de snapshots com hashes verificados.
- [x] Separar Fase 1, Fase 2, Fase 3 e avaliação automática.
- [x] Extrair e revisar somente o original no caminho da referência.
- [x] Congelar claims humanas e conjuntos suficientes com hashes e offsets exatos.
- [x] Integrar o gerador preservando o vínculo à claim original e a alteração correspondente na sentença.
- [x] Manter os dados sentenciais anteriores como provisórios.
- [ ] Produzir a referência humana por claim para os documentos do experimento real.
- [ ] Validar um protocolo de derivação do rótulo factual das alterações. Hipótese do gerador não basta.

## Avaliação automática
- [x] Condições fatoriais E0–E3, métricas com denominadores explícitos e relatório; piloto sintético com modelos reais.
- [x] Alinhamento conservador, confirmação semântica opcional e abstenção; falta validar o alinhador em coleção independente real.
- [x] Cobertura por intervalos verificados para segmentações e janelas diferentes, com alternativas não anotadas marcadas como não verificadas.
- [x] Alinhamento exato, detecção de ambiguidade e registros não alinhados.
- [x] Comparação de conjuntos suficientes conhecidos sem equiparar âncora de janela a conjunto.
- [x] Comparação NLI com o gold original quando aplicável, sem promover expectativas não validadas.
- [x] Diagnóstico separado do pipeline e proteção contra vazamento de rótulos para os modelos.
- [ ] Alinhamento semântico um-para-muitos/muitos-para-um com protocolo de validação.
- [ ] Comparação robusta por spans para evidências segmentadas de modos diferentes e conjuntos alternativos.
- [ ] Métricas por etapa e intervalos de confiança somente com cobertura e rótulos adequados.
- [ ] Experimento end-to-end com modelos reais nas três fases; os testes da reorganização usam fixtures/modelos simulados.
