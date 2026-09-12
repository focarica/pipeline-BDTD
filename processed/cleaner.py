"""Limpeza e normalização de texto da camada processada."""

from __future__ import annotations

from collections import Counter
import re
import unicodedata

_SOFT_HYPHEN = "\u00ad"
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MOJIBAKE_RE = re.compile(
    r"Ã[\x80-\xbf]|Â[\x80-\xbf]|â€[\x80-\xbf]|\xc3[\x80-\xbf]|\xe2[\x80-\xbf]"
)
_PAGE_NUMBER_RE = re.compile(r"^\s*\d{1,4}\s*$")
_CHAPTER_RE = re.compile(
    r"^(?:CAP[IÍ]TULO(?:\s+\d+)?|PARTE(?:\s+\d+)?|INTRODUÇÃO(?:\s|$)|"
    r"\d+(?:\.\d+)*\.?\s+[A-ZÀ-Ú])",
    re.IGNORECASE,
)
_REFERENCES_RE = re.compile(
    r"^\s*(?:REFERÊNCIAS\s*BIBLIOGR[ÁA]FICAS?|REFERÊNCIAS|BIBLIOGRAFIA)\b",
    re.IGNORECASE,
)
_BLANK_BLOCK_RE = re.compile(r"\n[ \t]*(?:\n[ \t]*)+")
_LINE_BREAK_RE = re.compile(r"(?:[ \t]*\n){3,}")
_LEAD_WORD_RE = re.compile(r"[A-Za-zÀ-ú][A-Za-zÀ-ú']*")
_VOWEL_RE = re.compile(r"[aeiouáéíóúàâêôãõAEIOUÁÉÍÓÚÀÂÊÔÃÕ]")

_MIN_REPEATED_LINE = 3
_MIN_HYPHEN_PREFIX = 3


def clean_text(text: str) -> str:
    """Aplica a limpeza completa de um texto extraído de um documento."""
    text = _normalize_unicode(text)
    text = _clean_whitespace(text)
    text = _strip_page_numbers(text)
    text = _strip_repeated_lines(text)
    text = _rejoin_hyphenation(text)
    text = _cut_front_matter(text)
    text = _cut_references(text)
    return text.strip() + "\n"


def _normalize_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    if _MOJIBAKE_RE.search(text):
        text = _fix_mojibake(text)
    return text


def _fix_mojibake(text: str) -> str:
    for encoding in ("latin-1", "cp1252"):
        try:
            return text.encode(encoding, errors="strict").decode("utf-8", errors="strict")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return text


def _clean_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = _LINE_BREAK_RE.sub("\n\n", text)
    return text


def _strip_page_numbers(text: str) -> str:
    return "\n".join(
        line for line in text.split("\n") if not _PAGE_NUMBER_RE.fullmatch(line.strip())
    )


def _strip_repeated_lines(text: str) -> str:
    lines = text.split("\n")
    counts = Counter(line.strip() for line in lines if line.strip())
    repeated = {
        line
        for line, count in counts.items()
        if count >= _MIN_REPEATED_LINE
        and len(line) >= 4
        and not _CHAPTER_RE.match(line)
        and not _PAGE_NUMBER_RE.fullmatch(line)
    }
    if not repeated:
        return text
    return "\n".join(line for line in lines if line.strip() not in repeated)


def _rejoin_hyphenation(text: str) -> str:
    text = text.replace(_SOFT_HYPHEN, "")
    lines = text.split("\n")
    joined: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        prefix = line[:-1].rstrip()
        if line.endswith("-") and len(prefix) >= _MIN_HYPHEN_PREFIX and index + 1 < len(lines):
            next_line = lines[index + 1].lstrip()
            suffix = _leading_word(next_line)
            if suffix and _VOWEL_RE.search(prefix[-1] + suffix):
                joined.append(prefix + suffix + next_line[len(suffix) :])
                index += 2
                continue
        joined.append(line)
        index += 1
    return "\n".join(joined)


def _leading_word(text: str) -> str:
    match = _LEAD_WORD_RE.match(text)
    return match.group(0) if match else ""


def _cut_front_matter(text: str) -> str:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if _CHAPTER_RE.match(line.strip()):
            return text if index == 0 else "\n".join(lines[index:])
    return text


def _cut_references(text: str) -> str:
    lines = text.splitlines()
    if not lines:
        return text
    limit = int(len(lines) * 0.35)
    for index, line in enumerate(lines):
        if index >= limit and _REFERENCES_RE.match(line.strip()):
            return "\n".join(lines[:index]).rstrip() + "\n"
    return text