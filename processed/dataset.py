
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_SECTION_TEMPLATES = (
    (("INTRODU", "INTRO"), "Resuma a introdução do documento intitulado {title}."),
    (("CONCLUSÃO", "CONSIDERAÇÕES FINAIS"), "Resuma a conclusão do documento intitulado {title}."),
    (("METODOLOGIA", "MÉTODO"), "Descreva a metodologia apresentada no documento intitulado {title}."),
)
_DEFAULT_TEMPLATE = "Resuma o documento intitulado {title}."


def _completed(records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [record for record in records if record.get("status") == "completed"]


def dataset_text(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gera entradas para o pré-treinamento contínuo (texto + resumo de metadados)."""
    entries: list[dict[str, Any]] = []
    for record in _completed(records):
        entries.append(
            {
                "id": record["bdtd_id"],
                "text": record["text"],
                "metadata": _metadata_summary(record),
            }
        )
    return entries


def dataset_chunks(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gera entradas para RAG e benchmarks (documento + chunks)."""
    entries: list[dict[str, Any]] = []
    for record in _completed(records):
        metadata = record.get("metadata") or {}
        entries.append(
            {
                "id": record["bdtd_id"],
                "title": metadata.get("title", ""),
                "chunks": record["chunks"],
            }
        )
    return entries


def dataset_instruction(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Gera entradas no formato instrucional a partir de cada chunk."""
    entries: list[dict[str, Any]] = []
    for record in _completed(records):
        metadata = record.get("metadata") or {}
        title = metadata.get("title", "")
        for chunk in record["chunks"]:
            entries.append(
                {
                    "instruction": _instruction_for(title, chunk.get("section", "")),
                    "input": chunk.get("text", ""),
                    "output": "",
                }
            )
    return entries


def _metadata_summary(record: Mapping[str, Any]) -> dict[str, Any]:
    metadata = record.get("metadata") or {}
    return {
        "title": metadata.get("title", ""),
        "authors": metadata.get("authors", []),
        "date": metadata.get("date", ""),
        "subjects": metadata.get("subjects", []),
        "institution": metadata.get("institution", ""),
        "repository": metadata.get("repository", ""),
    }


def _instruction_for(title: str, section: str) -> str:
    upper = section.upper()
    for markers, template in _SECTION_TEMPLATES:
        if any(marker in upper for marker in markers):
            return template.format(title=title)
    return _DEFAULT_TEMPLATE.format(title=title)