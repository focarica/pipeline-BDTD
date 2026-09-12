from __future__ import annotations

from processed.anonymizer import Anonymizer, assert_no_pii


def test_redacts_pii_to_placeholders() -> None:
    text = (
        "email fulano@exemplo.com para url https://exemplo.br/x e ip 192.168.0.1 "
        "tel (11) 98765-4321 cpf 123.456.789-00 rg 12.345.678-9 cep 70040-900"
    )
    anonymized, report = Anonymizer().anonymize(text, {})
    assert "<<EMAIL>>" in anonymized
    assert "<<URL>>" in anonymized
    assert "<<IP>>" in anonymized
    assert "<<PHONE>>" in anonymized
    assert "<<CPF>>" in anonymized
    assert "<<RG>>" in anonymized
    assert "<<ENDEREÇO>>" in anonymized
    assert report["EMAIL"] == 1
    assert report["CPF"] == 1
    remaining = assert_no_pii(anonymized)
    assert all(count == 0 for count in remaining.values())


def test_redacts_person_names_from_metadata() -> None:
    metadata = {
        "authors": ["Maria da Silva Santos"],
        "raw_record": {"orientador": "João Pedro de Almeida"},
    }
    text = (
        "O orientador João Pedro de Almeida e a autora Maria da Silva Santos "
        "revisaram juntos esta tese."
    )
    anonymized, report = Anonymizer().anonymize(text, metadata)
    assert "Maria da Silva Santos" not in anonymized
    assert "João Pedro de Almeida" not in anonymized
    assert anonymized.count("<<PERSON>>") >= 2
    assert report["PERSON"] >= 2


def test_assert_no_pii_flags_remaining_pii() -> None:
    remaining = assert_no_pii("ainda existe fulano@exemplo.com aqui")
    assert remaining["EMAIL"] == 1