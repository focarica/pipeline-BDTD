from __future__ import annotations

from processed.cleaner import clean_text, _fix_mojibake


def test_mojibake_latin1_utf8() -> None:
    assert _fix_mojibake("CafÃ© com aÃ§Ãºcar") == "Café com açúcar"


def test_normalizes_nfc() -> None:
    composing = "cafe\u0301 para todos"
    cleaned = clean_text(composing)
    assert "café para todos" in cleaned


def test_strips_page_numbers() -> None:
    text = "1 INTRODUÇÃO\n23\nEste é o corpo do texto.\n42\n"
    cleaned = clean_text(text)
    assert "\n23\n" not in cleaned
    assert "Este é o corpo do texto." in cleaned


def test_collapses_blank_lines() -> None:
    text = "parágrafo um.\n\n\n\n\nparágrafo dois.\n"
    cleaned = clean_text(text)
    assert "\n\n\n" not in cleaned


def test_removes_repeated_footer_lines() -> None:
    text = (
        "UNIVERSIDADE EXEMPLO SAUDÁVEL\n"
        "1 INTRODUÇÃO\n"
        "Este é o conteúdo da página um.\n"
        "UNIVERSIDADE EXEMPLO SAUDÁVEL\n"
        "continuação do conteúdo na página dois\n"
        "UNIVERSIDADE EXEMPLO SAUDÁVEL\n"
        "final do conteúdo.\n"
    )
    cleaned = clean_text(text)
    assert "UNIVERSIDADE EXEMPLO SAUDÁVEL" not in cleaned


def test_rejoins_hyphenation() -> None:
    text = "Esta palavra ficou parti-\ncionalmente dividida na linha.\n"
    cleaned = clean_text(text)
    assert "particionalmente" in cleaned


def test_cuts_front_matter_and_references() -> None:
    text = (
        "FOLHA DE ROSTO\n"
        "UNIVERSIDADE EXEMPLO\n"
        "1 INTRODUÇÃO\n"
        "Conteúdo da introdução do trabalho.\n"
        "2 METODOLOGIA\n"
        "Descrição metodológica principal.\n"
        "REFERÊNCIAS BIBLIOGRÁFICAS\n"
        "AUTOR, X. Obra qualquer."
    )
    cleaned = clean_text(text)
    assert "FOLHA DE ROSTO" not in cleaned
    assert "REFERÊNCIAS" not in cleaned
    assert "Conteúdo da introdução do trabalho." in cleaned
    assert "AUTOR, X." not in cleaned