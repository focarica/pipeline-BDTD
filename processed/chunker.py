"""Chunking ciente de tokens da camada processada."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import tiktoken

_TOKENIZER_MODEL = "cl100k_base"
_MAX_HEADING_LEN = 90

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…;])[ \t]+|\n+")
_CHAPTER_HEADING_RE = re.compile(
    r"^(?:CAP[IÍ]TULO|PARTE|ANEXO|APÊNDICE)\b",
    re.IGNORECASE,
)
_NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-ZÀ-Ú]")

_encoding = tiktoken.get_encoding(_TOKENIZER_MODEL)


@dataclass(frozen=True)
class Section:
    """Uma seção contígua de um documento."""

    name: str
    start_line: int
    end_line: int


def _section_name(heading: str) -> str:
    name = re.sub(r"^\d+(?:\.\d+)*\.?\s+", "", heading.strip()).strip(" -–—.")
    name = re.sub(r"\s+", " ", name)
    return (name or "SEÇÃO")[:60]


def _is_heading(line: str) -> str | None:
    stripped = line.strip()
    if not stripped or len(stripped) > _MAX_HEADING_LEN:
        return None
    if _CHAPTER_HEADING_RE.search(stripped):
        return stripped
    if _NUMBERED_HEADING_RE.match(stripped):
        return stripped
    if stripped.isupper() and any(char.isalpha() for char in stripped) and " " in stripped:
        return stripped
    return None


def split_sections(text: str) -> list[Section]:
    """Divide um texto em seções a partir dos cabeçalhos detectados."""
    lines = text.splitlines()
    sections: list[Section] = []
    start_line = 0
    name = "INÍCIO"
    for index, line in enumerate(lines):
        heading = _is_heading(line)
        if heading is not None:
            sections.append(Section(name=name, start_line=start_line, end_line=index))
            start_line = index
            name = _section_name(heading)
    sections.append(Section(name=name, start_line=start_line, end_line=len(lines)))
    return sections


def chunk_document(
    record_id: str,
    text: str,
    *,
    target_tokens: int = 1024,
    overlap: int = 128,
    title: str = "",
) -> list[dict[str, Any]]:
    """Gera chunks do documento com limite de tokens e sobreposição."""
    pieces = _sentence_pieces(text)
    if not pieces:
        return []
    tokenized = [(piece, start, len(_encoding.encode(piece))) for piece, start in pieces]
    section_ranges = _section_ranges(text)

    chunks: list[dict[str, Any]] = []
    position = 0
    index = 0
    total = len(tokenized)
    previous: list[int] = []

    while index < total:
        window = _tail_indices(previous, tokenized, overlap) if previous else []
        tokens = sum(tokenized[item][2] for item in window)
        start_char = tokenized[window[0]][1] if window else tokenized[index][1]

        while index < total and tokens < target_tokens:
            item_index = index
            piece_tokens = tokenized[index][2]
            if not window and tokens + piece_tokens > target_tokens:
                window = [item_index]
                tokens = piece_tokens
                start_char = tokenized[item_index][1]
                index += 1
                break
            if tokens + piece_tokens <= target_tokens:
                window.append(item_index)
                tokens += piece_tokens
                index += 1
            else:
                break

        if not window:
            break

        chunk_text = " ".join(tokenized[item][0] for item in window)
        section_index = _section_index(section_ranges, start_char)
        section_name = section_ranges[section_index][0] if section_index >= 0 else "INÍCIO"
        chunks.append(
            {
                "id": f"{record_id}-chunk-{position:03d}",
                "record_id": record_id,
                "title": title,
                "section": section_name,
                "page": (section_index + 1) if section_index >= 0 else 1,
                "position": position,
                "tokens": len(_encoding.encode(chunk_text)),
                "text": chunk_text,
            }
        )
        previous = window
        position += 1

    return chunks


def _sentence_pieces(text: str) -> list[tuple[str, int]]:
    pieces: list[tuple[str, int]] = []
    cursor = 0
    for match in _SENTENCE_SPLIT_RE.finditer(text):
        raw = text[cursor : match.start()]
        if raw.strip():
            pieces.append((raw.strip(), cursor + (len(raw) - len(raw.lstrip()))))
        cursor = match.end()
    tail = text[cursor:]
    if tail.strip():
        pieces.append((tail.strip(), cursor + (len(tail) - len(tail.lstrip()))))
    return pieces


def _section_ranges(text: str) -> list[tuple[str, int, int]]:
    lines = text.splitlines()
    offsets: list[int] = []
    position = 0
    for line in lines:
        offsets.append(position)
        position += len(line) + 1
    total = position if lines else 0
    ranges: list[tuple[str, int, int]] = []
    for section in split_sections(text):
        start = offsets[section.start_line] if section.start_line < len(offsets) else total
        end = offsets[section.end_line] if section.end_line < len(offsets) else total
        ranges.append((section.name, start, end))
    return ranges


def _section_index(ranges: list[tuple[str, int, int]], char_pos: int) -> int:
    for index, (_name, start, end) in enumerate(ranges):
        if start <= char_pos < end:
            return index
    return len(ranges) - 1 if ranges else -1


def _tail_indices(
    window: list[int], tokenized: list[tuple[str, int, int]], overlap: int
) -> list[int]:
    if not window or overlap <= 0:
        return []
    tokens = 0
    tail: list[int] = []
    for item in reversed(window):
        tail.insert(0, item)
        tokens += tokenized[item][2]
        if tokens >= overlap:
            break
    return tail