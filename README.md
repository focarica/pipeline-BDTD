# pipeline-BDTD
Pipeline de tratamento de dados da BDTD com foco na área de Computação, Informática e Informação; para pré-treinamento contínuo, fine-tuning, RAG e benchmarks de avaliação

## Piloto inicial

Instale o `uv`, sincronize as dependências usando Python 3.14+ e execute um piloto local:

```bash
uv sync
uv run python main.py --limit 5
```

O coletor usa a API JSON da BDTD, salva as respostas brutas e os documentos em
`data/raw/` e valida o manifesto resultante da coleta.
