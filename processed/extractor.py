"""Extração de texto de PDFs para a camada processada."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

MIN_TEXT_CHARS = 50


@dataclass(frozen=True)
class Extraction:
    """Resultado da extração de texto de um PDF."""

    text: str
    method: str = "pypdf"
    page_count: int = 0
    char_count: int = 0

    @property
    def valid(self) -> bool:
        return self.page_count > 0 and len(self.text.strip()) >= MIN_TEXT_CHARS


def extract(pdf_path: str | Path) -> Extraction:
    """Extrai o texto concatenado das páginas de um PDF usando o pypdf."""
    reader = PdfReader(str(pdf_path))
    pages = reader.pages
    parts: list[str] = []
    for page in pages:
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        parts.append(page_text)
    text = "\n\n".join(parts)
    return Extraction(
        text=text,
        method="pypdf",
        page_count=len(pages),
        char_count=len(text),
    )


def extract_text(pdf_path: str | Path) -> str:
    """Retorna apenas o texto extraído de um PDF (compatibilidade)."""
    return extract(pdf_path).text