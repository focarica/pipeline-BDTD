# pipeline-BDTD
Pipeline de tratamento de dados da BDTD com foco na área de Computação, Informática e Informação; para pré-treinamento contínuo, fine-tuning, RAG e benchmarks de avaliação

## Piloto inicial

Instale o `uv`, sincronize as dependências usando Python 3.14+ e execute um piloto local:

```bash
uv sync
uv run python main.py --limit 5
```

O coletor usa a API JSON da BDTD, salva as respostas brutas e os documentos em
`data/raw/`, valida o manifesto resultante da coleta e deriva a camada staging em
`data/staging/`.

Registros restritos, indisponíveis ou duplicados são ignorados sem falhar a coleta;
o motivo fica registrado em `reason` / `reason_detail` no manifesto.

## Somente o staging

Para remontar o staging a partir de um raw já coletado, sem nenhuma requisição de rede:

```bash
uv run python main.py --only-staging
```

Com diretórios personalizados:

```bash
uv run python main.py --only-staging --output data/raw --staging data/staging
```

## Camada processed

Gera a camada processada a partir do raw já coletado: extrai o texto dos PDFs,
limpa e normaliza, filtra por idioma/qualidade, deduplica (MinHash), anonimiza
PII, cria chunks cientes de tokens e serializa três datasets para pré-treino
contínuo, fine-tuning e RAG.

```bash
uv run python main.py processed
```

Com diretórios e parâmetros personalizados:

```bash
uv run python main.py processed \
  --raw-dir data/raw \
  --output data/processed \
  --target-tokens 1024 \
  --overlap 128 \
  --min-len 500
```

Opções da camada processed:

- `--raw-dir`: diretório da camada bruta (padrão `data/raw`).
- `--output`: diretório da camada processada (padrão `data/processed`).
- `--target-tokens`: tokens por chunk (padrão `1024`).
- `--overlap`: tokens de sobreposição entre chunks (padrão `128`).
- `--min-len`: tamanho mínimo em caracteres para manter o texto (padrão `500`).

Sem um raw válido em `--raw-dir`, o runner gera fixtures sintéticas em um
diretório temporário para permitir execução offline.

Saídas em `data/processed/`:

- `text/<id>.txt`: texto completo limpo e anonimizado por registro.
- `chunks/<id>.jsonl`: chunks com tokens, seção e paginação por registro.
- `datasets/text.jsonl`: corpus para pré-treinamento contínuo.
- `datasets/chunks.jsonl`: documento + chunks para RAG e benchmarks.
- `datasets/instruction.jsonl`: instrução + input por chunk para fine-tuning.
- `manifests/processed.json`: manifesto com config, dedup e validação.

## Testes

```bash
uv run pytest
```

## Camadas

- `data/raw/`: espelho fiel da fonte (respostas da API, PDFs originais, manifestos e proveniência). Nunca editado após a coleta.
- `data/staging/`: derivado offline do raw (`records/<id>.json` + `staging.json`), com metadados normalizados, `content_type` real detectado do arquivo e checagem de integridade (arquivos ausentes e órfãos).
- `data/processed/`: derivado do raw (`text/`, `chunks/`, `datasets/`, `manifests/processed.json`), com texto extraído, limpo, filtrado, deduplicado e anonimizado, pronto para pré-treino, fine-tuning e RAG.
