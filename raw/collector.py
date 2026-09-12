from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timezone
import re
from typing import Any
from urllib.parse import quote

from .common import DEFAULT_API_BASE_URL, DEFAULT_PAGE_SIZE
from .http import BdtdAccessError, BdtdClient
from .pdf_download import resolve_pdf_url, source_url
from .storage import DocumentValidationError, LocalStorage
from .validation import build_initial_query_url, initial_query_params, validate_pilot_manifest


class PilotCollector:
    def __init__(
        self,
        client: BdtdClient,
        storage: LocalStorage,
        *,
        target_records: int = 5,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int = 10,
        api_base_url: str = DEFAULT_API_BASE_URL,
        log: Callable[[str], None] = print,
    ) -> None:
        if not 1 <= target_records <= 50:
            raise ValueError("target_records deve estar entre 1 e 50")
        
        if page_size < 1 or max_pages < 1:
            raise ValueError("page_size e max_pages devem ser positivos")
        
        self.client = client
        self.storage = storage
        self.target_records = target_records
        self.page_size = page_size
        self.max_pages = max_pages
        self.search_url = f"{api_base_url.rstrip('/')}/search"
        self.record_url = f"{api_base_url.rstrip('/')}/record"
        self._log = log

    def collect(self) -> tuple[dict[str, Any], Any]:
        query_url = build_initial_query_url()
        manifest: dict[str, Any] = {
            "query": query_url,
            "query_params": [{"name": name, "value": value} for name, value in initial_query_params()],
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "records": [],
        }
        known_sources, known_checksums = self.storage.known_documents()
        page = 1
        self._log(f"iniciando coleta com alvo de {self.target_records} documentos baixados")

        while _downloaded_count(manifest["records"]) < self.target_records and page <= self.max_pages:
            params = list(initial_query_params())
            params.extend((("page", str(page)), ("limit", str(self.page_size))))
            self._log(f"buscando página {page} na API")
            payload = self.client.get_json(self.search_url, params=params)
            self.storage.save_search_response(page, payload)
            manifest["pages"].append(page)
            summaries = list(_search_records(payload))
            self._log(f"página {page}: {len(summaries)} registros encontrados")
            if not summaries:
                self._log("nenhum registro retornado; encerrando busca")
                break

            for summary in summaries:
                if _downloaded_count(manifest["records"]) >= self.target_records:
                    break
                record = self._collect_record(summary, page, known_sources, known_checksums)
                if record is not None:
                    manifest["records"].append(record)
                    self.storage.save_record(record)
            page += 1

            if len(summaries) < self.page_size:
                break

        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.storage.save_collection(manifest)
        report = validate_pilot_manifest(manifest)
        self._log(
            f"coleta encerrada: {report.record_count} registros, "
            f"{report.downloaded_count} baixados, {report.skipped_count} ignorados"
        )
        return manifest, report

    def _collect_record(
        self,
        summary: Mapping[str, Any],
        page: int,
        known_sources: dict[str, str],
        known_checksums: dict[str, str],
    ) -> dict[str, Any] | None:
        record_id = _record_id(summary)
        if not record_id:
            self._log("registro sem identificador; ignorando")
            return None
        self._log(f"processando registro {record_id} da página {page}")
        metadata = _metadata(summary)
        base = {
            "bdtd_id": record_id,
            "record_url": _record_url(record_id),
            "page": page,
            "metadata": metadata,
            "repository": _repository(summary, metadata),
        }

        try:
            full_record = self.client.get_json(
                self.record_url,
                params=[("id", record_id), *[("field[]", field) for field in _RECORD_FIELDS]],
            )
            raw_record = _unwrap_record(full_record)
            metadata = _metadata(raw_record)
            base["metadata"] = metadata
            base["repository"] = _repository(raw_record, metadata)
            base["raw_record"] = raw_record
            self._log(f"{record_id}: campos detalhados recebidos: {', '.join(sorted(raw_record))}")
        except BdtdAccessError as exc:
            status = getattr(exc, "status_code", None)
            detail = f"HTTP {status} no endpoint /record" if status else "falha de rede no endpoint /record"
            self._log(f"{record_id}: registro indisponível ({detail}); ignorando")
            return {**base, "status": "unavailable", "reason": "record_unavailable", "reason_detail": detail}

        if _is_restricted(metadata):
            detail = str(metadata.get("access_rights", "")).strip()[:200]
            self._log(f"{record_id}: acesso restrito; ignorando")
            return {**base, "status": "restricted", "reason": "restricted_rights", "reason_detail": detail}
        source_url, reason, reason_detail, landing_url = resolve_pdf_url(
            self.client, base["raw_record"], record_id=record_id, log=self._log
        )
        if not source_url:
            self._log(f"{record_id}: nenhum PDF encontrado ({reason}); ignorando")
            return {
                **base,
                "status": "unavailable",
                "source_url": landing_url,
                "reason": reason,
                "reason_detail": reason_detail,
            }
        if source_url in known_sources:
            self._log(f"{record_id}: documento duplicado; ignorando")
            return None

        try:
            self._log(f"{record_id}: baixando {source_url}")
            response = self.client.request(source_url)
            document = self.storage.save_document(record_id, source_url, response)
        except BdtdAccessError as exc:
            status = getattr(exc, "status_code", None)
            detail = f"HTTP {status} no download" if status else "falha de rede/timeout no download"
            self._log(f"{record_id}: download inacessível ({detail}); ignorando")
            return {
                **base,
                "status": "unavailable",
                "source_url": source_url,
                "reason": "download_unreachable",
                "reason_detail": detail,
            }
        except DocumentValidationError:
            self._log(f"{record_id}: download inválido (resposta não é um PDF válido); ignorando")
            return {
                **base,
                "status": "unavailable",
                "source_url": source_url,
                "reason": "download_invalid",
                "reason_detail": "resposta não passou na validação de PDF (MIME/assinatura)",
            }

        if document["sha256"].casefold() in known_checksums:
            target = self.storage.documents / record_id
            for path in target.glob("*"):
                path.unlink(missing_ok=True)
            target.rmdir()
            self._log(f"{record_id}: checksum duplicado; ignorando")
            return None
        known_sources[source_url] = record_id
        known_checksums[document["sha256"].casefold()] = record_id
        self._log(f"{record_id}: documento salvo com checksum {document['sha256']}")
        return {**base, "status": "downloaded", "document": document}

_RECORD_FIELDS = (
    "title",
    "authors",
    "abstract",
    "summary",
    "subjects",
    "publicationDates",
    "formats",
    "languages",
    "institutions",
    "accessRestrictions",
    "urls",
    "recordPage",
)


def _search_records(payload: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    candidates = payload.get("records")
    if isinstance(candidates, list):
        return (item for item in candidates if isinstance(item, Mapping))
    return ()


def _downloaded_count(records: Iterable[Mapping[str, Any]]) -> int:
    """Conta os registros com documento PDF já baixado."""

    return sum(record.get("status") == "downloaded" for record in records)


def _unwrap_record(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    records = payload.get("records")
    if isinstance(records, list) and records and isinstance(records[0], Mapping):
        return records[0]
    return {}


def _record_id(record: Mapping[str, Any]) -> str | None:
    value = record.get("id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _metadata(record: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "title": _first_text(record, ("title", "title_short")),
        "alternative_title": _first_text(record, ("alternative_title", "title_alt")),
        "authors": _author_values(record),
        "abstract": _first_text(record, ("abstract", "summary", "description")),
        "subjects": _values(record, ("subject", "subjects")),
        "date": _first_text(record, ("date", "publishDate", "publicationDates", "year")),
        "document_type": _first_text(record, ("document_type", "format", "formats")),
        "language": _first_text(record, ("language", "languages")),
        "institution": _first_text(record, ("institution", "institution_name", "institutions")),
        "repository": _first_text(record, ("repository", "source")),
        "access_rights": _first_text(record, ("rights", "access_rights", "accessRestrictions")),
        "source_url": source_url(record),
    }


def _first_text(record: Mapping[str, Any], keys: Iterable[str]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            for item in value:
                if isinstance(item, str) and item.strip():
                    return item.strip()
    return ""


def _values(record: Mapping[str, Any], keys: Iterable[str]) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(_text_values(record.get(key)))
    return values


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    if isinstance(value, list):
        values: list[str] = []
        for item in value:
            values.extend(_text_values(item))
        return values
    return []


def _author_values(record: Mapping[str, Any]) -> list[str]:
    authors = record.get("authors") or record.get("author")
    if isinstance(authors, list):
        return _extract_author_names(authors)
    if isinstance(authors, Mapping):
        values: list[str] = []
        for role in ("primary", "main", "secondary", "corporate"):
            values.extend(_extract_author_names(authors.get(role)))
        seen: set[str] = set()
        unique: list[str] = []
        for name in values:
            if name not in seen:
                seen.add(name)
                unique.append(name)
        return unique
    return _text_values(authors)


def _extract_author_names(node: Any) -> list[str]:
    if isinstance(node, Mapping):
        return [name for name in (n.strip() if isinstance(n, str) else str(n).strip() for n in node) if _is_plausible_author_name(name)]
    if isinstance(node, list):
        values: list[str] = []
        for item in node:
            if isinstance(item, Mapping):
                values.extend(_extract_author_names(item))
            elif isinstance(item, str) and _is_plausible_author_name(item):
                values.append(item.strip())
        return values
    if isinstance(node, str) and _is_plausible_author_name(node):
        return [node.strip()]
    return []


def _is_plausible_author_name(value: object) -> bool:
    if not isinstance(value, str):
        return False
    name = value.strip()
    if len(name) < 3:
        return False
    # A API às vezes classifica datas como autores secundários.
    if re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?", name):
        return False
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}|\d{4}/\d{2}/\d{2}", name):
        return False
    if not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name):
        return False
    return True


def _repository(record: Mapping[str, Any], metadata: Mapping[str, Any]) -> str:
    value = record.get("repository") or metadata.get("repository")
    return value.strip() if isinstance(value, str) else ""


def _is_restricted(metadata: Mapping[str, Any]) -> bool:
    rights = str(metadata.get("access_rights", "")).casefold()
    return any(term in rights for term in ("restricted", "embargo", "private", "closed", "access denied"))


def _record_url(record_id: str) -> str:
    return f"https://bdtd.ibict.br/vufind/Record/{quote(record_id, safe='')}"
