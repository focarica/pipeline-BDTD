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
        max_pages: int = 100,
        record_batch_size: int = 25,
        start_page: int = 1,
        api_base_url: str = DEFAULT_API_BASE_URL,
        log: Callable[[str], None] = print,
    ) -> None:
        if not 1 <= target_records <= 5000:
            raise ValueError("target_records deve estar entre 1 e 5000")

        if page_size < 1 or max_pages < 1 or record_batch_size < 1:
            raise ValueError("page_size, max_pages e record_batch_size devem ser positivos")

        if start_page < 1:
            raise ValueError("start_page deve ser maior que 0")

        self.client = client
        self.storage = storage
        self.target_records = target_records
        self.page_size = page_size
        self.max_pages = max_pages
        self.record_batch_size = record_batch_size
        self.start_page = start_page
        self.search_url = f"{api_base_url.rstrip('/')}/search"
        self.record_url = f"{api_base_url.rstrip('/')}/record"
        self._log = log

    def collect(self) -> tuple[dict[str, Any], Any]:
        query_url = build_initial_query_url()
        manifest: dict[str, Any] = {
            "query": query_url,
            "query_params": [{"name": name, "value": value} for name, value in initial_query_params()],
            "search_api_url": self.search_url,
            "page_size": self.page_size,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "records": [],
            "warnings": [],
        }
        known_sources, known_checksums = self.storage.known_documents()
        known_downloaded_ids = self.storage.known_downloaded_ids()
        known_dead_ends = self.storage.known_dead_ends()
        attempted_ids: set[str] = set()
        seen_page_fingerprints: set[tuple[str, ...]] = set()
        page = self.start_page
        last_page = self.start_page + self.max_pages - 1
        self._log(f"iniciando coleta com alvo de {self.target_records} documentos baixados")

        while _downloaded_count(manifest["records"]) < self.target_records and page <= last_page:
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

            page_ids = tuple(
                sorted(record_id for item in summaries if (record_id := _record_id(item)))
            )
            if page_ids in seen_page_fingerprints:
                warning = (
                    f"a API repetiu os mesmos registros na página {page}; "
                    "a janela de paginação pode ter atingido o limite do serviço"
                )
                manifest["warnings"].append(warning)
                self._log(f"{warning}; reduza a página inicial ou restrinja a busca")
                break
            seen_page_fingerprints.add(page_ids)

            pending: list[Mapping[str, Any]] = []
            for summary in summaries:
                record_id = _record_id(summary)
                if not record_id:
                    self._log("registro sem identificador; ignorando")
                    continue
                if record_id in attempted_ids:
                    self._log(f"{record_id}: registro repetido entre páginas; ignorando")
                    continue
                attempted_ids.add(record_id)
                if record_id in known_downloaded_ids:
                    self._log(f"{record_id}: documento já coletado anteriormente; ignorando")
                    continue
                if record_id in known_dead_ends:
                    self._log(
                        f"{record_id}: falha recente em cooldown "
                        f"({known_dead_ends[record_id]}); ignorando"
                    )
                    continue
                pending.append(summary)

            for offset in range(0, len(pending), self.record_batch_size):
                if _downloaded_count(manifest["records"]) >= self.target_records:
                    break
                batch = pending[offset : offset + self.record_batch_size]
                batch_ids = [record_id for item in batch if (record_id := _record_id(item))]
                detailed_records, batch_errors = self._fetch_record_batch(batch_ids)
                for summary in batch:
                    if _downloaded_count(manifest["records"]) >= self.target_records:
                        break
                    record_id = _record_id(summary)
                    if not record_id:
                        continue
                    record = self._collect_record(
                        summary,
                        page,
                        detailed_records.get(record_id),
                        batch_errors.get(record_id),
                        known_sources,
                        known_checksums,
                    )
                    if record is not None:
                        manifest["records"].append(record)
                        self.storage.save_record(record)
            page += 1

            if len(summaries) < self.page_size:
                break

        manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
        run_report = validate_pilot_manifest(manifest, min_records=0)
        run_records = manifest["records"]
        manifest["run_summary"] = {
            "record_count": run_report.record_count,
            "downloaded_count": run_report.downloaded_count,
            "skipped_count": run_report.skipped_count,
        }

        cumulative_records = {
            str(record["bdtd_id"]): record
            for record in self.storage.known_downloaded_records()
            if record.get("bdtd_id")
        }
        for record in run_records:
            record_id = record.get("bdtd_id")
            if isinstance(record_id, str) and record_id:
                cumulative_records[record_id] = record
        manifest["records"] = list(cumulative_records.values())
        self.storage.save_collection(manifest)
        self._log(
            f"coleta encerrada: {run_report.record_count} registros nesta execução, "
            f"{run_report.downloaded_count} baixados, {run_report.skipped_count} ignorados; "
            f"{len(cumulative_records)} documentos baixados mantidos no manifesto"
        )
        return manifest, run_report

    def _collect_record(
        self,
        summary: Mapping[str, Any],
        page: int,
        raw_record: Mapping[str, Any] | None,
        record_error: BdtdAccessError | None,
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
        if record_error is not None or raw_record is None:
            status = getattr(record_error, "status_code", None)
            transient_failure = (
                status is None
                or status in {408, 429}
                or status >= 500
            )
            detail = (
                f"HTTP {status} no endpoint /record"
                if status
                else "falha na consulta em lote ao endpoint /record"
            )
            self._log(f"{record_id}: registro indisponível ({detail}); ignorando")
            reason = "record_batch_unavailable" if transient_failure else "record_unavailable"
            return {**base, "status": "unavailable", "reason": reason, "reason_detail": detail}

        metadata = _metadata(raw_record)
        base["metadata"] = metadata
        base["repository"] = _repository(raw_record, metadata)
        base["raw_record"] = raw_record
        self._log(f"{record_id}: campos detalhados recebidos: {', '.join(sorted(raw_record))}")

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

    def _fetch_record_batch(
        self, record_ids: list[str]
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, BdtdAccessError]]:
        if not record_ids:
            return {}, {}
        params = [("id[]", record_id) for record_id in record_ids]
        params.extend(("field[]", field) for field in _RECORD_FIELDS)
        try:
            payload = self.client.get_json(self.record_url, params=params)
        except BdtdAccessError as exc:
            if len(record_ids) > 1 and getattr(exc, "status_code", None) in (400, 414):
                self._log(
                    "a API recusou os parâmetros em lote; buscando os registros "
                    "individualmente como fallback"
                )
                return self._fetch_records_individually(record_ids)
            self._log(f"falha ao buscar lote de {len(record_ids)} registros: {exc}")
            return {}, {record_id: exc for record_id in record_ids}

        records: dict[str, Mapping[str, Any]] = {}
        candidates = payload.get("records")
        if isinstance(candidates, list):
            for item in candidates:
                if isinstance(item, Mapping):
                    record_id = _record_id(item)
                    if record_id:
                        records[record_id] = item

        missing_ids = [record_id for record_id in record_ids if record_id not in records]
        errors: dict[str, BdtdAccessError] = {}
        if missing_ids:
            self._log(
                f"a resposta em lote omitiu {len(missing_ids)} registro(s); "
                "tentando esses IDs individualmente"
            )
            fallback_records, fallback_errors = self._fetch_records_individually(missing_ids)
            records.update(fallback_records)
            errors.update(fallback_errors)
            for record_id in missing_ids:
                if record_id not in records and record_id not in errors:
                    errors[record_id] = BdtdAccessError(
                        f"a API não retornou o registro {record_id} no lote"
                    )
        return records, errors

    def _fetch_records_individually(
        self, record_ids: list[str]
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, BdtdAccessError]]:
        records: dict[str, Mapping[str, Any]] = {}
        errors: dict[str, BdtdAccessError] = {}
        for record_id in record_ids:
            try:
                payload = self.client.get_json(
                    self.record_url,
                    params=[("id", record_id), *(('field[]', field) for field in _RECORD_FIELDS)],
                )
            except BdtdAccessError as exc:
                errors[record_id] = exc
                self._log(f"{record_id}: fallback individual /record falhou: {exc}")
                continue
            candidates = payload.get("records")
            if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
                returned_id = _record_id(candidates[0])
                if returned_id == record_id:
                    records[record_id] = candidates[0]
                else:
                    errors[record_id] = BdtdAccessError(
                        f"a API retornou um ID inesperado para {record_id}"
                    )
            else:
                errors[record_id] = BdtdAccessError(
                    f"a API não retornou o registro {record_id}"
                )
        return records, errors

_RECORD_FIELDS = (
    "id",
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
