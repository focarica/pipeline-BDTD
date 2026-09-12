"""Filtro de idioma e qualidade da camada processada."""

from __future__ import annotations

from dataclasses import dataclass, replace
import re
import unicodedata
from typing import Any

from langdetect import detect, detect_langs

MIN_CHARS = 500
MIN_PORTUGUESE_CONFIDENCE = 0.5
MAX_REPETITION_RATIO = 0.7
MAX_JUNK_RATIO = 0.15

_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SHINGLE_SIZE = 5


@dataclass(frozen=True)
class FilterVerdict:
    """Resultado da avaliação de idioma e qualidade de um texto."""

    allowed: bool
    language: str = ""
    confidence: float = 0.0
    char_count: int = 0
    repetition_ratio: float = 0.0
    junk_ratio: float = 0.0
    reason: str | None = None


def detect_language(text: str) -> str:
    """Detecta o idioma dominante de um texto via langdetect."""
    try:
        return detect(text)
    except Exception:
        return ""


def _language_with_confidence(text: str) -> tuple[str, float]:
    try:
        langs = detect_langs(text)
    except Exception:
        return "", 0.0
    if not langs:
        return "", 0.0
    for lang in langs:
        if lang.lang == "pt":
            return "pt", lang.prob
    return langs[0].lang, langs[0].prob


def quality(text: str) -> dict[str, Any]:
    """Calcula métricas de qualidade de um texto."""
    return {
        "char_count": len(text),
        "repetition_ratio": repetition_ratio(text),
        "junk_ratio": _junk_ratio(text),
    }


def repetition_ratio(text: str) -> float:
    """Proporção de shingles repetidos de palavras (heurística de repetição)."""
    words = _WORD_RE.findall(text.casefold())
    if len(words) < _SHINGLE_SIZE + 1:
        return 0.0
    total = len(words) - _SHINGLE_SIZE + 1
    unique = len({tuple(words[index : index + _SHINGLE_SIZE]) for index in range(total)})
    return 1.0 - (unique / total)


def _junk_ratio(text: str) -> float:
    if not text:
        return 1.0
    junk = sum(1 for char in text if _is_junk_char(char))
    return junk / len(text)


def _is_junk_char(char: str) -> bool:
    if char == "\ufffd":
        return True
    category = unicodedata.category(char)
    codepoint = ord(char)
    return (
        category in ("So", "Cf")
        or 0xFDD0 <= codepoint <= 0xFDEF
        or 0xF0000 <= codepoint <= 0xFFFFD
    )


def filter_score(text: str, *, min_len: int = MIN_CHARS) -> FilterVerdict:
    """Avalia se um texto deve ser mantido com base em idioma e qualidade."""
    language, confidence = _language_with_confidence(text)
    metrics = quality(text)
    verdict = FilterVerdict(
        allowed=True,
        language=language,
        confidence=confidence,
        char_count=metrics["char_count"],
        repetition_ratio=metrics["repetition_ratio"],
        junk_ratio=metrics["junk_ratio"],
    )
    if metrics["char_count"] < min_len:
        return replace(verdict, allowed=False, reason="too_short")
    if language != "pt" or confidence < MIN_PORTUGUESE_CONFIDENCE:
        return replace(verdict, allowed=False, reason="not_portuguese")
    if metrics["repetition_ratio"] > MAX_REPETITION_RATIO:
        return replace(verdict, allowed=False, reason="too_repetitive")
    if metrics["junk_ratio"] > MAX_JUNK_RATIO:
        return replace(verdict, allowed=False, reason="too_junky")
    return verdict