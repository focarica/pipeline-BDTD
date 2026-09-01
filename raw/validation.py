"""Verificações offline da coleta da BDTD."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlencode

from .common import DEFAULT_SEARCH_URL, INITIAL_QUERY_TERMS

_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_STATUSES = frozenset({"downloaded", "duplicate", "restricted", "unavailable"})


@dataclass(frozen=True)
class ValidationIssue:
    """Um problema encontrado no manifesto."""

    code: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Resumo das verificações e dos problemas encontrados."""

    record_count: int
    downloaded_count: int
    skipped_count: int
    duplicate_count: int
    issues: tuple[ValidationIssue, ...]

    @property
    def valid(self) -> bool:
        return not self.issues


def initial_query_params() -> tuple[tuple[str, str], ...]:
    """Retorna a busca inicial como parâmetros ``AllFields`` repetidos em OR."""

    params: list[tuple[str, str]] = [("join", "AND"), ("bool0[]", "OR")]
    
    for term in INITIAL_QUERY_TERMS:
        params.extend((("lookfor0[]", term), ("type0[]", "AllFields")))
    
    params.extend(
        (
            ("illustration", "-1"),
            ("daterange[]", "publishDate"),
            ("publishDatefrom", ""),
            ("publishDateto", ""),
            ("sort", "year"),
        )
    )
    return tuple(params)


def build_initial_query_url(base_url: str = DEFAULT_SEARCH_URL) -> str:
    """Monta o formato exato da consulta usada."""

    return f"{base_url}?{urlencode(initial_query_params())}"


def is_valid_pdf_payload(content_type: str, payload: bytes) -> bool:
    """Verifica o MIME e a assinatura básica do PDF antes de salvar o arquivo."""

    mime_type = content_type.split(";", 1)[0].strip().casefold()
    return (
        mime_type == "application/pdf"
        and payload.startswith(b"%PDF-")
        and b"%%EOF" in payload[-1024:]
    )


def validate_pilot_manifest(
    manifest: Mapping[str, Any],
    *,
    min_records: int = 1,
    max_records: int | None = None,
) -> ValidationReport:
    """Valida apenas a estrutura básica do manifesto da coleta.

    Registros restritos, indisponíveis e duplicados não são considerados falhas.
    """

    issues: list[ValidationIssue] = []
    _require_nonempty_string(manifest.get("query"), "query", issues)

    raw_records = manifest.get("records")
    if not isinstance(raw_records, Sequence) or isinstance(raw_records, (str, bytes)):
        issues.append(ValidationIssue("records", "manifest.records deve ser uma lista"))
        return ValidationReport(0, 0, 0, 0, tuple(issues))

    record_count = len(raw_records)
    if record_count < min_records or (max_records is not None and record_count > max_records):
        issues.append(
            ValidationIssue(
                "pilot_size",
                f"a coleta deve conter pelo menos {min_records} registro(s); encontrado: {record_count}",
            )
        )

    records: list[Mapping[str, Any]] = []
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, Mapping):
            issues.append(ValidationIssue("record", f"records[{index}] deve ser um objeto"))
            continue
        records.append(raw_record)

    duplicate_count = 0
    skipped_count = 0

    for index, record in enumerate(records):
        prefix = f"records[{index}]"

        status = record.get("status")
        if status not in _STATUSES:
            issues.append(
                ValidationIssue(
                    "status",
                    f"{prefix}.status deve ser um destes valores: {sorted(_STATUSES)}",
                )
            )
            continue

        if status == "downloaded":
            document = record.get("document")
            if not isinstance(document, Mapping):
                issues.append(
                    ValidationIssue("document", f"{prefix}.document deve ser um objeto")
                )
                continue
            _validate_document(document, prefix, issues)
        elif status == "duplicate":
            duplicate_count += 1
            skipped_count += 1
        else:
            skipped_count += 1

    return ValidationReport(
        record_count=record_count,
        downloaded_count=sum(record.get("status") == "downloaded" for record in records),
        skipped_count=skipped_count,
        duplicate_count=duplicate_count,
        issues=tuple(issues),
    )


def _validate_document(
    document: Mapping[str, Any], prefix: str, issues: list[ValidationIssue]
) -> None:
    for field in ("source_url", "sha256", "byte_count"):
        if field not in document:
            issues.append(ValidationIssue("document_field", f"{prefix}.document.{field} é obrigatório"))

    for field in ("source_url", "sha256"):
        if field in document:
            _require_nonempty_string(document[field], f"{prefix}.document.{field}", issues)

    byte_count = document.get("byte_count")
    if not isinstance(byte_count, int) or isinstance(byte_count, bool) or byte_count < 1:
        issues.append(ValidationIssue("byte_count", f"{prefix}.document.byte_count deve ser positivo"))

    checksum = document.get("sha256")
    if not isinstance(checksum, str) or not _SHA256_PATTERN.fullmatch(checksum):
        issues.append(ValidationIssue("checksum", f"{prefix}.document.sha256 deve ser um digest hexadecimal SHA-256"))

    if "pdf_valid" in document and document["pdf_valid"] is not True:
        issues.append(ValidationIssue("pdf", f"{prefix}.document.pdf_valid deve ser true"))


def _require_nonempty_string(
    value: object, field: str, issues: list[ValidationIssue]
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        issues.append(ValidationIssue("required", f"{field} deve ser uma string não vazia"))
        return None
    return value.strip()
