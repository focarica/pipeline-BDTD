# Benchmark RAG — 30 perguntas

- `rag.json`: perguntas, resposta de referência, itens obrigatórios e erros críticos.
- `RAG.md`: versão legível do mesmo benchmark.
- `evidence.json`: fixture de referência, com 20 chunks de oito documentos, metadados e
  proveniência do snapshot lido diretamente do R2. Não é resultado de modelo nem corpus completo.
- `export_evidence.py`: exportador somente leitura das evidências selecionadas do R2.
- `validate.py`: checa os 30 casos e suas referências, sem chamar modelos.

Não incluir esta pasta no índice ou no prompt do gerador. O baseline recebe **somente**
`question`; o gabarito é usado no relatório esperado × respondido. A base híbrida importa
`curated/datasets/chunks.jsonl` do R2 e não lê esta fixture.

## Cobertura

As questões avaliam resultados condicionais, cálculos, método experimental, comparação entre
trabalhos, contradições entre representações e limites de inferência. Incluem DustAI,
PersonaReAct, SAAL, nutrição oncológica, VFC/COVID-19, previsão de ações, ecologia e ATA.
Não são amostra representativa de todas as obras do corpus.

R28/R29 pedem uma garantia não demonstrada nos resultados: não exigem provar a ausência
de uma informação em todo o corpus. A resposta deve explicar o limite da conclusão.

`evidence_groups` é uma lista de grupos obrigatórios (AND); dentro de um grupo, as fontes
são alternativas (OR). `dust.001` aponta para um chunk na fixture. `saal.abstract` aponta
para o resumo dos metadados, não o texto do PDF. Aceitar evidência alternativa válida após
revisão humana; não basta recuperar qualquer chunk do mesmo documento.

Não citar o campo `page` da pipeline como página física verificada: use ID e seção.
Os conflitos documentais fazem parte do teste, não devem ser resolvidos arbitrariamente.

## Avaliação

Para cada item de `required_claims`, atribuir 0 (errado/ausente), 0,5 (parcial) ou 1 (completo).
A nota do caso é a média dos itens. Registrar erros críticos separadamente; sucesso estrito
exige todos os itens completos e nenhum erro crítico. Aceitar paráfrases, ponto ou vírgula
decimal e as tolerâncias indicadas. Não exigir correspondência literal ao gabarito.

Registrar também alegações inventadas e, quando houver recuperação, apoio nas evidências e
qualidade das citações. Não penalizar a baseline por não citar chunks que não recebeu.
O runner atual não calcula notas automaticamente: a revisão é humana.

Para comparar com/sem RAG futuramente, preservar perguntas, versão do modelo, parâmetros
e orçamento de resposta; registrar contexto efetivamente enviado. Uma baseline com política
científica adicional deve ser identificada separadamente da baseline crua.
Uma condição com evidências escolhidas pelo gabarito é contexto-oráculo, não teste da busca.

Não ajustar recuperação ou prompts usando estas mesmas 30 perguntas e depois apresentá-las
como teste independente. Congelar configurações em dados de desenvolvimento distintos.
As questões compartilham documentos: diferenças agregadas não demonstram significância
estatística ou generalização por si só. Gabaritos exigem revisão humana antes do relatório final.

## Snapshot

O snapshot da fixture contém 960 IDs documentais e 58.494 chunks no objeto original, com
SHA-256 `68b42a9c2676fece7bef5eb11f6c090c936dd806daf60a2138e66225d568afa9`.
Somente as evidências selecionadas estão nesta pasta. O R2 pode conter uma versão mais
recente; verificar o hash do índice antes de reutilizar gabaritos e medidas de cobertura.

Na pasta `RAG/`:

```bash
uv run python benchmarks/validate.py
```

Para exportar outro snapshot, preservar/versionar a fixture antes: o exportador recusa
sobrescrita e não altera o bucket.

```bash
uv run --env-file ../.env benchmarks/export_evidence.py
```

Sem PDFs de apoio, guardrails, credenciais ou resultados de execuções nesta pasta.
