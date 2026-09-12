"""Anonimização de PII e nomes de pessoas na camada processada."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import re
from typing import Any

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_RE = re.compile(r"\b(?:https?://|ftp://|www\.)\S+", re.IGNORECASE)
_IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PHONE_RE = re.compile(
    r"(?:\+55[\s-]?)?(?:\(\d{2}\)[\s-]?|\d{2}[\s-]?)\d{4,5}[\s-]?\d{4}"
)
_CPF_RE = re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b|\b\d{11}\b")
_RG_RE = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}(?:-\d{1,2})?\b")
_CEP_RE = re.compile(r"\b\d{5}-\d{3}\b")
_ROLE_SEQUENCE_RE = re.compile(
    r"(?:Orientador|Co-orientador|Coorientador|por|Autor|Professor|Professora)\s*:?\s+"
    r"([A-ZÀ-Ú][\wÀ-Ú']*(?:\s+[A-ZÀ-Ú][\wÀ-Ú']*){1,5})",
    re.IGNORECASE,
)
_ROLE_KEY_RE = re.compile(r"orientador|advisor|professor", re.IGNORECASE)

_PERSON_PLACEHOLDER = "<<PERSON>>"
_PII_REPLACEMENTS = (
    (_URL_RE, "<<URL>>"),
    (_EMAIL_RE, "<<EMAIL>>"),
    (_IP_RE, "<<IP>>"),
    (_PHONE_RE, "<<PHONE>>"),
    (_CPF_RE, "<<CPF>>"),
    (_RG_RE, "<<RG>>"),
    (_CEP_RE, "<<ENDEREÇO>>"),
)


class PersonRedactor:
    """Interface para redação de nomes de pessoas em um texto."""

    def redact_persons(self, text: str, names: Sequence[str]) -> str:
        """Redige as ocorrências de nomes conhecidos no texto."""
        raise NotImplementedError


class HeuristicPersonRedactor(PersonRedactor):
    """Redator heurístico: nomes conhecidos mais sequências capitalizadas."""

    def redact_persons(self, text: str, names: Sequence[str]) -> str:
        text = _redact_known_names(text, names)
        return _ROLE_SEQUENCE_RE.sub(_PERSON_PLACEHOLDER, text)


class SpacyPersonRedactor(PersonRedactor):
    """Redator NER baseado em spaCy (desabilitado até wheels Python 3.14)."""

    SUPPORTED = False

    def redact_persons(self, text: str, names: Sequence[str]) -> str:
        raise NotImplementedError(
            "spaCy NER não está habilitado: aguardando wheels de spacy/pt_core_news_lg para Python 3.14"
        )


class Anonymizer:
    """Redige PII estruturada e nomes de pessoas em um texto."""

    def __init__(self, redactor: PersonRedactor | None = None) -> None:
        self.redactor = redactor or HeuristicPersonRedactor()

    def anonymize(self, text: str, metadata: Mapping[str, Any]) -> tuple[str, dict[str, int]]:
        """Retorna o texto anonimizado e o relatório de redações por tipo."""
        report: dict[str, int] = {}
        text = self._redact_pii(text, report)
        names = self._collect_names(metadata)
        text = self.redactor.redact_persons(text, names)
        count = _placeholder_count(text, _PERSON_PLACEHOLDER)
        if count:
            report["PERSON"] = report.get("PERSON", 0) + count
        return text, report

    def _redact_pii(self, text: str, report: dict[str, int]) -> str:
        for pattern, placeholder in _PII_REPLACEMENTS:
            count = len(pattern.findall(text))
            if count:
                report[placeholder[2:-2]] = report.get(placeholder[2:-2], 0) + count
                text = pattern.sub(placeholder, text)
        return text

    def _collect_names(self, metadata: Mapping[str, Any]) -> list[str]:
        names: list[str] = []
        for key in ("authors", "author"):
            value = metadata.get(key)
            if isinstance(value, str):
                names.append(value)
            elif isinstance(value, Sequence):
                names.extend(str(item) for item in value if isinstance(item, str))
        raw_record = metadata.get("raw_record")
        if isinstance(raw_record, Mapping):
            names.extend(_names_from_record(raw_record))
        seen: list[str] = []
        for name in names:
            cleaned = name.strip()
            if cleaned and cleaned not in seen:
                seen.append(cleaned)
        return seen


def assert_no_pii(text: str) -> dict[str, int]:
    """Reexecuta os padrões de PII e reporta ocorrências remanescentes."""
    patterns = (
        ("EMAIL", _EMAIL_RE),
        ("URL", _URL_RE),
        ("IP", _IP_RE),
        ("PHONE", _PHONE_RE),
        ("CPF", _CPF_RE),
        ("RG", _RG_RE),
        ("ENDEREÇO", _CEP_RE),
    )
    return {name: len(pattern.findall(text)) for name, pattern in patterns}


def _redact_known_names(text: str, names: Sequence[str]) -> str:
    for name in names:
        tokens = [token for token in re.split(r"[,\s]+", name) if token]
        if len(tokens) < 2:
            continue
        joined = " ".join(tokens)
        pattern = re.compile(
            r"\b" + re.escape(joined).replace(r"\ ", r"\s+") + r"\b",
            re.IGNORECASE,
        )
        text = pattern.sub(_PERSON_PLACEHOLDER, text)
    return text


def _names_from_record(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if _ROLE_KEY_RE.search(str(key)):
                if isinstance(item, str):
                    found.append(item)
                elif isinstance(item, Sequence) and not isinstance(item, (str, bytes)):
                    found.extend(_names_from_record(item))
            else:
                found.extend(_names_from_record(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for item in value:
            found.extend(_names_from_record(item))
    return found


def _placeholder_count(text: str, placeholder: str) -> int:
    return len(re.findall(re.escape(placeholder), text))