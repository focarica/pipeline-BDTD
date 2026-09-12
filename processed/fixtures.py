"""Fixtures sintéticas para testar a camada processada offline."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

_FIXTURE_TEXT = """1 INTRODUÇÃO
Esta pesquisa investiga o uso de aprendizado de máquina em sistemas de
informação no Brasil, com foco nas áreas de computação, informática e
informação. O problema central é a ausência de corpora abertos em língua
portuguesa para pré-treinamento de modelos de linguagem de pequeno porte.
A autora pode ser contatada pelo email maria.silva@exemplo.com e pelo
telefone (61) 99876-5432. O repositório da instituição está disponível em
https://repositorio.exemplo.br/teses e o servidor de apoio usa o endereço
192.168.0.1.
O CPF do responsável pela liberação é 123.456.789-00, o RG é 12.345.678-9 e
o CEP da sede é 70910-900. O orientador responsável é João Pedro de Almeida
e a autora Maria da Silva Santos desenvolveu o trabalho em Brasília, sob a
supervisão da Professora Ana Clara Nogueira.
2 FUNDAMENTAÇÃO TEÓRICA
A fundamentação reúne trabalhos sobre arquiteturas transformer, mecanismos
de atenção, posicionamentos relativos e estratégias de janela deslizante.
São discutidas métricas de avaliação como perplexidade e acurácia, além de
aspectos de eficiência computacional para treinamento em uma única GPU.
3 METODOLOGIA
A metodologia propõe a coleta automatizada de teses da Biblioteca Digital
Brasileira de Teses e Dissertações, seguida por limpeza, anonimização,
formação de chunks com sobreposição e geração de datasets de pré-treinamento,
instrucional e de recuperação.
4 CONCLUSÃO
A conclusão reforça que a disponibilidade de dados tratados em português é
essencial para o avanço de modelos abertos e reprodutíveis no contexto
brasileiro de pesquisa.
REFERÊNCIAS BIBLIOGRÁFICAS
VASWANI, A. Attention is all you need. Advances in Neural Information
Processing Systems, 2017.
"""

_FIXTURE_NEAR_DUPLICATE = _FIXTURE_TEXT.replace(
    "em Brasília, sob a supervisão", "em Goiânia, sob a orientacao"
) + " Esta versão acrescenta uma consideração final adicional ao texto.\n"


def build_fixtures(raw_root: str | Path) -> Path:
    """Gera uma coleção bruta sintética e retorna o caminho do manifesto."""
    root = Path(raw_root)
    documents = root / "documents"
    records = root / "manifests" / "records"
    documents.mkdir(parents=True, exist_ok=True)
    records.mkdir(parents=True, exist_ok=True)

    base = {
        "bdtd_id": "fixture-a",
        "record_url": "https://bdtd.ibict.br/vufind/Record/fixture-a",
        "page": 1,
        "repository": "Exemplo",
        "metadata": {
            "title": "Aprendizado de máquina em sistemas de informação",
            "alternative_title": "",
            "authors": ["Maria da Silva Santos"],
            "abstract": "Pesquisa sobre aprendizado de máquina.",
            "subjects": ["Computação", "Informação"],
            "date": "2024",
            "document_type": "Tese",
            "language": "pt",
            "institution": "Universidade Exemplo",
            "repository": "Exemplo",
            "access_rights": "open access",
            "source_url": "https://repositorio.exemplo.br/teses/a.pdf",
        },
        "raw_record": {
            "authors": {"primary": ["Maria da Silva Santos"]},
            "orientador": "João Pedro de Almeida",
            "coorientador": "Ana Clara Nogueira",
            "institutions": ["Universidade Exemplo"],
            "urls": [{"url": "https://repositorio.exemplo.br/teses/a.pdf"}],
        },
    }
    entries: list[dict[str, Any]] = [_fixture_record(base, _FIXTURE_TEXT, records, documents)]

    near = dict(base)
    near["bdtd_id"] = "fixture-b"
    near["metadata"] = {**base["metadata"], "title": "Aprendizado de máquina (versão 2)"}
    entries.append(_fixture_record(near, _FIXTURE_NEAR_DUPLICATE, records, documents))

    scanned = dict(base)
    scanned["bdtd_id"] = "fixture-c"
    entries.append(_fixture_record(scanned, "x", records, documents))

    english = dict(base)
    english["bdtd_id"] = "fixture-d"
    english["metadata"] = {**base["metadata"], "title": "Machine learning survey"}
    entries.append(
        _fixture_record(
            english,
            _english_text(),
            records,
            documents,
        )
    )

    restricted = dict(base)
    restricted["bdtd_id"] = "fixture-e"
    restricted["status"] = "restricted"
    restricted["metadata"] = {**base["metadata"], "access_rights": "restricted"}
    entries.append(_fixture_record(restricted, None, records, documents))

    collection = {
        "query": "https://bdtd.ibict.br/vufind/Search/Results?fixtures=1",
        "query_params": [{"name": "fixtures", "value": "1"}],
        "started_at": "2026-01-01T00:00:00+00:00",
        "finished_at": "2026-01-01T00:01:00+00:00",
        "pages": [1],
        "records": entries,
    }
    manifest = root / "manifests" / "collection.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(
        json.dumps(collection, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest


def _fixture_record(
    data: dict[str, Any],
    text: str | None,
    records_dir: Path,
    documents_dir: Path,
) -> dict[str, Any]:
    record = dict(data)
    status = record.get("status", "downloaded")
    if status != "downloaded" or text is None:
        record["status"] = status
        record.pop("document", None)
        _write_json(records_dir / f"{record['bdtd_id']}.json", record)
        return record

    pdf_bytes = _build_pdf_bytes(text)
    record_id = record["bdtd_id"]
    relative = f"documents/{record_id}/{record_id}.pdf"
    target = documents_dir / record_id / f"{record_id}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(pdf_bytes)
    record["status"] = "downloaded"
    record["document"] = {
        "source_url": record.get("metadata", {}).get("source_url", ""),
        "final_url": record.get("metadata", {}).get("source_url", ""),
        "retrieved_at": "2026-01-01T00:00:00+00:00",
        "http_status": 200,
        "content_type": "application/pdf",
        "original_filename": f"{record_id}.pdf",
        "byte_count": len(pdf_bytes),
        "sha256": hashlib.sha256(pdf_bytes).hexdigest(),
        "pdf_valid": True,
        "path": relative,
    }
    _write_json(records_dir / f"{record_id}.json", record)
    return record


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _english_text() -> str:
    return (
        "This survey reviews machine learning methods applied to information retrieval. "
        "We discuss supervised and unsupervised approaches, evaluation metrics and "
        "open research challenges. The field has grown rapidly in recent years, driven "
        "by large datasets, faster hardware and new model architectures. Several works "
        "compare transformer-based encoders with classical bag-of-words baselines. "
        "Future directions include multilingual models, efficient attention mechanisms "
        "and better evaluation protocols for low-resource languages."
    )


def _build_pdf_bytes(text: str) -> bytes:
    lines = _pdf_lines(text)
    content = (
        b"BT\n/F1 12 Tf\n72 720 Td\n15 TL\n"
        + b"\n".join(
            b"(" + line.encode("latin-1", errors="replace") + b") Tj\nT*" for line in lines
        )
        + b"\nET"
    )

    bodies = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        (
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
            b"/Encoding /WinAnsiEncoding >>"
        ),
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
        + content
        + b"\nendstream",
    ]

    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, body in enumerate(bodies, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n" % index + body + b"\nendobj\n"

    xref_position = len(output)
    output += b"xref\n0 6\n"
    output += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        output += b"%010d 00000 n \n" % offset
    output += (
        b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"
        + str(xref_position).encode()
        + b"\n%%EOF"
    )
    return bytes(output)


def _pdf_lines(text: str) -> list[str]:
    return [
        re.sub(r"\s+", " ", line.strip())
        for line in text.splitlines()
        if line.strip()
    ]