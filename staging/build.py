from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class StagingReport:
    record_count: int
    downloaded_count: int
    missing_files: tuple[str, ...] = ()
    orphan_files: tuple[str, ...] = ()
    content_type_mismatches: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing_files


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
        },
    }
    (staging_root / "staging.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    log(
        f"staging pronto: {len(staged)} registros, {downloaded} baixados, "
        f"{len(missing)} arquivos ausentes, {len(orphans)} órfãos, "
        f"{len(mismatches)} content-types divergentes"
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
    )


def _stage_record(raw_root: Path, record: Mapping[str, Any], log: Callable[[str], None]) -> _StagingRecord:
    data: dict[str, Any] = {
        "bdtd_id": record.get("bdtd_id", ""),
        "status": record.get("status", ""),
        "reason": record.get("reason", ""),
        "reason_detail": record.get("reason_detail", ""),
        "page": record.get("page"),
        "record_url": record.get("record_url", ""),
        "repository": record.get("repository", ""),
        "metadata": record.get("metadata", {}),
    }
    referenced: str | None = None
    document = record.get("document")
    if isinstance(document, Mapping) and record.get("status") == "downloaded":
        staged_doc = dict(document)
        real, mismatch = _sniff_document(raw_root, document)
        staged_doc["content_type_header"] = document.get("content_type", "")
        staged_doc["content_type_real"] = real
        staged_doc["content_type_mismatch"] = mismatch
        if mismatch:
            log(f"{record.get('bdtd_id')}: content-type divergente (header x arquivo)")
        data["document"] = staged_doc
        path = document.get("path")
        if isinstance(path, str) and path:
            referenced = path
    return _StagingRecord(data=data, referenced_path=referenced)


def _sniff_document(raw_root: Path, document: Mapping[str, Any]) -> tuple[str, bool]:
    header = str(document.get("content_type", ""))
    path = document.get("path")
    if not isinstance(path, str) or not path:
        return ("unknown", True)
    try:
        with open(raw_root / path, "rb") as fh:
            real = detect_content_type(fh.read(8))
    except OSError:
        return ("unknown", True)
    base_header = header.split(";", 1)[0].strip().casefold()
    mismatch = bool(base_header) and base_header != real
    return (real, mismatch)
