"""Geração do DATACARD.md da camada curated da BDTD."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

_LIMITATIONS = (
    "Extração de texto via `pypdf`: cobre apenas PDFs com texto embutido, "
    "sem OCR — documentos escaneados como imagem ficam como `no_text`.",
    "Filtro de idioma exige português (`pt`) com confiança de detecção "
    "(`langdetect`) de pelo menos 0,5; textos bilíngues ou com poucos "
    "caracteres podem ser descartados por engano.",
    "Anonimização de nomes de pessoas é heurística (nomes já conhecidos dos "
    "metadados + padrões de papel como \"Orientador: Nome\"), não um "
    "reconhecimento de entidades nomeadas (NER) completo — nomes fora desses "
    "padrões podem não ser redigidos, e o rótulo `<<PERSON>>` às vezes "
    "engole também a palavra de papel (ex.: \"orientador\").",
    "Deduplicação (MinHash/LSH) roda do zero a cada execução: reprocessar um "
    "documento novo refaz o agrupamento de todos os outros, não é incremental.",
)


def render_datacard(
    processed_manifest: Mapping[str, Any],
    curated_manifest: Mapping[str, Any],
    chunk_rows: Sequence[Mapping[str, Any]],
) -> str:
    """Monta o DATACARD.md: composição, parâmetros e limitações do corpus curated."""
    status_counts = _status_counts(processed_manifest.get("records", []))
    config = processed_manifest.get("config", {})
    dedup = processed_manifest.get("dedup", {})
    is_synthetic = processed_manifest.get("raw_manifest") == "fixtures-sinteticas"

    languages = Counter(str(row.get("language", "")) or "desconhecido" for row in chunk_rows)
    institutions = Counter(
        str(row.get("institution", "")) or "desconhecido" for row in chunk_rows
    )
    avg_tokens = _average(row.get("tokens", 0) for row in chunk_rows)

    lines: list[str] = []
    lines.append("# DATACARD — corpus curated da BDTD")
    lines.append("")
    lines.append(
        "Corpus de chunks desnormalizados (um chunk por linha, com metadados "
        "completos do documento de origem embutidos), pronto para busca "
        "semântica/RAG sobre teses e dissertações da BDTD nas áreas de "
        "Computação, Informática e Informação."
    )
    lines.append("")
    if is_synthetic:
        lines.append(
            "> **Aviso:** este manifesto foi gerado a partir de **fixtures "
            "sintéticas** (sem coleta real da BDTD), usadas apenas para "
            "validar o pipeline offline. Os números abaixo não representam "
            "um corpus real."
        )
        lines.append("")

    lines.append("## Composição")
    lines.append("")
    lines.append(f"- Documentos completos (com texto e chunks): {curated_manifest['document_count']}")
    lines.append(f"- Chunks no dataset: {curated_manifest['chunk_count']}")
    lines.append(f"- Tokens médios por chunk: {avg_tokens:.1f}")
    lines.append(f"- Clusters após deduplicação: {dedup.get('clusters', 'n/d')}")
    lines.append(f"- Documentos descartados por duplicidade: {dedup.get('duplicates', 'n/d')}")
    lines.append("")
    lines.append("Status dos registros na camada processada de origem:")
    lines.append("")
    for status in ("completed", "no_text", "filtered", "duplicate", "skipped"):
        lines.append(f"- `{status}`: {status_counts.get(status, 0)}")
    lines.append("")

    lines.append("### Distribuição por idioma (chunks)")
    lines.append("")
    for language, count in languages.most_common():
        lines.append(f"- `{language}`: {count}")
    lines.append("")

    lines.append("### Distribuição por instituição (chunks)")
    lines.append("")
    for institution, count in institutions.most_common(10):
        lines.append(f"- {institution}: {count}")
    lines.append("")

    lines.append("## Como foi gerado")
    lines.append("")
    lines.append(
        "Pipeline: `raw` (coleta da API da BDTD) → `staging` (organização e "
        "normalização de metadados) → `processed` (extração de texto, "
        "limpeza, filtro de idioma/qualidade, deduplicação, anonimização de "
        "PII e chunking) → `curated` (desnormalização dos chunks com os "
        "metadados completos do documento)."
    )
    lines.append("")
    lines.append("Parâmetros de chunking usados na camada processada:")
    lines.append("")
    lines.append(f"- Tokens por chunk: {config.get('target_tokens', 'n/d')}")
    lines.append(f"- Sobreposição (overlap) entre chunks: {config.get('overlap', 'n/d')}")
    lines.append(f"- Tamanho mínimo de texto retido: {config.get('min_len', 'n/d')} caracteres")
    lines.append("")

    lines.append("## Esquema de cada linha de `datasets/chunks.jsonl`")
    lines.append("")
    lines.append(
        "Cada linha é um chunk autocontido: além do texto e da posição no "
        "documento, carrega os metadados completos da tese/dissertação de "
        "origem, para que um resultado de busca não precise de nenhum JOIN "
        "com outra tabela."
    )
    lines.append("")
    for field, description in _SCHEMA_FIELDS:
        lines.append(f"- `{field}`: {description}")
    lines.append("")

    lines.append("## Limitações conhecidas")
    lines.append("")
    for limitation in _LIMITATIONS:
        lines.append(f"- {limitation}")
    lines.append("")

    lines.append("## Uso pretendido")
    lines.append("")
    lines.append(
        "Indexação vetorial para busca semântica e RAG sobre o acervo da "
        "BDTD. Não recomendado como única fonte para decisões que exijam "
        "cobertura completa do acervo, dadas as perdas por filtro de "
        "qualidade/idioma e por deduplicação descritas acima."
    )
    lines.append("")

    return "\n".join(lines)


_SCHEMA_FIELDS = (
    ("chunk_id", "identificador único do chunk (`<bdtd_id>-chunk-<posição>`)"),
    ("bdtd_id", "identificador do documento de origem na BDTD"),
    ("cluster_id", "bdtd_id do documento canônico após deduplicação"),
    ("position", "índice do chunk dentro do documento, a partir de 0"),
    ("section", "seção do documento em que o chunk está (ex.: INTRODUÇÃO)"),
    ("page", "índice de seção usado como aproximação de página"),
    ("tokens", "número de tokens do chunk (tokenizador cl100k_base)"),
    ("text", "texto do chunk, já limpo e com PII anonimizada"),
    ("title", "título do documento"),
    ("alternative_title", "título alternativo, quando existir"),
    ("authors", "lista de autores"),
    ("abstract", "resumo do documento"),
    ("subjects", "lista de assuntos/palavras-chave"),
    ("date", "data de publicação (texto livre, como veio da fonte)"),
    ("document_type", "tipo de documento (ex.: Tese, Dissertação)"),
    ("language", "idioma declarado do documento"),
    ("institution", "instituição de defesa"),
    ("repository", "repositório de origem na BDTD"),
    ("access_rights", "direitos de acesso declarados"),
    ("source_url", "URL do PDF de origem"),
)


def _status_counts(records: Any) -> Counter[str]:
    counts: Counter[str] = Counter()
    if isinstance(records, Sequence):
        for record in records:
            if isinstance(record, Mapping):
                counts[str(record.get("status", ""))] += 1
    return counts


def _average(values: Any) -> float:
    values = list(values)
    return (sum(values) / len(values)) if values else 0.0
