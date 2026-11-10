# RAG — BDTD

Código, testes e benchmark de RAG. Não inclui PDFs de apoio, guardrails, credenciais,
corpus completo ou resultados de execuções. Execute os comandos desta página dentro de `RAG/`.

## Base de busca híbrida — R2 → Qdrant

Esta base é separada do baseline cru. `run_rag.py` continua enviando somente a pergunta.
`hybrid_search.py` apenas indexa e recupera trechos: não chama o Qwen gerador e não executa
o benchmark. Nenhum gabarito ou arquivo de `benchmarks/` é indexado.

1. Subir Qdrant local, persistente, acessível somente em `127.0.0.1:6333`:

```bash
docker compose up -d qdrant
ollama pull bge-m3
```

2. Indexar **o objeto remoto** `curated/datasets/chunks.jsonl` usando as credenciais R2
da pipeline, sem copiar `.env` ou credenciais para este projeto:

```bash
uv run --env-file ../.env \
  hybrid_search.py --collection bdtd_20261109 index
```

O script usa boto3 declarado no próprio arquivo. O `.env` pertence à raiz da pipeline e não
deve ser copiado ou versionado. O R2 é somente leitura. Faz download de um
snapshot para um arquivo temporário em `/tmp/opencode`, valida o JSONL inteiro e então
indexa em lotes de oito. O arquivo temporário é removido ao terminar ou falhar; os textos ficam
no volume persistente do Qdrant. É necessário espaço para uma cópia temporária do objeto,
o índice e os embeddings. Pode demorar: todos os chunks passam pelo modelo de embeddings.

São indexados chunks com título e um registro separado de resumo por documento. Metadados
incluem IDs originais, URL de origem, seção e tipo. Não interpreta `page` como página física.
Um registro interno guarda bucket/chave, ETag, SHA-256 dos bytes reais, horário, contagens e
digest do modelo de embeddings. As contagens não dependem do antigo manifesto curated.

Coleção existente é recusada: para outro snapshot, escolha outro nome. A carga não apaga nem
substitui coleções. Carga interrompida permanece marcada como incompleta e não é consultável
pelo script; crie uma coleção nova para repetir. Esta versão inicial não implementa retomada,
troca automática de alias ou exclusão de índices antigos.

3. Consultar a combinação semântica + palavras:

```bash
uv run hybrid_search.py --collection bdtd_20261109 query \
  --text "Quais os resultados da calibração de MP10 no DustAI?"
```

Ou testar os componentes separadamente:

```bash
uv run hybrid_search.py --collection bdtd_20261109 query --mode words --text "DustAI MP10"
uv run hybrid_search.py --collection bdtd_20261109 query --mode semantic --text "calibração de sensores de partículas"
```

- **Semântica:** embedding `bge-m3` pelo Ollama e similaridade cosseno no Qdrant.
- **Palavras:** BM25 nativo sobre título + texto, com minúsculas, normalização de acentos e
  stopwords portuguesas. Corpus contém também inglês; não aplicamos stemming português a
  textos bilíngues. Parâmetros e qualidade ainda precisam ser avaliados em dados de desenvolvimento.
- **Híbrida:** até 20 candidatos por componente, combinados por RRF com pesos padrão iguais.
  Retorna cinco trechos por padrão (`--limit`). O score não é probabilidade de resposta correta.
- **Dependência de versão:** Qdrant **>=1.20**, necessário para BM25 no índice textual.
  O Compose fixa 1.20.0. Não é somente filtro de palavras nem banco SQLite auxiliar.
- Consultas exigem carga concluída. Semântica/híbrida verificam se o digest do embedding
  instalado continua igual ao usado na carga. `words` funciona sem Ollama.

URLs alternativas: `--qdrant` e `--ollama` antes do subcomando. Serviço local não tem
autenticação: não exponha sua porta em rede pública. `docker compose stop` para parar sem
apagar o volume. Não use `docker compose down -v` se quiser preservar os dados.

O Compose fixa o projeto `trab_final` para reutilizar o contêiner e o volume
`trab_final_qdrant_data` já criados. Esta cópia não reinicia o serviço nem interfere na carga.
Em outra máquina, o mesmo comando cria os recursos se ainda não existirem.

## Executar baseline cru

Com o Ollama ativo, dentro de `RAG`:

```bash
uv run run_rag.py --benchmark benchmarks/rag.json --model qwen3.5:2b
```

O runner envia **somente a pergunta original como uma mensagem de usuário**, em chamada
independente por caso. Não adiciona mensagem de sistema, política científica, exemplos,
gabarito, histórico, corpus, busca lexical ou RAG. O campo `policy` do benchmark não é enviado.
Não executa juiz automático: mostra esperado × respondido para análise humana.

"Modelo cru" aqui significa o modelo instalado, sem instruções adicionais do runner.
Seu alinhamento, template e configuração próprios no Ollama continuam ativos. Não é uma
versão pré-instrução ou sem alinhamento. O runner não força `think=false`; o modo de raciocínio
é o padrão do modelo. A temperatura 1 já configurada no arquivo foi preservada. Seed, janela
e limite de geração só são enviados se explicitados:

```bash
uv run run_rag.py --benchmark benchmarks/rag.json --limit 2
uv run run_rag.py --benchmark benchmarks/rag.json --case R01 --temperature 1
```

As perguntas continuam específicas aos trabalhos, pois esse é o benchmark solicitado.
Mesmo sem sistema, o modelo pode declarar que não sabe ou mencionar contexto: o runner
não garante uma forma de resposta. Não há consulta a nenhuma database.

## Saída

O terminal mostra pergunta, esperado, respondido e tempo. Em `results/<horário>/`:

- `report.md`: comparação esperado × respondido para cada questão.
- `answers.jsonl`: resposta e requisição exata enviada ao Ollama; raciocínio separado se retornado.
- `summary.json`: execuções, falhas, truncamentos e tempo; sem percentual fictício de acerto.
- `manifest.json`: configuração, hashes e metadados do modelo; marca `mode: raw_baseline`.

Resultados antigos com prompt de sistema ou busca foram preservados, mas **não são o baseline
cru**. Execute novamente e não misture esses resultados com os novos.

Outras opções: `--output results/nome-novo`, `--url http://127.0.0.1:11434`,
`--timeout 600`, `--max-tokens 1200`, `--num-ctx 16384`, `--seed 42`.
O diretório de saída deve ser novo. `Ctrl+C` preserva os casos concluídos; não há retomada
automática. O runner não instala modelos nem acessa o R2. Usa somente a biblioteca padrão.

## Testes offline

```bash
uv run python -m unittest discover -s tests -v
```

Verificam que apenas a pergunta chega ao gerador, sem política, contexto, gabarito,
histórico ou alteração explícita do modo de raciocínio.
