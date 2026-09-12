"""Verificações offline da camada processada."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any

_STATUSES = frozenset({"completed", "no_text", "filtered", "duplicate", "skipped"})

_QUALITY_BUCKETS = ("<500", "500-5000", "5000-20000", ">20000")


@dataclass(frozen=True)
class ProcessedIssue:
    """Um problema encontrado no manifesto processado."""

    code: str
    message: str


@dataclass(frozen=True)
class ProcessedReport:
    """Resumo das verificações da camada processada."""

    total: int
    completed: int
    no_text: int
    filtered: int
    duplicate: int
    skipped: int
    dedup_clusters: int
    remaining_pii: dict[str, int]
    redactions: dict[str, int]
    quality_histogram: dict[str, int]
    issues: tuple[ProcessedIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def validate_processed_manifest(
    manifest: Mapping[str, Any],
    *,
    root: str | Path = "data/processed",
) -> ProcessedReport:
    """Valida a estrutura e a consistência do manifesto processado."""
    issues: list[ProcessedIssue] = []
    if not isinstance(manifest, Mapping):
        return _empty_report(
            (ProcessedIssue("manifest", "o manifesto processado deve ser um objeto"),)
        )

    raw_records = manifest.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        issues.append(ProcessedIssue("records", "manifest.records deve ser uma lista"))
        return _empty_report(tuple(issues))

    records: list[Mapping[str, Any]] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            issues.append(ProcessedIssue("record", f"records[{index}] deve ser um objeto"))
            continue
        records.append(raw_record)

    completed = no_text = filtered = duplicate = skipped = 0
    remaining_pii: dict[str, int] = {}
    redactions: dict[str, int] = {}
    char_counts: list[int] = []

    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        status = record.get("status")
        if status not in _STATUSES:
            issues.append(
                ProcessedIssue(
                    "status",
                    f"{prefix}.status deve ser um destes valores: {sorted(_STATUSES)}",
                )
            )
            continue

        _merge_counts(remaining_pii, record.get("remaining_pii"))
        _merge_counts(redactions, record.get("redaction"))

        extraction = record.get("extraction")
        if isinstance(extraction, Mapping):
            char_count = extraction.get("char_count")
            if isinstance(char_count, int):
                char_counts.append(char_count)

        if status == "completed":
            completed += 1
            _validate_completed(record, prefix, Path(root), issues)
        elif status == "no_text":
            no_text += 1
        elif status == "filtered":
            filtered += 1
            if not record.get("reason"):
                issues.append(ProcessedIssue("reason", f"{prefix}.reason deve existir"))
        elif status == "duplicate":
            duplicate += 1
            if not record.get("cluster_id"):
                issues.append(ProcessedIssue("cluster_id", f"{prefix}.cluster_id deve existir"))
        else:
            skipped += 1

    dataset_paths = manifest.get("datasets")
    if isinstance(dataset_paths, Sequence) and not isinstance(dataset_paths, (str, bytes)):
        for path in dataset_paths:
            _require_file(Path(root) / str(path), f"manifest.datasets:{path}", issues)
    else:
        issues.append(ProcessedIssue("datasets", "manifest.datasets deve ser uma lista"))

    dedup = manifest.get("dedup")
    dedup_clusters = 0
    if isinstance(dedup, Mapping):
        value = dedup.get("clusters")
        if isinstance(value, int):
            dedup_clusters = value

    return ProcessedReport(
        total=len(records),
        completed=completed,
        no_text=no_text,
        filtered=filtered,
        duplicate=duplicate,
        skipped=skipped,
        dedup_clusters=dedup_clusters,
        remaining_pii=remaining_pii,
        redactions=redactions,
        quality_histogram=_histogram(char_counts),
        issues=tuple(issues),
    )


def _validate_completed(
    record: Mapping[str, Any],
    prefix: str,
    root: Path,
    issues: list[ProcessedIssue],
) -> None:
    text_path = record.get("text_path")
    if isinstance(text_path, str):
        file_path = root / text_path
        if not file_path.exists():
            issues.append(ProcessedIssue("text_path", f"{prefix}.text_path não existe: {text_path}"))
        else:
            stored = file_path.read_text(encoding="utf-8", errors="replace")
            if not stored.strip():
                issues.append(ProcessedIssue("text_path", f"{prefix}.text_path está vazio"))
            checksum = record.get("sha256_text")
            if isinstance(checksum, str):
                computed = hashlib.sha256(stored.encode("utf-8")).hexdigest()
                if computed != checksum:
                    issues.append(
                        ProcessedIssue("sha256_text", f"{prefix}.sha256_text não confere")
                    )
    else:
        issues.append(ProcessedIssue("text_path", f"{prefix}.text_path é obrigatório"))

    chunks_path = record.get("chunks_path")
    chunk_count = record.get("chunk_count")
    if isinstance(chunks_path, str):
        file_path = root / chunks_path
        if not file_path.exists():
            issues.append(ProcessedIssue("chunks_path", f"{prefix}.chunks_path não existe: {chunks_path}"))
            return
        lines = [line for line in file_path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            issues.append(ProcessedIssue("chunks_path", f"{prefix}.chunks_path está vazio"))
        if isinstance(chunk_count, int) and len(lines) != chunk_count:
            issues.append(
                ProcessedIssue(
                    "chunk_count",
                    f"{prefix}.chunk_count ({chunk_count}) não confere com o arquivo ({len(lines)})",
                )
            )
    else:
        issues.append(ProcessedIssue("chunks_path", f"{prefix}.chunks_path é obrigatório"))


def _require_file(path: Path, label: str, issues: list[ProcessedIssue]) -> None:
    if not path.exists():
        issues.append(ProcessedIssue("missing_file", f"{label} não existe"))


def _merge_counts(target: dict[str, int], value: object) -> None:
    if not isinstance(value, Mapping):
        return
    for key, count in value.items():
        if isinstance(count, int):
            target[key] = target.get(key, 0) + count


def _histogram(char_counts: list[int]) -> dict[str, int]:
    buckets = {name: 0 for name in _QUALITY_BUCKETS}
    for count in char_counts:
        if count < 500:
            buckets["<500"] += 1
        elif count < 5000:
            buckets["500-5000"] += 1
        elif count < 20000:
            buckets["5000-20000"] += 1
        else:
            buckets[">20000"] += 1
    return buckets


def _empty_report(issues: tuple[ProcessedIssue, ...]) -> ProcessedReport:
    return ProcessedReport(
        total=0,
        completed=0,
        no_text=0,
        filtered=0,
        duplicate=0,
        skipped=0,
        dedup_clusters=0,
        remaining_pii={},
        redactions={},
        quality_histogram={},
        issues=issues,
    )