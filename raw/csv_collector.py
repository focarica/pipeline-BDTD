"""Coleta limitada de registros exportados da busca BDTD em CSV."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any
from urllib.parse import urlsplit

from .collector import (
    PilotCollector,
    _canonical_source_url,
    _downloaded_count,
)
from .validation import build_initial_query_url, initial_query_params, validate_pilot_manifest

_TOPIC_TERMS = ("computacao", "informatica", "informacao")
_TOPIC_FIELDS = (
    "Título",
    "Área do conhecimento CNPq",
    "Assuntos em português",
    "Assuntos em inglês",
)
_HTTP_URL = re.compile(r"https?://[^\s|<>\"']+", re.IGNORECASE)


class CsvPilotCollector(PilotCollector):
    """Uses the BDTD CSV export as a bounded candidate list, not as a bulk download."""

    def collect_csv(
        self,
        csv_path: str | Path,
        *,
        max_candidates: int = 1000,
    ) -> tuple[dict[str, Any], Any]:
        if max_candidates < 1:
            raise ValueError("max_candidates deve ser positivo")
        source_path = Path(csv_path).expanduser().resolve()
        if not source_path.is_file():
            raise ValueError(f"arquivo CSV não encontrado: {source_path}")

        source_sha256 = _file_sha256(source_path)
        initial_url = build_initial_query_url()
        manifest: dict[str, Any] = {
            "query": initial_url,
            "query_params": [
                {"name": name, "value": value} for name, value in initial_query_params()
            ],
            "source": {
                "type": "bdtd_search_csv",
                "path": str(source_path),
                "sha256": source_sha256,
            },
            "candidate_filter": {
                "topic_terms": ["Computação", "Informática", "Informação"],
                "topic_fields": list(_TOPIC_FIELDS),
                "access": "openAccess (sem rótulos restrictedAccess/embargoedAccess)",
                "requires_http_source_url": True,
            },
            "started_at": _now_iso(),
            "pages": [],
            "records": [],
            "warnings": [],
        }

        known_sources, known_checksums = self.storage.known_documents()
        for source_url in list(known_sources):
            known_sources.setdefault(_canonical_source_url(source_url), known_sources[source_url])
        for record in self.storage.known_downloaded_records():
            _add_existing_source_urls(record, known_sources)
        known_downloaded_ids = self.storage.known_downloaded_ids()
        known_dead_ends = self.storage.known_dead_ends()
        attempted_ids: set[str] = set()
        scanned = 0
        csv_row_count = 0
        self._log(
            f"coleta por CSV iniciada: alvo de {self.target_records} downloads; "
            f"máximo de {max_candidates} candidatos elegíveis"
        )

        with source_path.open("r", encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required_columns = {"Título", "Tipos de acesso", "Link de acesso"}
            missing = required_columns - set(reader.fieldnames or ())
            if missing:
                raise ValueError(
                    "CSV BDTD sem colunas obrigatórias: " + ", ".join(sorted(missing))
                )

            for row_number, row in enumerate(reader, start=2):
                csv_row_count += 1
                summary = _candidate_from_row(row, row_number)
                if summary is None:
                    continue
                if scanned >= max_candidates:
                    break
                record_id = str(summary["id"])
                scanned += 1
                if record_id in attempted_ids or record_id in known_downloaded_ids:
                    continue
                attempted_ids.add(record_id)
                if record_id in known_dead_ends:
                    self._log(f"{record_id}: falha CSV recente em cooldown; ignorando")
                    continue

                for url_item in summary["urls"]:
                    key = _canonical_source_url(str(url_item["url"]))
                    if key in known_sources:
                        summary["_known_duplicate_of"] = known_sources[key]
                        break
                if summary.get("_known_duplicate_of"):
                    duplicate_of = str(summary.pop("_known_duplicate_of"))
                    self._log(f"{record_id}: link de origem já coletado como {duplicate_of}")
                    record = {
                        "bdtd_id": record_id,
                        "record_url": summary["record_url"],
                        "page": None,
                        "metadata": _row_metadata(summary),
                        "repository": summary["repository"],
                        "provenance": _provenance(source_path, source_sha256, row_number),
                        "status": "duplicate",
                        "duplicate_of": duplicate_of,
                    }
                else:
                    record = self._collect_record(
                        summary,
                        None,
                        summary,
                        None,
                        known_sources,
                        known_checksums,
                    )
                    if record is not None:
                        record["provenance"] = _provenance(
                            source_path, source_sha256, row_number
                        )

                if record is not None:
                    manifest["records"].append(record)
                    self.storage.save_record(record)
                if _downloaded_count(manifest["records"]) >= self.target_records:
                    break

        manifest["finished_at"] = _now_iso()
        run_report = validate_pilot_manifest(manifest, min_records=0)
        manifest["run_summary"] = {
            "record_count": run_report.record_count,
            "downloaded_count": run_report.downloaded_count,
            "skipped_count": run_report.skipped_count,
            "requested_download_count": self.target_records,
            "eligible_candidates_scanned": scanned,
            "csv_rows_read": csv_row_count,
            "target_reached": run_report.downloaded_count >= self.target_records,
        }
        if scanned >= max_candidates and not manifest["run_summary"]["target_reached"]:
            manifest["warnings"].append(
                f"limite de {max_candidates} candidatos elegíveis atingido antes da meta"
            )
        elif not manifest["run_summary"]["target_reached"]:
            manifest["warnings"].append(
                "o CSV terminou antes de atingir a meta de downloads"
            )

        cumulative_records = {
            str(record["bdtd_id"]): record
            for record in self.storage.known_downloaded_records()
            if record.get("bdtd_id")
        }
        for record in manifest["records"]:
            if record.get("status") == "downloaded":
                cumulative_records[str(record["bdtd_id"])] = record
        manifest["records"] = list(cumulative_records.values())
        self.storage.save_collection(manifest)
        self._log(
            f"coleta CSV encerrada: {run_report.downloaded_count}/{self.target_records} "
            f"downloads, {run_report.skipped_count} ignorados, {scanned} candidatos elegíveis "
            f"examinados; {len(cumulative_records)} downloads mantidos no manifesto"
        )
        return manifest, run_report


def _candidate_from_row(row: dict[str, str], row_number: int) -> dict[str, Any] | None:
    title = _clean(row.get("Título"))
    if not title:
        return None
    access_labels = {_normalize(part) for part in _split_values(row.get("Tipos de acesso"))}
    if "openaccess" not in access_labels or any(
        "restrictedaccess" in label or "embargoedaccess" in label
        for label in access_labels
    ):
        return None

    topical_text = _normalize(" ".join(row.get(field, "") or "" for field in _TOPIC_FIELDS))
    if not any(term in topical_text for term in _TOPIC_TERMS):
        return None
    urls = _extract_urls(row.get("Link de acesso", ""))
    if not urls:
        return None

    author = _clean(row.get("Autor(a)"))
    year = _clean(row.get("Ano de defesa"))
    institution = _clean(row.get("Instituição de defesa"))
    ark = _clean(row.get("Identificador persistente ARK"))
    canonical_urls = [_canonical_source_url(item) for item in urls]
    identity = {
        "ark": ark.casefold() if ark and _normalize(ark) != "nao informado pela instituicao" else "",
        "urls": canonical_urls,
        "title": _normalize(title),
        "author": _normalize(author),
        "year": year,
        "institution": _normalize(institution),
    }
    digest = hashlib.sha256(
        json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    repository = _clean(row.get("Sigla da instituição de defesa")) or institution
    return {
        "id": f"csv_{digest}",
        "_csv_row": row_number,
        "record_url": urls[0],
        "title": title,
        "authors": _split_values(author),
        "abstract": (
            _csv_value(row.get("Resumo em Português"))
            or _csv_value(row.get("Resumo"))
            or _csv_value(row.get("Resumo em Inglês"))
        ),
        "subjects": _split_values(row.get("Assuntos em português"))
        + _split_values(row.get("Assuntos em inglês")),
        "date": year,
        "formats": _split_values(row.get("Tipo de documento")),
        "languages": _split_values(row.get("Idioma")),
        "institutions": [institution] if institution else [],
        "repository": repository,
        "accessRestrictions": "openAccess",
        "urls": [{"url": url} for url in urls],
    }


def _row_metadata(row: dict[str, Any]) -> dict[str, Any]:
    from .collector import _metadata

    return _metadata(row)


def _extract_urls(value: str | None) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for segment in (value or "").split("||"):
        for match in _HTTP_URL.findall(segment):
            candidate = match.rstrip(".,;:)]}")
            parts = urlsplit(candidate)
            if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
                continue
            key = _canonical_source_url(candidate)
            if key not in seen:
                seen.add(key)
                urls.append(candidate)
    return urls


def _add_existing_source_urls(
    record: dict[str, Any], known_sources: dict[str, str]
) -> None:
    record_id = record.get("bdtd_id")
    if not isinstance(record_id, str):
        return
    urls: list[str] = []
    document = record.get("document")
    if isinstance(document, dict) and isinstance(document.get("source_url"), str):
        urls.append(document["source_url"])
    metadata = record.get("metadata")
    if isinstance(metadata, dict) and isinstance(metadata.get("source_url"), str):
        urls.append(metadata["source_url"])
    raw = record.get("raw_record")
    if isinstance(raw, dict) and isinstance(raw.get("urls"), list):
        urls.extend(
            item["url"]
            for item in raw["urls"]
            if isinstance(item, dict) and isinstance(item.get("url"), str)
        )
    for url in urls:
        known_sources[url] = record_id
        known_sources[_canonical_source_url(url)] = record_id


def _split_values(value: str | None) -> list[str]:
    return [
        cleaned
        for item in (value or "").split("||")
        if (cleaned := _csv_value(item))
    ]


def _csv_value(value: str | None) -> str:
    cleaned = (value or "").strip()
    return "" if _normalize(cleaned) == "nao informado pela instituicao" else cleaned


def _clean(value: str | None) -> str:
    return _csv_value(value)


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(decomposed.encode("ascii", "ignore").decode("ascii").split())


def _provenance(path: Path, sha256: str, row_number: int) -> dict[str, Any]:
    return {
        "source_csv": str(path),
        "source_csv_sha256": sha256,
        "source_csv_row": row_number,
    }


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()
