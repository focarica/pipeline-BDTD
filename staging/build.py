from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from .normalize import fix_text, normalize_metadata


@dataclass(frozen=True)
class StagingReport:
    record_count: int
    downloaded_count: int
    missing_files: tuple[str, ...] = ()
    orphan_files: tuple[str, ...] = ()
    content_type_mismatches: tuple[str, ...] = ()
    checksum_mismatches: tuple[str, ...] = ()
    duplicate_ids: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not (
            self.missing_files
            or self.content_type_mismatches
            or self.checksum_mismatches
            or self.duplicate_ids
        )


@dataclass
class _StagingRecord:
    data: dict[str, Any]
    referenced_path: str | None = None


def detect_content_type(payload_start: bytes) -> str:
    if payload_start.startswith(b"%PDF-"):
        return "application/pdf"
    if payload_start.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload_start.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload_start.startswith(b"PK\x03\x04"):
        return "application/zip"
    if payload_start.startswith(b"%!PS"):
        return "application/postscript"
    return "application/octet-stream"


def build_staging(
    raw_root: str | Path,
    staging_root: str | Path,
    *,
    log: Callable[[str], None] = print,
) -> StagingReport:
    raw_root = Path(raw_root)
    staging_root = Path(staging_root)
    records_dir = staging_root / "records"
    records_dir.mkdir(parents=True, exist_ok=True)

    raw_records = sorted((raw_root / "manifests" / "records").glob("*.json"))
    log(f"montando staging a partir de {len(raw_records)} registros do raw")

    staged: list[_StagingRecord] = []
    for path in raw_records:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            log(f"registro ilegível, ignorando: {path.name}")
            continue
        if not isinstance(record, Mapping):
            continue
        staged.append(_stage_record(raw_root, record, log))

    staged, duplicate_ids = _drop_duplicate_ids(staged, log)

    for entry in staged:
        record_id = entry.data["bdtd_id"]
        (records_dir / f"{record_id}.json").write_text(
            json.dumps(entry.data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    referenced = {e.referenced_path for e in staged if e.referenced_path}
    on_disk = {
        str(p.relative_to(raw_root))
        for p in (raw_root / "documents").rglob("*")
        if p.is_file()
    }
    missing = sorted(referenced - on_disk)
    orphans = sorted(on_disk - referenced)
    mismatches = sorted(
        e.data["bdtd_id"]
        for e in staged
        if e.data.get("document", {}).get("content_type_mismatch")
    )
    checksum_mismatches = sorted(
        e.data["bdtd_id"]
        for e in staged
        if e.data.get("document", {}).get("checksum_mismatch")
    )

    collection_path = raw_root / "manifests" / "collection.json"
    query = ""
    try:
        collection = json.loads(collection_path.read_text(encoding="utf-8"))
        if isinstance(collection, Mapping):
            query = str(collection.get("query", ""))
    except (OSError, ValueError):
        query = ""

    downloaded = sum(1 for e in staged if e.data["status"] == "downloaded")
    manifest = {
        "query": query,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "raw_root": str(raw_root),
        "record_count": len(staged),
        "downloaded_count": downloaded,
        "integrity": {
            "missing_files": missing,
            "orphan_files": orphans,
            "content_type_mismatches": mismatches,
            "checksum_mismatches": checksum_mismatches,
            "duplicate_ids": duplicate_ids,
        },
    }
    (staging_root / "staging.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    log(
        f"staging pronto: {len(staged)} registros, {downloaded} baixados, "
        f"{len(missing)} arquivos ausentes, {len(orphans)} órfãos, "
        f"{len(mismatches)} content-types divergentes, "
        f"{len(checksum_mismatches)} checksums divergentes, "
        f"{len(duplicate_ids)} bdtd_id duplicados"
    )
    for path in missing:
        log(f"arquivo ausente: {path}")
    for path in orphans:
        log(f"arquivo órfão: {path}")
    return StagingReport(
        record_count=len(staged),
        downloaded_count=downloaded,
        missing_files=tuple(missing),
        orphan_files=tuple(orphans),
        content_type_mismatches=tuple(mismatches),
        checksum_mismatches=tuple(checksum_mismatches),
        duplicate_ids=tuple(duplicate_ids),
    )


def _drop_duplicate_ids(
    staged: list[_StagingRecord], log: Callable[[str], None]
) -> tuple[list[_StagingRecord], list[str]]:
    """Mantém a primeira ocorrência de cada bdtd_id e reporta as demais como duplicatas.

    Sem isso, um bdtd_id repetido faria a segunda gravação sobrescrever
    silenciosamente o arquivo da primeira em staging/records/.
    """
    seen: set[str] = set()
    unique: list[_StagingRecord] = []
    duplicates: list[str] = []
    for entry in staged:
        record_id = str(entry.data["bdtd_id"])
        if record_id in seen:
            duplicates.append(record_id)
            log(f"{record_id}: bdtd_id duplicado no staging; mantendo a primeira ocorrência")
            continue
        seen.add(record_id)
        unique.append(entry)
    return unique, sorted(set(duplicates))


def _stage_record(raw_root: Path, record: Mapping[str, Any], log: Callable[[str], None]) -> _StagingRecord:
    raw_metadata = record.get("metadata")
    data: dict[str, Any] = {
        "bdtd_id": record.get("bdtd_id", ""),
        "status": record.get("status", ""),
        "reason": record.get("reason", ""),
        "reason_detail": record.get("reason_detail", ""),
        "page": record.get("page"),
        "record_url": record.get("record_url", ""),
        "repository": fix_text(str(record.get("repository", ""))),
        "metadata": normalize_metadata(raw_metadata) if isinstance(raw_metadata, Mapping) else {},
    }
    referenced: str | None = None
    document = record.get("document")
    if isinstance(document, Mapping) and record.get("status") == "downloaded":
        staged_doc = dict(document)
        real, content_type_mismatch, checksum_mismatch = _inspect_document(raw_root, document)
        staged_doc["content_type_header"] = document.get("content_type", "")
        staged_doc["content_type_real"] = real
        staged_doc["content_type_mismatch"] = content_type_mismatch
        staged_doc["checksum_mismatch"] = checksum_mismatch
        if content_type_mismatch:
            log(f"{record.get('bdtd_id')}: content-type divergente (header x arquivo)")
        if checksum_mismatch:
            log(f"{record.get('bdtd_id')}: sha256 divergente do declarado no raw (arquivo pode estar corrompido)")
        data["document"] = staged_doc
        path = document.get("path")
        if isinstance(path, str) and path:
            referenced = path
    return _StagingRecord(data=data, referenced_path=referenced)


def _inspect_document(raw_root: Path, document: Mapping[str, Any]) -> tuple[str, bool, bool]:
    """Lê o arquivo referenciado e confere content-type e sha256 contra o raw.

    Retorna (content_type_real, content_type_mismatch, checksum_mismatch).
    Um documento sem `path` registrado conta como divergência (não há outro
    jeito de sinalizar esse problema); um `path` que não abre no disco não é
    contado aqui de novo — já aparece em `missing_files`.
    """
    header = str(document.get("content_type", ""))
    path = document.get("path")
    if not isinstance(path, str) or not path:
        return ("unknown", True, True)
    try:
        payload = (raw_root / path).read_bytes()
    except OSError:
        return ("unknown", False, False)

    real = detect_content_type(payload[:8])
    base_header = header.split(";", 1)[0].strip().casefold()
    content_type_mismatch = bool(base_header) and base_header != real

    declared_checksum = str(document.get("sha256", "")).strip().casefold()
    actual_checksum = hashlib.sha256(payload).hexdigest()
    checksum_mismatch = bool(declared_checksum) and declared_checksum != actual_checksum

    return (real, content_type_mismatch, checksum_mismatch)
