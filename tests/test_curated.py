from __future__ import annotations

import json
from pathlib import Path

from curated.build import build_curated
from processed.runner import ProcessedRunner


def _run_processed(tmp_path: Path) -> Path:
    runner = ProcessedRunner(
        raw_root=tmp_path / "raw",
        out_root=tmp_path / "processed",
        log=lambda _message: None,
    )
    runner.run()
    return tmp_path / "processed"


def test_curated_denormalizes_chunks_with_full_metadata(tmp_path: Path) -> None:
    processed_root = _run_processed(tmp_path)

    report = build_curated(
        processed_root,
        tmp_path / "curated",
        log=lambda _message: None,
    )

    assert report.ok
    assert report.document_count == 1
    assert report.chunk_count == 1
    assert report.missing_chunks == ()

    curated_root = tmp_path / "curated"
    dataset_path = curated_root / "datasets" / "chunks.jsonl"
    assert dataset_path.exists()

    rows = [json.loads(line) for line in dataset_path.read_text(encoding="utf-8").splitlines() if line]
    assert len(rows) == 1
    row = rows[0]

    assert row["chunk_id"] == "fixture-a-chunk-000"
    assert row["bdtd_id"] == "fixture-a"
    assert row["cluster_id"] == "fixture-a"
    assert row["position"] == 0
    assert row["tokens"] > 0
    assert row["text"]

    assert row["title"] == "Aprendizado de máquina em sistemas de informação"
    assert row["authors"] == ["Maria da Silva Santos"]
    assert row["institution"] == "Universidade Exemplo"
    assert row["repository"] == "Exemplo"
    assert row["date"] == "2024"
    assert row["document_type"] == "Tese"
    assert row["language"] == "pt"
    assert row["access_rights"] == "open access"
    assert row["source_url"] == "https://repositorio.exemplo.br/teses/a.pdf"
    assert row["subjects"] == ["Computação", "Informação"]

    manifest_path = curated_root / "manifests" / "curated.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["document_count"] == 1
    assert manifest["chunk_count"] == 1
    assert manifest["missing_chunks"] == []


def test_curated_writes_datacard(tmp_path: Path) -> None:
    processed_root = _run_processed(tmp_path)

    build_curated(processed_root, tmp_path / "curated", log=lambda _message: None)

    datacard_path = tmp_path / "curated" / "DATACARD.md"
    assert datacard_path.exists()
    datacard = datacard_path.read_text(encoding="utf-8")

    assert "DATACARD" in datacard
    assert "fixtures sintéticas" in datacard
    assert "Documentos completos (com texto e chunks): 1" in datacard
    assert "Chunks no dataset: 1" in datacard
    assert "`pt`: 1" in datacard
    assert "Universidade Exemplo: 1" in datacard
    assert "chunk_id" in datacard
    assert "Limitações conhecidas" in datacard


def test_curated_reports_missing_chunks_file(tmp_path: Path) -> None:
    processed_root = _run_processed(tmp_path)
    chunks_file = next((processed_root / "chunks").glob("*.jsonl"))
    chunks_file.unlink()

    report = build_curated(
        processed_root,
        tmp_path / "curated",
        log=lambda _message: None,
    )

    assert not report.ok
    assert report.chunk_count == 0
    assert report.missing_chunks == ("fixture-a",)
