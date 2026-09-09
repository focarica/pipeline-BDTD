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

## Camadas

- `data/raw/`: espelho fiel da fonte (respostas da API, PDFs originais, manifestos e proveniência). Nunca editado após a coleta.
- `data/staging/`: derivado offline do raw (`records/<id>.json` + `staging.json`), com metadados normalizados, `content_type` real detectado do arquivo e checagem de integridade (arquivos ausentes e órfãos).
