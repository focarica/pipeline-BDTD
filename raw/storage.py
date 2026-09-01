from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any
from urllib.parse import unquote, urlparse

from .validation import is_valid_pdf_payload


class DocumentValidationError(ValueError):
    """Erro levantado quando uma resposta não é um download PDF válido."""


class LocalStorage:
    """Persiste respostas brutas e documentos em um diretório local de saída."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.manifests = self.root / "manifests"
        self.records = self.manifests / "records"
        self.documents = self.root / "documents"
        self.records.mkdir(parents=True, exist_ok=True)
        self.documents.mkdir(parents=True, exist_ok=True)

    def save_search_response(self, page: int, payload: Mapping[str, Any]) -> Path:
        return self._save_json(self.manifests / f"search-page-{page:04d}.json", payload)

    def save_record(self, record: Mapping[str, Any]) -> Path:
        record_id = _safe_name(str(record["bdtd_id"]))
        return self._save_json(self.records / f"{record_id}.json", record)

    def save_collection(self, manifest: Mapping[str, Any]) -> Path:
        return self._save_json(self.manifests / "collection.json", manifest)

    def known_documents(self) -> tuple[dict[str, str], dict[str, str]]:
        sources: dict[str, str] = {}
        checksums: dict[str, str] = {}
        for path in self.records.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            document = record.get("document")
            if isinstance(document, Mapping) and record.get("status") == "downloaded":
                source = document.get("source_url")
                checksum = document.get("sha256")
                record_id = record.get("bdtd_id")
                if not isinstance(record_id, str):
                    continue
                if isinstance(source, str):
                    sources[source] = record_id
                if isinstance(checksum, str):
                    checksums[checksum.casefold()] = record_id
        return sources, checksums

    def save_document(
        self,
        record_id: str,
        source_url: str,
        response: Any,
    ) -> dict[str, Any]:
        content_type = response.headers.get("Content-Type", "")
        payload = response.content
        if not is_valid_pdf_payload(content_type, payload):
            raise DocumentValidationError(f"a resposta para {source_url} não é um PDF válido")

        checksum = hashlib.sha256(payload).hexdigest()
        filename = _filename_from_response(response, record_id)
        target_dir = self.documents / _safe_name(record_id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / filename
        self._atomic_write(target, payload)
        return {
            "source_url": source_url,
            "final_url": str(response.url),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "http_status": response.status_code,
            "content_type": content_type,
            "original_filename": filename,
            "byte_count": len(payload),
            "sha256": checksum,
            "pdf_valid": True,
            "path": str(target.relative_to(self.root)),
        }

    def _save_json(self, path: Path, value: Mapping[str, Any]) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._atomic_write(
            path,
            (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
                "utf-8"
            ),
        )
        return path

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "record"


def _filename_from_response(response: Any, record_id: str) -> str:
    disposition = response.headers.get("Content-Disposition", "")
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^;\"]+)", disposition, re.I)
    candidate = unquote(match.group(1).strip()) if match else ""
    candidate = Path(urlparse(candidate).path).name if candidate else ""
    return _safe_name(candidate or f"{record_id}.pdf")
