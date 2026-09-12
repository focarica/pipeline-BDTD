"""Persistência local da camada processada da BDTD."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


class ProcessedStorage:
    """Salva textos, chunks, datasets e o manifesto da camada processada."""

    def __init__(self, root: str | Path = "data/processed") -> None:
        self.root = Path(root)
        self.text_dir = self.root / "text"
        self.chunks_dir = self.root / "chunks"
        self.datasets_dir = self.root / "datasets"
        self.manifests_dir = self.root / "manifests"
        for directory in (self.text_dir, self.chunks_dir, self.datasets_dir, self.manifests_dir):
            directory.mkdir(parents=True, exist_ok=True)

    def record_text_path(self, record_id: str) -> Path:
        return self.text_dir / f"{_safe_name(record_id)}.txt"

    def record_chunks_path(self, record_id: str) -> Path:
        return self.chunks_dir / f"{_safe_name(record_id)}.jsonl"

    def save_text(self, record_id: str, text: str) -> Path:
        return self._atomic_write_text(self.record_text_path(record_id), text)

    def save_chunks(self, record_id: str, chunks: Sequence[Mapping[str, Any]]) -> Path:
        lines = "".join(
            json.dumps(chunk, ensure_ascii=False, sort_keys=True) + "\n" for chunk in chunks
        )
        return self._atomic_write_text(self.record_chunks_path(record_id), lines)

    def save_dataset(self, name: str, entries: Sequence[Mapping[str, Any]]) -> Path:
        path = self.datasets_dir / f"{_safe_name(name)}.jsonl"
        lines = "".join(
            json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n" for entry in entries
        )
        return self._atomic_write_text(path, lines)

    def save_manifest(self, manifest: Mapping[str, Any]) -> Path:
        payload = (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        return self._atomic_write(self.manifests_dir / "processed.json", payload)

    def _atomic_write_text(self, path: Path, text: str) -> Path:
        return self._atomic_write(path, text.encode("utf-8"))

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as temporary:
            temporary.write(payload)
            temporary.flush()
            os.fsync(temporary.fileno())
            temporary_path = Path(temporary.name)
        os.replace(temporary_path, path)
        return path


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._")
    return cleaned or "record"