from __future__ import annotations

import json
from pathlib import Path

from processed.runner import ProcessedRunner

_FILTERED_PII = {"EMAIL": 0, "URL": 0, "IP": 0, "PHONE": 0, "CPF": 0, "RG": 0, "ENDEREÇO": 0}


def test_runner_end_to_end_on_fixtures(tmp_path: Path) -> None:
    runner = ProcessedRunner(
        raw_root=tmp_path / "raw",
        out_root=tmp_path / "out",
        log=lambda _message: None,
    )
    manifest, report = runner.run()

    assert report.valid, report.issues
    assert report.total == 5
    assert report.completed == 1
    assert report.no_text == 1
    assert report.filtered == 1
    assert report.duplicate == 1
    assert report.skipped == 1
    assert report.remaining_pii == _FILTERED_PII

    outer = tmp_path / "out"
    assert (outer / "manifests" / "processed.json").exists()
    for dataset in ("text", "chunks", "instruction"):
        path = outer / "datasets" / f"{dataset}.jsonl"
        assert path.exists()
        assert path.stat().st_size > 0

    completed_file = outer / "text" / "fixture-a.txt"
    assert completed_file.exists()
    completed_text = completed_file.read_text(encoding="utf-8")
    assert "maria.silva@exemplo.com" not in completed_text
    assert "123.456.789-00" not in completed_text
    assert "maria da silva santos" not in completed_text.casefold()

    completed_entries = [
        record
        for record in manifest["records"]
        if record.get("status") == "completed"
    ]
    assert len(completed_entries) == 1
    assert completed_entries[0]["chunk_count"] >= 1

    text_lines = [
        json.loads(line)
        for line in (outer / "datasets" / "text.jsonl").read_text(encoding="utf-8").splitlines()
        if line
    ]
    assert len(text_lines) == 1
    assert text_lines[0]["id"] == "fixture-a"
    assert text_lines[0]["text"]


def test_runner_reuses_existing_raw_collection(tmp_path: Path) -> None:
    from processed.fixtures import build_fixtures

    raw_root = tmp_path / "raw"
    build_fixtures(raw_root)
    assert (raw_root / "manifests" / "collection.json").exists()

    runner = ProcessedRunner(
        raw_root=raw_root,
        out_root=tmp_path / "out",
        log=lambda _message: None,
    )
    manifest, report = runner.run()
    assert report.valid
    assert report.completed == 1
    assert manifest["raw_manifest"].endswith("collection.json")