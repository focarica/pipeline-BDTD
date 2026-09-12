"""Deduplicação da coleção processada."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
import re
import unicodedata
from typing import Any

from datasketch import MinHash, MinHashLSH

_MINHASH_PERM = 128
_LSH_THRESHOLD = 0.85
_SHINGLE_SIZE = 5

_WORD_RE = re.compile(r"\w+", re.UNICODE)


def normalize_for_dedup(text: str) -> str:
    """Normaliza o texto para comparação de deduplicação."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = text.casefold()
    return re.sub(r"\s+", " ", text).strip()


def text_digest(text: str) -> str:
    """Digest SHA-256 do texto normalizado para deduplicação."""
    return hashlib.sha256(normalize_for_dedup(text).encode("utf-8")).hexdigest()


def _year(value: object) -> str:
    match = re.search(r"\d{4}", str(value or ""))
    return match.group(0) if match else ""


def metadata_key(metadata: Mapping[str, Any]) -> str:
    """Chave de deduplicação nível 2: título + autor + ano."""
    title = normalize_for_dedup(str(metadata.get("title", "")))
    authors = metadata.get("authors")
    if isinstance(authors, Sequence) and authors:
        author = normalize_for_dedup(str(authors[0]))
    elif isinstance(authors, str):
        author = normalize_for_dedup(authors)
    else:
        author = ""
    year = _year(metadata.get("date"))
    return "|".join((title, author, year)).rstrip("|")


def _shingles(text: str) -> list[str]:
    words = _WORD_RE.findall(text.casefold())
    if len(words) < _SHINGLE_SIZE:
        return [" ".join(words)]
    return [
        " ".join(words[index : index + _SHINGLE_SIZE])
        for index in range(len(words) - _SHINGLE_SIZE + 1)
    ]


class Deduplicator:
    """Agrupa registros duplicados em clusters.

    O primeiro registro de um cluster é considerado canônico; os demais são
    marcados como ``duplicate`` apontando para o ``cluster_id`` do canônico.
    """

    def __init__(self, *, num_perm: int = _MINHASH_PERM, threshold: float = _LSH_THRESHOLD) -> None:
        self._num_perm = num_perm
        self._lsh = MinHashLSH(threshold=threshold, num_perm=num_perm)
        self._exact: dict[str, str] = {}
        self._keyed: dict[str, str] = {}
        self.clusters: dict[str, str] = {}

    def process(self, records: Sequence[Mapping[str, Any]]) -> dict[str, str]:
        """Processa a coleção e retorna o mapeamento record_id -> cluster_id."""
        for record in records:
            rec_id = str(record["bdtd_id"])
            text = str(record.get("text", ""))
            if not text:
                self.clusters[rec_id] = rec_id
                continue
            metadata = record.get("metadata")
            self.clusters[rec_id] = self._find_cluster(
                rec_id, text, metadata if isinstance(metadata, Mapping) else {}
            )
        return self.clusters

    def _find_cluster(self, rec_id: str, text: str, metadata: Mapping[str, Any]) -> str:
        digest = text_digest(text)
        if digest in self._exact:
            return self._exact[digest]
        key = metadata_key(metadata)
        if key and key in self._keyed:
            self._exact[digest] = self._keyed[key]
            return self._keyed[key]
        similar = self._lsh.query(self._minhash(text))
        if similar:
            first = similar[0]
            self._exact[digest] = first
            if key:
                self._keyed[key] = first
            return first
        self._lsh.insert(rec_id, self._minhash(text))
        self._exact[digest] = rec_id
        if key:
            self._keyed[key] = rec_id
        return rec_id

    def _minhash(self, text: str) -> MinHash:
        minhash = MinHash(num_perm=self._num_perm)
        for shingle in _shingles(text):
            minhash.update(shingle.encode("utf-8"))
        return minhash