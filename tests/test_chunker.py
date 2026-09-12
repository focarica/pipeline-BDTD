from __future__ import annotations

from processed.chunker import chunk_document, split_sections


def test_chunk_tokens_and_metadata() -> None:
    sentences = [
        f"Frase de exemplo número {index} com conteúdo suficiente para tokenizar."
        for index in range(40)
    ]
    text = " ".join(sentences)
    chunks = chunk_document("doc-1", text, target_tokens=64, overlap=16)
    assert chunks
    first = chunks[0]
    assert first["record_id"] == "doc-1"
    assert first["position"] == 0
    assert first["tokens"] > 0
    assert first["page"] >= 1
    assert first["section"]
    assert "text" in first
    assert all(chunk["tokens"] > 0 for chunk in chunks)
    assert chunks[-1]["position"] == len(chunks) - 1


def test_overlap_repeats_tail() -> None:
    sentences = [
        f"Frase de exemplo número {index} com conteúdo suficiente para tokenizar."
        for index in range(80)
    ]
    text = " ".join(sentences)
    chunks = chunk_document("doc-2", text, target_tokens=48, overlap=24)
    assert len(chunks) >= 2
    first_of_second = next(
        sentence for sentence in sentences if chunks[1]["text"].startswith(sentence)
    )
    assert first_of_second in chunks[0]["text"]


def test_split_sections_detects_headings() -> None:
    text = (
        "1 INTRODUÇÃO\n"
        "corpo da introdução.\n"
        "2 METODOLOGIA\n"
        "corpo da metodologia.\n"
        "3 RESULTADOS\n"
        "corpo dos resultados.\n"
    )
    sections = split_sections(text)
    names = [section.name for section in sections]
    assert "INTRODUÇÃO" in names
    assert "METODOLOGIA" in names
    assert "RESULTADOS" in names