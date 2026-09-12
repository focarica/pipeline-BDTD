from __future__ import annotations

from processed.dedup import Deduplicator, metadata_key, normalize_for_dedup


def test_normalize_for_dedup() -> None:
    assert normalize_for_dedup("  Olá  Mundo!\nAcentuação ") == "ola mundo! acentuacao"


def test_exact_duplicate_via_digest() -> None:
    text_a = "O mesmo texto exato, com acentuação e espaços extras."
    text_b = "  o mesmo texto exato com acentuação e espaços extras "
    dedup = Deduplicator()
    clusters = dedup.process(
        [
            {"bdtd_id": "a", "text": text_a, "metadata": {"title": "Um", "authors": ["X"], "date": "2020"}},
            {"bdtd_id": "b", "text": text_b, "metadata": {"title": "Dois", "authors": ["Y"], "date": "2021"}},
        ]
    )
    assert clusters["b"] == "a"
    assert clusters["a"] == "a"


def test_near_duplicate_via_lsh() -> None:
    base = " ".join(
        f"sentença única número {index} com conteúdo repetido entre os textos deste experimento"
        for index in range(300)
    )
    near = base + " adição final exclusiva para romper a igualdade exata "
    dedup = Deduplicator()
    clusters = dedup.process(
        [
            {"bdtd_id": "x", "text": base, "metadata": {"title": "Titulo X", "authors": ["A"], "date": "2020"}},
            {"bdtd_id": "y", "text": near, "metadata": {"title": "Titulo Y", "authors": ["B"], "date": "2021"}},
        ]
    )
    assert clusters["y"] == "x"


def test_title_author_year_key() -> None:
    shared = {"title": "Mesmo título repetido", "authors": ["Autor Comum"], "date": "2019"}
    dedup = Deduplicator()
    clusters = dedup.process(
        [
            {"bdtd_id": "a", "text": "conteúdo completamente diferente um", "metadata": dict(shared)},
            {"bdtd_id": "b", "text": "texto totalmente distinto dois", "metadata": dict(shared)},
        ]
    )
    assert clusters["b"] == "a"


def test_metadata_key_uses_year() -> None:
    key = metadata_key({"title": "  Título Exemplo ", "authors": ["Autor Teste"], "date": "2023-05-01"})
    assert "2023" in key
    assert "titulo exemplo" in key