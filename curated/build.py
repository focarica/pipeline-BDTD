"""Construção da camada curated a partir da camada processada da BDTD."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .datacard import render_datacard
from .storage import CuratedStorage


@dataclass(frozen=True)
class CuratedReport:
    document_count: int
    chunk_count: int
    missing_chunks: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing_chunks


def build_curated(
    processed_root: str | Path,
    curated_root: str | Path,
    *,
    log: Callable[[str], None] = print,
) -> CuratedReport:
    processed_root = Path(processed_root)
    storage = CuratedStorage(curated_root)

    manifest_path = processed_root / "manifests" / "processed.json"
    try:
        processed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RuntimeError(f"manifesto processado não encontrado em {manifest_path}") from exc
    except ValueError as exc:
        raise RuntimeError(f"manifesto processado inválido: {exc}") from exc

    records = [
        record for record in processed_manifest.get("records", []) if isinstance(record, Mapping)
    ]
    completed = [record for record in records if record.get("status") == "completed"]
    log(f"montando curated a partir de {len(completed)} documentos completos")

    chunk_rows: list[dict[str, Any]] = []
    missing_chunks: list[str] = []
    for record in completed:
        bdtd_id = str(record.get("bdtd_id", ""))
        rows = _load_chunk_rows(processed_root, record, log)
        if rows is None:
            missing_chunks.append(bdtd_id)
            continue
        chunk_rows.extend(rows)

    storage.save_dataset("chunks", chunk_rows)

    now = datetime.now(timezone.utc).isoformat()
    curated_manifest = {
        "created_at": now,
        "processed_manifest": str(manifest_path),
        "document_count": len(completed),
        "chunk_count": len(chunk_rows),
        "missing_chunks": sorted(missing_chunks),
    }
    storage.save_manifest(curated_manifest)
    storage.save_datacard(render_datacard(processed_manifest, curated_manifest, chunk_rows))

    log(
        f"curated pronto: {len(completed)} documentos, {len(chunk_rows)} chunks, "
        f"{len(missing_chunks)} sem chunks"
    )
    return CuratedReport(
        document_count=len(completed),
        chunk_count=len(chunk_rows),
        missing_chunks=tuple(sorted(missing_chunks)),
    )


def _load_chunk_rows(
    processed_root: Path, record: Mapping[str, Any], log: Callable[[str], None]
) -> list[dict[str, Any]] | None:
    bdtd_id = str(record.get("bdtd_id", ""))
    chunks_path = record.get("chunks_path")
    if not isinstance(chunks_path, str) or not chunks_path:
        log(f"{bdtd_id}: sem chunks_path no manifesto processado; ignorando")
        return None
    try:
        lines = (processed_root / chunks_path).read_text(encoding="utf-8").splitlines()
    except OSError:
        log(f"{bdtd_id}: chunks_path não encontrado em disco ({chunks_path}); ignorando")
        return None

    metadata = record.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    cluster_id = record.get("cluster_id", bdtd_id)

    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        chunk = json.loads(line)
        rows.append(_denormalize_chunk(chunk, bdtd_id, cluster_id, metadata))
    return rows


def _denormalize_chunk(
    chunk: Mapping[str, Any],
    bdtd_id: str,
    cluster_id: Any,
    metadata: Mapping[str, Any],
) -> dict[str, Any]:
    """Combina um chunk com os metadados completos do documento de origem.

    Cada linha resultante é autocontida: quem consome um chunk isolado (busca
    semântica, RAG) não precisa voltar ao documento original para saber quem
    escreveu, quando, em que instituição ou sob quais direitos de acesso.
    """
    return {
        "chunk_id": chunk.get("id", ""),
        "bdtd_id": bdtd_id,
        "cluster_id": cluster_id,
        "position": chunk.get("position", 0),
        "section": chunk.get("section", ""),
        "page": chunk.get("page", 1),
        "tokens": chunk.get("tokens", 0),
        "text": chunk.get("text", ""),
        "title": metadata.get("title", ""),
        "alternative_title": metadata.get("alternative_title", ""),
        "authors": metadata.get("authors", []),
        "abstract": metadata.get("abstract", ""),
        "subjects": metadata.get("subjects", []),
        "date": metadata.get("date", ""),
        "document_type": metadata.get("document_type", ""),
        "language": metadata.get("language", ""),
        "institution": metadata.get("institution", ""),
        "repository": metadata.get("repository", ""),
        "access_rights": metadata.get("access_rights", ""),
        "source_url": metadata.get("source_url", ""),
    }
