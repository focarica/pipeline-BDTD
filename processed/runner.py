"""Orquestrador da camada processada da BDTD."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timezone
import hashlib
import json
import tempfile
from pathlib import Path
from typing import Any

from .anonymizer import Anonymizer, assert_no_pii
from .chunker import chunk_document
from .cleaner import clean_text
from .dataset import dataset_chunks, dataset_instruction, dataset_text
from .dedup import Deduplicator
from .extractor import extract
from .filter import filter_score
from .fixtures import build_fixtures
from .storage import ProcessedStorage
from .validation import ProcessedReport, validate_processed_manifest

_DATASET_FILES = (
    "datasets/text.jsonl",
    "datasets/chunks.jsonl",
    "datasets/instruction.jsonl",
)


class ProcessedRunner:
    """Coordena a extração, limpeza, deduplicação e serialização de datasets."""

    def __init__(
        self,
        raw_root: str | Path = "data/raw",
        out_root: str | Path = "data/processed",
        *,
        target_tokens: int = 1024,
        overlap: int = 128,
        min_len: int = 500,
        log: Callable[[str], None] = print,
    ) -> None:
        self.raw_root = Path(raw_root)
        self.storage = ProcessedStorage(out_root)
        self.target_tokens = target_tokens
        self.overlap = overlap
        self.min_len = min_len
        self._log = log
        self._anonymizer = Anonymizer()

    def run(self) -> tuple[dict[str, Any], ProcessedReport]:
        self._raw_base, is_fixtures = self._load_records()
        collection_path = self.raw_root / "manifests" / "collection.json" if not is_fixtures else None
        records = self._records
        self._log(f"processando {len(records)} registros da camada bruta")

        manifest_records: list[dict[str, Any]] = []
        candidates: list[dict[str, Any]] = []
        char_counts: list[int] = []

        for record in records:
            self._log(f"processando registro {record.get('bdtd_id', '?')}")
            if record.get("status") != "downloaded":
                manifest_records.append(
                    {
                        "bdtd_id": record.get("bdtd_id", ""),
                        "status": "skipped",
                        "reason": {"code": f"raw_{record.get('status', 'unknown')}"},
                    }
                )
                continue
            entry = self._process_downloaded(record, char_counts)
            if entry is None:
                continue
            if entry["status"] in ("no_text", "filtered"):
                manifest_records.append(entry)
            else:
                candidates.append(entry)

        completed_records: list[dict[str, Any]] = []
        deduplicator = Deduplicator()
        cluster_map = deduplicator.process(candidates)
        for candidate in candidates:
            rec_id = candidate["bdtd_id"]
            cluster_id = cluster_map[rec_id]
            if cluster_id != rec_id:
                manifest_records.append(
                    {
                        "bdtd_id": rec_id,
                        "status": "duplicate",
                        "metadata": candidate["metadata"],
                        "cluster_id": cluster_id,
                        "extraction": candidate["extraction"],
                    }
                )
                self._log(f"{rec_id}: duplicado do registro {cluster_id}")
                continue
            completed = self._complete_candidate(candidate, cluster_id)
            manifest_records.append(completed["manifest"])
            completed_records.append(completed["dataset"])
            self._log(f"{rec_id}: concluído com {completed['manifest']['chunk_count']} chunks")

        datasets = {
            "text": dataset_text(completed_records),
            "chunks": dataset_chunks(completed_records),
            "instruction": dataset_instruction(completed_records),
        }
        for name, entries in datasets.items():
            self.storage.save_dataset(name, entries)

        now = datetime.now(timezone.utc).isoformat()
        manifest: dict[str, Any] = {
            "created_at": now,
            "raw_manifest": str(collection_path) if collection_path is not None else "fixtures-sinteticas",
            "input_records": len(records),
            "datasets": list(_DATASET_FILES),
            "dedup": {
                "clusters": len(set(cluster_map.values())),
                "duplicates": sum(cluster != rec for rec, cluster in cluster_map.items()),
            },
            "config": {
                "target_tokens": self.target_tokens,
                "overlap": self.overlap,
                "min_len": self.min_len,
            },
            "records": manifest_records,
            "finished_at": now,
        }
        self.storage.save_manifest(manifest)
        report = validate_processed_manifest(manifest, root=self.storage.root)
        self._log(
            f"processamento encerrado: {report.completed} completos, {report.no_text} sem texto, "
            f"{report.filtered} filtrados, {report.duplicate} duplicados, {report.skipped} ignorados"
        )
        return manifest, report

    def _load_records(self) -> tuple[Path, bool]:
        collection_path = self.raw_root / "manifests" / "collection.json"
        if collection_path.exists():
            try:
                collection = json.loads(collection_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise RuntimeError(f"o manifesto bruto é inválido: {exc}") from exc
            raw_records = collection.get("records")
            if not isinstance(raw_records, list):
                raise RuntimeError("manifest.records deve ser uma lista")
            self._records = [
                record for record in raw_records if isinstance(record, Mapping)
            ]
            return self.raw_root, False
        self._log("dados brutos ausentes; gerando fixtures sintéticas para teste offline")
        fixture_root = Path(tempfile.mkdtemp(prefix="bdtd-fixtures-"))
        build_fixtures(fixture_root)
        collection = json.loads(
            (fixture_root / "manifests" / "collection.json").read_text(encoding="utf-8")
        )
        self._records = [
            record for record in collection.get("records", []) if isinstance(record, Mapping)
        ]
        return fixture_root, True

    def _process_downloaded(
        self, record: Mapping[str, Any], char_counts: list[int]
    ) -> dict[str, Any] | None:
        metadata = record.get("metadata") or {}
        base = {
            "bdtd_id": str(record.get("bdtd_id", "")),
            "metadata": metadata,
            "raw_record": record.get("raw_record") or {},
            "page": record.get("page"),
        }
        try:
            extraction = extract(self._pdf_path(record))
        except Exception as exc:
            self._log(f"{base['bdtd_id']}: falha na extração ({exc})")
            return {
                **base,
                "status": "no_text",
                "extraction": {"method": "pypdf", "page_count": 0, "char_count": 0},
                "reason": {"code": "extraction_failed"},
            }

        char_counts.append(extraction.char_count)
        extraction_report = {
            "method": extraction.method,
            "page_count": extraction.page_count,
            "char_count": extraction.char_count,
        }
        if not extraction.valid:
            self._log(f"{base['bdtd_id']}: texto insuficiente; marcando como sem texto")
            return {
                **base,
                "status": "no_text",
                "extraction": extraction_report,
                "reason": {"code": "empty_text"},
            }

        cleaned = clean_text(extraction.text)
        verdict = filter_score(cleaned, min_len=self.min_len)
        if not verdict.allowed:
            self._log(f"{base['bdtd_id']}: filtrado ({verdict.reason})")
            return {
                **base,
                "status": "filtered",
                "extraction": extraction_report,
                "reason": {
                    "code": verdict.reason,
                    "language": verdict.language,
                    "confidence": round(verdict.confidence, 4),
                    "char_count": verdict.char_count,
                    "repetition_ratio": round(verdict.repetition_ratio, 4),
                    "junk_ratio": round(verdict.junk_ratio, 4),
                },
            }

        return {
            **base,
            "status": "candidate",
            "extraction": extraction_report,
            "text": cleaned,
        }

    def _complete_candidate(
        self, candidate: Mapping[str, Any], cluster_id: str
    ) -> dict[str, Any]:
        rec_id = candidate["bdtd_id"]
        metadata = candidate["metadata"]
        anonymization_input = {**metadata, "raw_record": candidate["raw_record"]}
        text, redaction = self._anonymizer.anonymize(candidate["text"], anonymization_input)
        remaining = assert_no_pii(text)
        chunks = chunk_document(
            rec_id,
            text,
            target_tokens=self.target_tokens,
            overlap=self.overlap,
            title=str(metadata.get("title", "")),
        )
        text_path = self.storage.save_text(rec_id, text)
        chunks_path = self.storage.save_chunks(rec_id, chunks)
        manifest_entry = {
            "bdtd_id": rec_id,
            "status": "completed",
            "metadata": metadata,
            "extraction": candidate["extraction"],
            "cluster_id": cluster_id,
            "text_path": str(text_path.relative_to(self.storage.root)),
            "chunks_path": str(chunks_path.relative_to(self.storage.root)),
            "chunk_count": len(chunks),
            "sha256_text": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "redaction": redaction,
            "remaining_pii": remaining,
        }
        return {
            "manifest": manifest_entry,
            "dataset": {
                "bdtd_id": rec_id,
                "status": "completed",
                "metadata": metadata,
                "text": text,
                "chunks": chunks,
            },
        }

    def _pdf_path(self, record: Mapping[str, Any]) -> Path:
        document = record.get("document")
        if not isinstance(document, Mapping):
            raise RuntimeError("registro baixado sem informações do documento")
        path = Path(str(document.get("path", "")))
        return path if path.is_absolute() else self._raw_base / path