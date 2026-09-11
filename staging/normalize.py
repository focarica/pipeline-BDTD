"""Normalização de metadados na camada Staging.

Corrige encoding (mojibake) e deriva campos estruturados (data ISO 8601,
código de idioma) a partir dos metadados já extraídos pela camada Raw,
sempre preservando os valores originais ao lado dos derivados.
"""

from __future__ import annotations

from collections.abc import Mapping
import re
import unicodedata
from typing import Any

import ftfy

_LANGUAGE_CODES: dict[str, str] = {
    "por": "pt", "pt": "pt", "pt-br": "pt", "portuguese": "pt",
    "português": "pt", "portugues": "pt",
    "eng": "en", "en": "en", "english": "en", "inglês": "en", "ingles": "en",
    "spa": "es", "es": "es", "spanish": "es", "español": "es", "espanhol": "es",
    "fra": "fr", "fre": "fr", "fr": "fr", "french": "fr", "francês": "fr", "frances": "fr",
    "deu": "de", "ger": "de", "de": "de", "german": "de", "alemão": "de", "alemao": "de",
    "ita": "it", "it": "it", "italian": "it", "italiano": "it",
}

_ISO_DATE = re.compile(r"^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?$")
_BR_DATE = re.compile(r"^(\d{2})/(\d{2})/(\d{4})$")
_YMD_SLASH_DATE = re.compile(r"^(\d{4})/(\d{2})/(\d{2})$")
_YEAR = re.compile(r"(\d{4})")


def fix_text(value: str) -> str:
    """Conserta mojibake e aplica normalização Unicode NFC."""
    return unicodedata.normalize("NFC", ftfy.fix_text(value)).strip()


def normalize_date(raw: str) -> tuple[str, int | None]:
    """Converte uma data em texto livre para ISO 8601, quando possível.

    Retorna (data_normalizada, ano). ``data_normalizada`` fica vazia quando
    o formato não é reconhecido, mas o ano ainda é extraído quando presente.
    """
    text = raw.strip()
    if not text:
        return "", None

    match = _ISO_DATE.match(text)
    if match:
        year, month, day = match.groups()
        parts = [p for p in (year, month, day) if p]
        return "-".join(parts), int(year)

    match = _BR_DATE.match(text)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month}-{day}", int(year)

    match = _YMD_SLASH_DATE.match(text)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month}-{day}", int(year)

    match = _YEAR.search(text)
    if match:
        return "", int(match.group(1))

    return "", None


def normalize_language(raw: str) -> str:
    """Retorna o código ISO 639-1 conhecido para o idioma, ou "" se não reconhecido."""
    return _LANGUAGE_CODES.get(raw.strip().casefold(), "")


def _fix_value(value: Any) -> Any:
    if isinstance(value, str):
        return fix_text(value)
    if isinstance(value, list):
        return [_fix_value(item) for item in value]
    if isinstance(value, Mapping):
        return {key: _fix_value(item) for key, item in value.items()}
    return value


def normalize_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Corrige encoding dos campos textuais e adiciona campos derivados.

    Os campos originais (``date``, ``language``, ...) são preservados; os
    derivados (``date_normalized``, ``date_year``, ``language_code``) são
    adicionados ao lado, sem sobrescrever o que veio da fonte.
    """
    cleaned: dict[str, Any] = {key: _fix_value(value) for key, value in metadata.items()}

    date_normalized, date_year = normalize_date(str(cleaned.get("date", "")))
    cleaned["date_normalized"] = date_normalized
    cleaned["date_year"] = date_year
    cleaned["language_code"] = normalize_language(str(cleaned.get("language", "")))
    return cleaned
