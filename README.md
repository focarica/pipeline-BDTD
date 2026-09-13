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

## Camada curated

Gera a camada curated a partir da camada processada já gerada: lê o manifesto e
os chunks de cada documento `completed`, e desnormaliza cada chunk com os
metadados completos do documento de origem (título, autores, resumo, assuntos,
data, instituição, repositório, direitos de acesso e URL da fonte) — cada
linha do dataset fica autocontida, sem necessidade de JOIN com outra tabela.

```bash
uv run python main.py curated
```

Com diretórios personalizados:

```bash
uv run python main.py curated --processed-dir data/processed --output data/curated
```

Saídas em `data/curated/`:

- `datasets/chunks.jsonl`: um chunk por linha, com todos os metadados do documento embutidos.
- `manifests/curated.json`: manifesto com contagens de documentos, chunks e documentos sem chunks encontrados em disco.
- `DATACARD.md`: composição do corpus, parâmetros de chunking, distribuição por idioma/instituição e limitações conhecidas.

## Sincronização com o R2 (Cloudflare)

Envia camadas locais para um bucket R2 (compatível com S3). Por padrão
sincroniza `raw` e `curated` — são a fonte da verdade (os PDFs originais,
caros de recoletar) e o produto final (o corpus pronto para consumo);
`staging` e `processed` são reconstruíveis localmente a partir do `raw` em
segundos/minutos, então não precisam de backup remoto.

Copie `.env.example` para `.env` e preencha com as credenciais do R2 (Account
ID e um token de API com permissão de leitura/escrita no bucket):

```bash
cp .env.example .env
```

```
R2_ACCOUNT_ID=...
R2_ACCESS_KEY_ID=...
R2_SECRET_ACCESS_KEY=...
R2_BUCKET=...
```

Depois:

```bash
uv run python main.py sync
```

Um arquivo já enviado (mesmo tamanho no bucket) é pulado nas execuções
seguintes — só o que mudou é reenviado.

Para escolher camadas ou bucket explicitamente:

```bash
uv run python main.py sync --layer raw --layer curated --bucket meu-bucket
```

## Testes

```bash
uv run pytest
```

## Camadas

- `data/raw/`: espelho fiel da fonte (respostas da API, PDFs originais, manifestos e proveniência). Nunca editado após a coleta.
- `data/staging/`: derivado offline do raw (`records/<id>.json` + `staging.json`), com metadados normalizados, `content_type` real detectado do arquivo e checagem de integridade (arquivos ausentes e órfãos).
- `data/processed/`: derivado do raw (`text/`, `chunks/`, `datasets/`, `manifests/processed.json`), com texto extraído, limpo, filtrado, deduplicado e anonimizado, pronto para pré-treino, fine-tuning e RAG.
- `data/curated/`: derivado do processed (`datasets/chunks.jsonl`, `manifests/curated.json`, `DATACARD.md`), com chunks desnormalizados e documentados, prontos para indexação vetorial/RAG.
